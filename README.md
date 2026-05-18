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

## Team Lead Agent

| File | Used by |
|------|---------|
| `.cursor/agents/team-lead.md` | **Cursor subagent** — source prompt; invoke with `/team-lead` |
| `.cursor/skills/team-lead/SKILL.md` | **Cursor slash menu** — type `/` in Agent chat and pick **team-lead** |
| `.github/agents/team-lead.agent.md` | **GitHub Copilot** only (not Cursor) |

Edit `.cursor/agents/team-lead.md` for Cursor. Keep `.github/agents/team-lead.agent.md` in sync only if you use GitHub Copilot.

### Quick access in Cursor

1. Open **Agent** chat (`Ctrl+I`).
2. Type **`/`** — open the command/skill menu.
3. Select **team-lead**, then ask your question.

Or type directly: `/team-lead How should I structure the workflow planner?`

The **mode** dropdown (Agent / Ask / Plan / Debug) cannot list custom agents; that menu is for modes only.

If **team-lead** does not appear: **Developer: Reload Window**, confirm the folder `c:\agentFlow` is open (not only a loose file), and check **Cursor Settings → Rules** for the skill.

### Optional: terminal CLI (`agent_manager/`)

`agent_manager/` is **not required** for Cursor. It is a small Python script that runs the same mentor prompt in a terminal (useful without the IDE). Remove the folder if you do not need that.

```powershell
.\venv\Scripts\Activate.ps1
py -m agent_manager.team_lead_agent "How should I architect the task planner?"
```

Set `OPENAI_API_KEY` in `.env` for AI-powered CLI responses.

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
