-- =============================================================
-- EXISTING database: allow event_type 'results_summary' on execution_logs
-- Run in pgAdmin on agentFlow DB after table exists.
-- =============================================================

ALTER TABLE execution_logs
    DROP CONSTRAINT IF EXISTS execution_logs_event_type_check;

ALTER TABLE execution_logs
    ADD CONSTRAINT execution_logs_event_type_check
        CHECK (event_type IN (
            'llm_decision',
            'tool_selection',
            'tool_run',
            'tool_result',
            'task_started',
            'task_completed',
            'results_summary',
            'error'
        ));
