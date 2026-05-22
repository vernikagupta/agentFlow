-- =============================================================
-- DEV ONLY: wipe all agentFlow tables and recreate from scratch.
-- WARNING: deletes ALL workflows, tasks, and execution_logs data.
--
-- Run in pgAdmin on the agentflow database (Query Tool → paste → Run).
-- After this, request_id sequence default works — no migrate script needed.
-- =============================================================

-- Child tables first (FK order), then parent, then sequence
DROP TABLE IF EXISTS execution_logs CASCADE;
DROP TABLE IF EXISTS tasks CASCADE;
DROP TABLE IF EXISTS workflows CASCADE;
DROP SEQUENCE IF EXISTS workflow_request_id_seq;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SEQUENCE workflow_request_id_seq START 1;

CREATE TABLE workflows (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      VARCHAR(50) NOT NULL UNIQUE
                        DEFAULT ('WF_' || nextval('workflow_request_id_seq')::text),
    goal            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX idx_workflows_status ON workflows (status);

CREATE TABLE tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL
                        REFERENCES workflows (id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'retrying')),
    result          JSONB,
    retry_count     INT NOT NULL DEFAULT 0,
    max_retries     INT NOT NULL DEFAULT 3,
    task_order      INT NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX idx_tasks_workflow_id ON tasks (workflow_id);
CREATE INDEX idx_tasks_status ON tasks (status);

CREATE TABLE execution_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL
                        REFERENCES workflows (id) ON DELETE CASCADE,
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
                            'results_summary',
                            'error'
                        )),
    message         TEXT,
    payload         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_execution_logs_workflow_id ON execution_logs (workflow_id, created_at);
CREATE INDEX idx_execution_logs_task_id ON execution_logs (task_id, created_at);

-- Quick verify (tables exist):
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('workflows', 'tasks', 'execution_logs')
ORDER BY table_name;

-- Optional test (should return WF_1):
-- INSERT INTO workflows (goal) VALUES ('reset test') RETURNING request_id, status;
