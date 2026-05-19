-- =============================================================
-- agentFlow PostgreSQL Schema v2
-- Built through reasoning session on 2026-05-18
-- Run in pgAdmin: select agentflow db > Tools > Query Tool > paste > Run
-- =============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;  

-- =============================================================
-- TABLE 1: workflows
-- One row per user submitted request
-- =============================================================
CREATE TABLE IF NOT EXISTS workflows (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      VARCHAR(50) NOT NULL UNIQUE,       -- human readable e.g. WF_101
    goal            TEXT NOT NULL,                     -- the user's submitted request
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    result          JSONB,                             -- final assembled output
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ                        -- null until workflow ends
);

CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows (status);

-- =============================================================
-- TABLE 2: tasks
-- One row per subtask created by the Planner Agent
-- Many tasks belong to one workflow
-- =============================================================
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL
                        REFERENCES workflows (id) ON DELETE CASCADE,
    name            TEXT NOT NULL,                     -- short title e.g. "Search for AI startups"
    description     TEXT,                              -- full detail of what the task should do
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'retrying')),
    result          JSONB,                             -- task output once complete
    retry_count     INT NOT NULL DEFAULT 0,            -- how many attempts so far
    max_retries     INT NOT NULL DEFAULT 3,            -- give up after this many
    task_order      INT NOT NULL DEFAULT 1,            -- execution order, same number = parallel
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- stale if running but not updated
    finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tasks_workflow_id ON tasks (workflow_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);

-- =============================================================
-- TABLE 3: execution_logs
-- Append only. One row per agent step inside a task.
-- Never update rows here, only INSERT.
-- =============================================================
CREATE TABLE IF NOT EXISTS execution_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL
                        REFERENCES tasks (id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL
                        CHECK (event_type IN (
                            'llm_decision',
                            'tool_selection',
                            'tool_run',
                            'tool_result',
                            'task_started',
                            'task_completed',
                            'error'
                        )),
    message         TEXT,                              -- human readable description
    payload         JSONB,                             -- structured data e.g. tool input/output
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execution_logs_task_id
    ON execution_logs (task_id, created_at);

-- =============================================================
-- AUTO UPDATE updated_at ON workflows AND tasks
-- =============================================================
-- CREATE OR REPLACE FUNCTION set_updated_at()
-- RETURNS TRIGGER AS $$
-- BEGIN
--     NEW.updated_at = NOW();
--     RETURN NEW;
-- END;
-- $$ LANGUAGE plpgsql;

-- DROP TRIGGER IF EXISTS trg_workflows_updated_at ON workflows;
-- CREATE TRIGGER trg_workflows_updated_at
--     BEFORE UPDATE ON workflows
--     FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- DROP TRIGGER IF EXISTS trg_tasks_updated_at ON tasks;
-- CREATE TRIGGER trg_tasks_updated_at
--     BEFORE UPDATE ON tasks
--     FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================
-- VERIFY: run this after to confirm all 3 tables exist
-- =============================================================
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'public'
-- ORDER BY table_name;

