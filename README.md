# AI Workflow & Agent Platform (V1)

A starting scaffold for an AI workflow platform with:
- FastAPI backend
- PostgreSQL persistence
- Redis task queue
- Workflow/task tracking
- Async worker execution
- Retry support and execution logs

## Architecture

- `FastAPI` API gateway
- `PostgreSQL` workflow/task storage
- `Redis` async queue
- `Worker` processes tasks and creates workflow subtasks

## Getting Started

1. Copy `.env.example` to `.env`
2. Run `docker compose up --build`
3. Hit the API at `http://localhost:8000`

## Endpoints

- `POST /workflows/` — create a workflow
- `GET /workflows/{workflow_id}` — inspect workflow state
- `GET /tasks/{task_id}` — inspect task state

## Next Steps

This scaffold is intentionally minimal for Phase 1:
- single-process worker
- simple planner/executor flow
- basic schema + data model

Future phases can add:
- React/Next frontend
- shared tool registry
- vector memory search
- RBAC/auth
- distributed workers
- observability/tracing
