"""
FastAPI orchestrator (this file).

Wires HTTP endpoints to schema validation, DB persistence, and background agent work.

FastAPI glossary (used below)
-----------------------------
  app          — the web application object; uvicorn runs this.
  route        — URL + HTTP method (GET/POST) → Python function.
  decorator    — @app.get("/path") registers a function as a route handler.
  Depends()    — "inject" a dependency (here: DB session) before your function runs.
  response_model — validate/serialize the return value to JSON for the client.
  status_code  — HTTP status to send (201 = created, 404 = not found).
  BackgroundTasks — run a function after the HTTP response is sent (non-blocking).
"""

import os

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload

from backend.agent import run_workflow
from backend.database import get_db
from backend.models import Task, Workflow
from backend.schema import TaskResponse, WorkflowCreate, WorkflowResponse

# Create the FastAPI application. Uvicorn serves this object: uvicorn backend.main:app
app = FastAPI(title="agentFlow", version="0.1.0")


# --- Global exception handler (not a route) ---------------------------------
# If any route hits a DB connection error, return 503 JSON instead of a generic 500.
@app.exception_handler(OperationalError)
def database_connection_failed(_request, _exc: OperationalError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Cannot connect to PostgreSQL. Check .env (DB_PASSWORD, DB_NAME=agentFlow), "
                "Postgres running, and reset_and_create.sql applied."
            ),
        },
    )


# --- CORS middleware --------------------------------------------------------
# Browsers block frontend (localhost:5173) from calling API (localhost:8000) unless
# the API allows that origin. Middleware runs on every request before your routes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],   # GET, POST, etc.
    allow_headers=["*"],
)


# --- Helpers: ORM rows → Pydantic response (schema.py shapes) ----------------
def _task_to_response(task: Task) -> TaskResponse:
    """Map one SQLAlchemy Task row to API JSON shape."""
    return TaskResponse(name=task.name, status=task.status, result=task.result)


def _workflow_to_response(workflow: Workflow) -> WorkflowResponse:
    """
    Build WorkflowResponse for GET polling rules:
    - completed → return final workflow.result, empty tasks list
    - otherwise → return tasks with progress, result null
    """
    if workflow.status == "completed":
        return WorkflowResponse(
            request_id=workflow.request_id,
            status=workflow.status,
            result=workflow.result,
            tasks=[],
        )
    return WorkflowResponse(
        request_id=workflow.request_id,
        status=workflow.status,
        result=None,
        tasks=[_task_to_response(t) for t in workflow.tasks],
    )


# --- Routes -----------------------------------------------------------------

@app.get("/")
def root():
    """
    GET / — optional landing page when you open http://127.0.0.1:8000 in a browser.
    Returning a dict → FastAPI converts it to JSON automatically.
    """
    return {
        "service": "agentFlow",
        "docs": "/docs",
        "health": "/health",
        "create_workflow": "POST /workflows",
        "get_workflow": "GET /workflows/{request_id}",
    }


@app.get("/health")
def health():
    """GET /health — simple liveness check (no database)."""
    return {"status": "ok"}


@app.post(
    "/workflows",
    response_model=WorkflowResponse,  # validate return value; drives OpenAPI schema in /docs
    status_code=201,                  # 201 Created (default for POST would be 200)
)
def create_workflow(
    # FastAPI reads JSON body and validates → WorkflowCreate (schema.py).
    body: WorkflowCreate,
    # Injected by FastAPI: queue for work after response (agent pipeline).
    background_tasks: BackgroundTasks,
    # Depends(get_db): call get_db(), pass yield value as db, close session after request.
    db: Session = Depends(get_db),
):
    """
    POST /workflows — create one workflow row, return request_id, start agent in background.

    Why Depends(get_db): one DB session per HTTP request; always closed in finally block.
    """
    # ORM object → SQLAlchemy will INSERT on commit. request_id comes from DB sequence.
    workflow = Workflow(
        goal=body.goal,
        status="pending",
    )
    db.add(workflow)       # stage INSERT in this session
    db.commit()            # send SQL to Postgres
    db.refresh(workflow)   # reload row so request_id (set by DB default) is on the object

    # Debug: watch uvicorn terminal (agent prints appear after this HTTP response).
    if os.getenv("AGENTFLOW_DEBUG", "1").strip().lower() not in ("0", "false", "no"):
        print(f"\n[DEBUG] --- POST /workflows IN ---\n  goal: {body.goal!r}")
        print(f"[DEBUG] --- POST /workflows OUT ---\n  request_id: {workflow.request_id!r}\n  status: {workflow.status!r}")
        print(f"[DEBUG] --- background task queued ---\n  run_workflow({workflow.request_id!r})")

    # After the client gets 201, run_workflow runs (planner → tasks → worker later).
    background_tasks.add_task(run_workflow, workflow.request_id)

    # Return Pydantic model → JSON like {"request_id":"WF_3","status":"pending",...}
    return WorkflowResponse(
        request_id=workflow.request_id,
        status=workflow.status,
        result=None,
        tasks=[],
    )


@app.get("/workflows/{request_id}", response_model=WorkflowResponse)
def get_workflow(
    # Path parameter: /workflows/WF_2 → request_id="WF_2"
    request_id: str,
    db: Session = Depends(get_db),
):
    """
    GET /workflows/{request_id} — poll status; frontend calls this repeatedly.
    """
    # joinedload: fetch workflow AND related tasks in one query (avoids N+1 queries).
    workflow = (
        db.query(Workflow)
        .options(joinedload(Workflow.tasks))
        .filter(Workflow.request_id == request_id)
        .first()  # one row or None
    )
    if workflow is None:
        # HTTPException → FastAPI returns JSON {"detail": "..."} with status 404.
        raise HTTPException(status_code=404, detail=f"Workflow {request_id!r} not found")
    return _workflow_to_response(workflow)
