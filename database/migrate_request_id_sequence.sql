-- =============================================================
-- Run ONCE if workflows.request_id has NO default (null on INSERT).
-- Symptom: ERROR null value in column "request_id" violates not-null constraint
-- Cause: table was created before sequence default was added; CREATE TABLE IF NOT EXISTS
--        does not alter existing columns.
-- =============================================================

CREATE SEQUENCE IF NOT EXISTS workflow_request_id_seq START 1;

ALTER TABLE workflows
    ALTER COLUMN request_id SET DEFAULT ('WF_' || nextval('workflow_request_id_seq')::text);

-- Sync sequence: empty table → next WF_1; max WF_5 → next WF_6. Never setval(0).
SELECT setval(
    'workflow_request_id_seq',
    GREATEST(
        COALESCE((
            SELECT MAX(CAST(substring(request_id FROM '^WF_([0-9]+)$') AS BIGINT))
            FROM workflows
            WHERE request_id ~ '^WF_[0-9]+$'
        ), 1),
        1
    ),
    EXISTS (SELECT 1 FROM workflows WHERE request_id ~ '^WF_[0-9]+$')
);

-- Verify default is set (should show nextval expression, not NULL):
SELECT pg_get_expr(d.adbin, d.adrelid) AS request_id_default
FROM pg_attrdef d
JOIN pg_class c ON c.oid = d.adrelid
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = d.adnum
WHERE c.relname = 'workflows' AND a.attname = 'request_id';

-- Test (optional — delete row after if you keep it):
-- INSERT INTO workflows (goal) VALUES ('migration test') RETURNING request_id, status;
