"""
agentFlow agent — background workflow runner (three Groq calls + tools).

How this file fits the project
------------------------------
  main.py     → POST/GET /workflows; queues run_workflow(request_id) only (not goal)
  agent.py    → planner, per-task tool selection, tool execution, workflow summary (here)
  tools.py    → TOOL_DEFINITIONS / TOOL_REGISTRY; Tavily web_search; Groq summarize
  models.py   → ORM: Workflow, Task, ExecutionLog
  schema.py   → Pydantic API shapes (agent does not import schema)

Entry point: run_workflow(request_id)
  Goal is read from workflows.goal in Postgres — never passed from main.py.

Environment (.env)
------------------
  GROQ_API_KEY, GROQ_MODEL     planner, tool selector, workflow summarizer, summarize tool
  TAVILY_API_KEY               web_search in tools.py (not read here)
  AGENTFLOW_DEBUG=0            disable [DEBUG] prints in agent + tools

End-to-end flow
---------------

  User POST {"goal": "..."}
       │
       ▼
  main.create_workflow ──► INSERT workflows (pending)
       │                   background_tasks.add_task(run_workflow, request_id)
       ▼
  HTTP 201 (client polls GET /workflows/{request_id})
       │
       ▼
  run_workflow(request_id)
       │
       ├─► SessionLocal() — separate session from HTTP Depends(get_db)
       ├─► SELECT workflow BY request_id → WorkflowNotFoundError if missing
       ├─► status = "running" → commit early (GET shows running during Groq/tools)
       │
       ├─► Phase 1: plan_subtasks(goal)           Groq #1 → INSERT tasks (pending)
       │
       ├─► Phase 2: _select_and_run_tools        for each task:
       │       ├─ select_tool_for_task()          Groq #2 + catalog from get_tools()
       │       ├─ run_tool() in tools.py         Tavily web_search or Groq summarize
       │       ├─ success → status=completed, result={success, tool_output, ...}
       │       ├─ ToolExecutionError / other     → status=failed, workflow continues
       │       └─ execution_logs: tool_selection, tool_run | error
       │
       ├─► Phase 3: _finalize_workflow           Groq #3
       │       ├─ workflows.result JSONB         {summary, reasoning} [+ failed_tasks]
       │       ├─ status = completed             even if some tasks failed
       │       └─ execution_logs: results_summary
       │
       └─► db.close() in finally

  GET /workflows/{request_id}  (main._workflow_to_response)
       ├─ running:  tasks[] with name, status, result per row
       └─ completed: workflows.result populated, tasks=[] (progress hidden)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from groq import Groq
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import ExecutionLog, Task, Workflow
from backend.tools import ToolExecutionError, get_tools, run_tool

class WorkflowNotFoundError(Exception):
    """run_workflow(request_id) when no row exists in workflows."""


def _debug(step: str, **fields: Any) -> None:
    """
    Print IN/OUT at pipeline boundaries. Watch the uvicorn terminal (not the HTTP response).

    Disable: set AGENTFLOW_DEBUG=0 in .env and restart uvicorn.
    """
    if os.getenv("AGENTFLOW_DEBUG", "1").strip().lower() in ("0", "false", "no"):
        return
    print(f"\n[DEBUG] --- {step} ---")
    for key, value in fields.items():
        if isinstance(value, (dict, list)):
            print(f"  {key}:")
            print(json.dumps(value, indent=2, default=str))
        else:
            print(f"  {key}: {value!r}")


# --- Groq system prompts (model must return JSON only, no markdown fences) ---

PLANNER_SYSTEM = """You are a workflow planner for agentFlow.
Break the user's goal into 3-8 concrete, actionable subtasks.
Return ONLY valid JSON (no markdown fences), exactly this shape:
{"tasks": [{"name": "short title", "description": "what to do", "task_order": 1}]}
Rules:
- name: short string
- description: one or two sentences
- task_order: integers starting at 1; same number means tasks may run in parallel"""

TOOL_SELECTOR_SYSTEM = """You are a tool selector for agentFlow.
Pick exactly ONE tool for the given subtask from the catalog below.
Return ONLY valid JSON (no markdown): {"tool": "<tool_name>"}
The tool name must be one of the catalog names exactly."""

WORKFLOW_SUMMARIZER_SYSTEM = """You are a workflow summarizer for agentFlow.
The user had an overall goal; subtasks ran via tools (e.g. Tavily web_search). Each task has status and result.
Write a concise answer for the client. If any task failed, mention that clearly in summary and reasoning.
Use ONLY information present in task results (tool_output, errors) — do not invent facts or URLs.
Return ONLY valid JSON (no markdown fences), exactly:
{"summary": "2-5 sentences, direct answer for the user", "reasoning": "2-4 sentences explaining how task results support the summary, including any failures"}"""


# --- Groq client + JSON parsing helpers ----------------------------------------

def _groq_client() -> Groq:
    """One client per call; reads GROQ_API_KEY from .env (loaded when database.py imports)."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing — add it to .env")
    return Groq(api_key=api_key)


