# > I am building an AI workflow platform called agentFlow. Users submit a goal, the system breaks it into subtasks using LLMs, executes them dynamically using tools, and returns results.
# >
# > I have already built two files:
# > - `database.py` — creates a PostgreSQL connection using SQLAlchemy and provides a session per request
# > - `models.py` — defines SQLAlchemy ORM models (Workflow, Task, ExecutionLog) that map to the database tables
# >
# > Now write `schemas.py` using Pydantic. This file should define request and response shapes only — no database logic, no imports from models.py, no writing to DB.
# >
# > It should have:
# > 1. `WorkflowCreate` — request body for POST /workflows, with a single field: `goal` (string)
# > 2. `WorkflowResponse` — response for POST /workflows, with fields: `request_id` (string), `status` (string)
# > 3. `TaskResponse` — used inside WorkflowResponse, with fields: `name` (string), `status` (string), `result` (string)
# > 4. `WorkflowResponse` should also include a `tasks` field — a list of `TaskResponse`
#
# > Note: `result` is implemented as dict | list | None to match JSONB in the DB (see comments below).

"""
Pydantic request/response shapes for the API.

No database imports here — validation and API contracts only.

Data flow (formats at each step)
--------------------------------
1. User types in UI     →  plain text  (e.g. "Research AI startups in healthcare")
2. Frontend POST body   →  JSON        {"goal": "Research AI startups..."}
3. FastAPI + Pydantic   →  WorkflowCreate (Python str, validated & stripped)
4. You save to Postgres →  workflows.goal is TEXT; tasks/workflow result start as NULL
5. Route builds response→  WorkflowResponse (Python objects)
6. FastAPI sends HTTP    →  JSON body   (application/json)
7. Frontend receives    →  JavaScript object  (fetch → res.json())
8. UI renders for user  →  strings, cards, lists  (your React components — not raw JSON)

This file defines steps 2-3 (request) and 5-6 (response). It does NOT talk to the DB.
"""

from pydantic import BaseModel, Field, field_validator


class WorkflowCreate(BaseModel):
    """
    Incoming: POST /workflows JSON body.

    Final user only sends `goal` as text; the browser wraps it in JSON for the API.
    Invalid input → 422 before any database write.
    ... in Field description means that the field is required and must be a string
    in the JSON body.
    min_length and max_length are the constraints on the length of the string.
    """

    goal: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="User's task for the workflow engine",
    )

    @field_validator("goal")
    @classmethod
    def goal_must_not_be_blank(cls, value: str) -> str:
        # Strip spaces so "  hello  " is stored/sent as "hello"; reject "" and "   ".
        stripped = value.strip()
        if not stripped:
            raise ValueError("goal cannot be empty or whitespace only")
        return stripped


class TaskResponse(BaseModel):
    """
    One subtask in the API response (not the DB model — a read-only view).

    Maps from ORM Task row:
      name, status  →  same strings in JSON
      result        →  tasks.result JSONB: null | {"key": "value"} | [...]
    """

    name: str
    status: str
    # null in JSON when task is new; object/array when executor wrote JSONB to DB.
    result: dict | list | None = None


class WorkflowResponse(BaseModel):
    """
    Outgoing: what GET/POST /workflows returns to the frontend.

    Example JSON the user's browser receives (new workflow, no tasks yet):

      {
        "request_id": "WF_101",
        "status": "pending",
        "result": null,
        "tasks": []
      }

    Later, when done, result might be {"report": "...", "sources": [...]} — still JSON,
    not a string. The UI picks fields (e.g. result.report) to show readable text.
    """

    request_id: str
    status: str
    # null until workflow completes; then dict/list from workflows.result JSONB.
    result: dict | list | None = None
    # Empty list right after POST; filled after the planner creates Task rows.
    tasks: list[TaskResponse]
