-- =============================================================
-- EXISTING database: add workflow_id to execution_logs
-- Run in pgAdmin on agentFlow DB if table already exists without this column.
-- =============================================================
ALTER TABLE execution_logs
    ADD COLUMN IF NOT EXISTS workflow_id UUID;

-- Backfill from tasks (required before NOT NULL + FK)
UPDATE execution_logs el
SET workflow_id = t.workflow_id
FROM tasks t
WHERE el.task_id = t.id
  AND el.workflow_id IS NULL;

ALTER TABLE execution_logs
    ALTER COLUMN workflow_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'execution_logs_workflow_id_fkey'
    ) THEN
        ALTER TABLE execution_logs
            ADD CONSTRAINT execution_logs_workflow_id_fkey
                FOREIGN KEY (workflow_id) REFERENCES workflows (id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_execution_logs_workflow_id
    ON execution_logs (workflow_id, created_at);