def _strip_json_fences(raw: str) -> str:
    """Remove optional ```json markdown wrappers from LLM output."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)
    return text


def _parse_planner_response(raw: str) -> list[dict[str, Any]]:
    """
    Turn LLM text into Python list of planned tasks.
    Models sometimes wrap JSON in ```json fences — strip those before json.loads.
    """
    data = json.loads(_strip_json_fences(raw))
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Planner JSON must contain a non-empty 'tasks' list")
    return tasks


def plan_subtasks(goal: str) -> list[dict[str, Any]]:
    """
    Groq call #1 — planner.

    Input:  workflows.goal (loaded in run_workflow)
    Output: list of dicts — caller _insert_planned_tasks writes Task rows (status pending)
    """
    _debug("plan_subtasks IN", goal=goal)
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    client = _groq_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": goal},
        ],
        temperature=0.2,
    )
    raw = response.choices[0].message.content or ""
    _debug("plan_subtasks Groq raw text", llm_response=raw)
    planned = _parse_planner_response(raw)
    _debug("plan_subtasks OUT", planned_tasks=planned)
    return planned


def _parse_workflow_summary(raw: str) -> dict[str, Any]:
    """Extract {summary, reasoning} for workflows.result JSONB."""
    data = json.loads(_strip_json_fences(raw))
    summary = data.get("summary")
    reasoning = data.get("reasoning")
    if not summary or not isinstance(summary, str):
        raise ValueError("Workflow summary JSON must contain a string 'summary'")
    if not reasoning or not isinstance(reasoning, str):
        raise ValueError("Workflow summary JSON must contain a string 'reasoning'")
    return {"summary": summary.strip(), "reasoning": reasoning.strip()}


def _parse_tool_selection(raw: str) -> str:
    """Extract tool name from {"tool": "web_search"} LLM response."""
    data = json.loads(_strip_json_fences(raw))
    tool = data.get("tool")
    if not tool or not isinstance(tool, str):
        raise ValueError("Tool selector JSON must contain a string 'tool' field")
    return tool.strip()


def select_tool_for_task(
    task_name: str,
    task_description: str | None,
    tool_catalog: list[dict[str, str]],
) -> str:
    """
    Groq call #2 — tool selector (once per task).

    Input:  task title + description + TOOL_DEFINITIONS from tools.py
    Output: tool name string — must match a key in tools.TOOL_REGISTRY
    """
    _debug(
        "select_tool_for_task IN",
        task_name=task_name,
        task_description=task_description,
        tool_catalog=tool_catalog,
    )
    catalog_text = json.dumps(tool_catalog, indent=2)
    _debug("catalog JSON pasted into Groq prompt", catalog_json=catalog_text)
    user_content = (
        f"Subtask name: {task_name}\n"
        f"Subtask description: {task_description or '(none)'}\n\n"
        f"Tool catalog:\n{catalog_text}"
    )
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    client = _groq_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": TOOL_SELECTOR_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
    )
    raw = response.choices[0].message.content or ""
    _debug("select_tool_for_task Groq raw text", llm_response=raw)
    tool_name = _parse_tool_selection(raw)
    _debug("select_tool_for_task OUT", tool_name=tool_name)
    return tool_name


def summarize_workflow(goal: str, task_snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Groq call #3 — workflow-level summary for the client.

    Input:  goal + snapshots with name, description, status, result (incl. tool_output / errors)
    Output: {summary, reasoning} — merged into workflows.result by _finalize_workflow
    """
    _debug("summarize_workflow IN", goal=goal, task_snapshots=task_snapshots)
    payload = json.dumps({"goal": goal, "tasks": task_snapshots}, indent=2, default=str)
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    client = _groq_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": WORKFLOW_SUMMARIZER_SYSTEM},
            {
                "role": "user",
                "content": (
                    "Synthesize the following workflow for the client.\n\n" + payload
                ),
            },
        ],
        temperature=0.3,
    )
    raw = response.choices[0].message.content or ""
    _debug("summarize_workflow Groq raw text", llm_response=raw)
    result = _parse_workflow_summary(raw)
    _debug("summarize_workflow OUT", workflow_result=result)
    return result


# --- DB: execution_logs audit trail + per-task tool loop -----------------------

def _log_execution(
    db: Session,
    workflow_id: UUID,
    task_id: UUID,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """
    Append-only execution_logs row (never UPDATE).

    event_type examples: tool_selection, tool_run, error, results_summary
    payload: JSONB — tool name, tool output snapshot, or error dict
    """
    db.add(
        ExecutionLog(
            workflow_id=workflow_id,
            task_id=task_id,
            event_type=event_type,
            message=message,
            payload=payload,
        )
    )


def _select_and_run_tools(db: Session, workflow: Workflow) -> None:
    """
    Phase 2 — one Groq tool pick + one tools.run_tool() per Task row.

    Success (tools.py returns dict):
      task.status = "completed"
      task.result = {selected_tool, success: true, tool_output: {...}}

    Failure (ToolExecutionError or unexpected Exception):
      task.status = "failed"
      task.result = {selected_tool, success: false, error: {...}, tool_output: null}
      Loop continues — other tasks still run; workflow still reaches Phase 3.

    See tools.py for web_search (Tavily) and summarize (Groq) output shapes.
    """
    tool_catalog, tool_registry = get_tools()
    _debug(
        "tool catalog ready for this workflow",
        catalog=tool_catalog,
        available_tools=list(tool_registry.keys()),
    )
    tasks = (
        db.query(Task)
        .filter(Task.workflow_id == workflow.id)
        .order_by(Task.task_order, Task.created_at)
        .all()
    )
    _debug("_select_and_run_tools IN", workflow_request_id=workflow.request_id, task_count=len(tasks))
    for task in tasks:
        _debug("task loop", task_name=task.name, task_description=task.description, task_order=task.task_order)
        tool_name = select_tool_for_task(
            task.name,
            task.description,
            tool_catalog,
        )
        _log_execution(
            db,
            workflow.id,
            task.id,
            "tool_selection",
            f"Selected {tool_name!r} for {task.name!r}",
            {"tool": tool_name},
        )

        try:
            output = run_tool(
                tool_name,
                task_name=task.name,
                task_description=task.description,
            )
        except ToolExecutionError as err:
            error_payload = {
                "type": "ToolExecutionError",
                "message": str(err),
                "tool": err.tool_name,
                "details": err.details,
            }
            task.result = {
                "selected_tool": tool_name,
                "success": False,
                "error": error_payload,
                "tool_output": None,
            }
            task.status = "failed"
            _log_execution(
                db,
                workflow.id,
                task.id,
                "error",
                f"Tool {tool_name!r} failed for {task.name!r}",
                error_payload,
            )
            db.flush()
            _debug("task failed (tool error)", task_name=task.name, result=task.result)
            print(f"[agent] task {task.name!r} FAILED: {err}")
            continue

        except Exception as err:
            error_payload = {
                "type": type(err).__name__,
                "message": str(err),
                "tool": tool_name,
            }
            task.result = {
                "selected_tool": tool_name,
                "success": False,
                "error": error_payload,
                "tool_output": None,
            }
            task.status = "failed"
            _log_execution(
                db,
                workflow.id,
                task.id,
                "error",
                f"Unexpected error running {tool_name!r}",
                error_payload,
            )
            db.flush()
            print(f"[agent] task {task.name!r} FAILED: {err}")
            continue

        _log_execution(
            db,
            workflow.id,
            task.id,
            "tool_run",
            f"Ran {tool_name!r}",
            output,
        )

        task.result = {
            "selected_tool": tool_name,
            "success": True,
            "tool_output": output,
        }
        task.status = "completed"
        db.flush()
        _debug("task saved to DB (task.result)", task_name=task.name, result=task.result)
        print(f"[agent] task {task.name!r} -> tool {tool_name!r}")


def _finalize_workflow(db: Session, workflow: Workflow) -> dict[str, Any]:
    """
    Phase 3 — Groq #3: synthesize goal + all task rows into client-facing summary.

    workflows.result JSONB:
      {summary, reasoning} always
      {failed_tasks: [{name, error}, ...]} when any task.status == "failed"
      {summary_error} if the summarizer Groq call itself throws

    workflow.status is always "completed" here (partial tool failures are not workflow.failed).
    GET when completed: main returns result + tasks=[] (see main._workflow_to_response).
    """
    tasks = (
        db.query(Task)
        .filter(Task.workflow_id == workflow.id)
        .order_by(Task.task_order, Task.created_at)
        .all()
    )
    snapshots = [
        {
            "name": t.name,
            "description": t.description,
            "status": t.status,
            "result": t.result,
        }
        for t in tasks
    ]
    _debug(
        "_finalize_workflow IN",
        request_id=workflow.request_id,
        goal=workflow.goal,
        task_count=len(snapshots),
    )

    failed_tasks = [t for t in tasks if t.status == "failed"]

    try:
        workflow_result = summarize_workflow(workflow.goal, snapshots)
    except Exception as exc:
        workflow_result = {
            "summary": (
                f"Workflow finished with {len(failed_tasks)} failed task(s). "
                f"Summary LLM call failed: {exc}"
            ),
            "reasoning": "See individual task results for tool output and errors.",
            "summary_error": str(exc),
        }
        _debug("_finalize_workflow summarize failed", error=str(exc))

    if failed_tasks:
        workflow_result["failed_tasks"] = [
            {
                "name": t.name,
                "error": (t.result or {}).get("error"),
            }
            for t in failed_tasks
        ]

    workflow.result = workflow_result
    workflow.status = "completed"
    workflow.finished_at = datetime.now(timezone.utc)

    if tasks:
        _log_execution(
            db,
            workflow.id,
            tasks[0].id,
            "results_summary",
            "Workflow summary generated",
            {"workflow_result": workflow_result},
        )

    _debug(
        "_finalize_workflow OUT",
        workflow_status=workflow.status,
        workflow_result=workflow.result,
        finished_at=str(workflow.finished_at),
    )
    return workflow_result


def _insert_planned_tasks(db: Session, workflow: Workflow, planned: list[dict[str, Any]]) -> None:
    """Planner JSON → Task rows: status pending, result NULL until Phase 2."""
    for index, item in enumerate(planned):
        name = item.get("name")
        if not name or not str(name).strip():
            raise ValueError(f"Task at index {index} missing non-empty 'name'")
        description = item.get("description")
        task_order = item.get("task_order", index + 1)
        db.add(
            Task(
                workflow_id=workflow.id,
                name=str(name).strip(),
                description=str(description).strip() if description else None,
                status="pending",
                task_order=int(task_order),
            )
        )


# --- Entry point (called from main.py BackgroundTasks) -------------------------

def run_workflow(request_id: str) -> None:
    """
    Background entry point — main.py passes only request_id.

    Session: open → phases 0–3 → commit per phase → close in finally.
    Uncaught exception after status=running: rollback, set workflow.status=failed, re-raise.
    Per-task tool failures do NOT fail the whole workflow (handled inside _select_and_run_tools).
    """
    db = SessionLocal()
    workflow: Workflow | None = None
    try:
        _debug("run_workflow IN", request_id=request_id)

        # --- Phase 0: load workflow from DB (goal is on this row) ---
        workflow = (
            db.query(Workflow).filter(Workflow.request_id == request_id).first()
        )
        if workflow is None:
            raise WorkflowNotFoundError(
                f"Workflow {request_id!r} not found — cannot run agent"
            )

        _debug(
            "run_workflow loaded from DB",
            request_id=workflow.request_id,
            goal=workflow.goal,
            status_before=workflow.status,
        )

        workflow.status = "running"
        db.commit()  # commit early so GET shows running during slow Groq calls
        _debug("run_workflow DB commit", workflow_status=workflow.status)

        # --- Phase 1: planner → tasks table ---
        planned = plan_subtasks(workflow.goal)
        _insert_planned_tasks(db, workflow, planned)
        db.commit()
        _debug("run_workflow Phase 1 done", tasks_inserted=len(planned))

        # --- Phase 2: tool selector + tools.run_tool per task ---
        _select_and_run_tools(db, workflow)
        db.commit()
        _debug("run_workflow Phase 2 done", message="all tools run, task.result saved")

        # --- Phase 3: workflow summary for client (workflows.result) ---
        final = _finalize_workflow(db, workflow)
        db.commit()
        _debug("run_workflow Phase 3 done", workflow_status=workflow.status, result=final)

        print(
            f"[agent] {request_id}: completed, {len(planned)} task(s), "
            f"summary: {final.get('summary', '')[:120]}..."
        )
    except Exception as exc:
        _debug("run_workflow ERROR", error_type=type(exc).__name__, error_message=str(exc))
        db.rollback()
        if workflow is not None:
            failed = (
                db.query(Workflow)
                .filter(Workflow.request_id == request_id)
                .first()
            )
            if failed is not None and failed.status == "running":
                failed.status = "failed"
                db.commit()
        raise
    finally:
        db.close()


# if __name__ == "__main__":
#     """
#     Local dev only — production uses main.py BackgroundTasks → run_workflow.

#     Full pipeline (DB + Tavily + execution_logs):
#       uvicorn backend.main:app --reload
#       POST /workflows in /docs

#     Terminal shortcuts:
#       python -m backend.agent           # Groq planner + one tool (no DB)
#       python -m backend.agent WF_5    # run_workflow for existing request_id
#     """
#     import sys

#     if len(sys.argv) > 1:
#         run_workflow(sys.argv[1])
#     else:
#         # No DB in this path — only Groq + tools. See [DEBUG] blocks above each step.
#         goal = "I want to buy a new laptop"
#         print("\n=== LOCAL TEST: planner -> catalog -> tool pick -> run_tool (no database) ===\n")

#         planned = plan_subtasks(goal)
#         catalog, registry = get_tools()

#         if not planned:
#             print("Planner returned no tasks — stopping.")
#         else:
#             first = planned[0]
#             print(f"\n--- First task only: {first['name']!r} ---\n")

#             # Capture return values — do not use tool_name before this line.
#             tool_name = select_tool_for_task(
#                 first["name"],
#                 first.get("description"),
#                 catalog,
#             )
#             output = run_tool(
#                 tool_name,
#                 task_name=first["name"],
#                 task_description=first.get("description"),
#             )

#             print("\n=== SUMMARY (what this script stored in variables) ===")
#             print(f"  catalog tools: {[t['name'] for t in catalog]}")
#             print(f"  registry keys: {list(registry.keys())}")
#             print(f"  tool_name:     {tool_name!r}")
#             print(f"  tool_output:   {json.dumps(output, indent=2)}")
#             print("\nFull pipeline with DB + all tasks:")
#             print("  uvicorn backend.main:app --reload  ->  POST /workflows in /docs")
#             print("  or: python -m backend.agent WF_<n>")