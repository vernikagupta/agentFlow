"""
SQLAlchemy ORM models for agentFlow.

These classes mirror database/table_creation.sql so Python code and Postgres
stay in sync. Run that SQL in pgAdmin first; models do not create tables on their own.

Timestamps: Python only (DB triggers for updated_at are commented out in SQL).

- INSERT: _pg_created_at / _pg_updated_at defaults (func.now()).
- UPDATE: mutate the ORM row in memory, then commit() — _pg_updated_at onupdate
  refreshes updated_at automatically.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from .database import Base


def _pg_uuid_pk() -> Column:
    """Primary key UUID; default gen_random_uuid() in Postgres (see pgcrypto in schema)."""
    return Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def _pg_created_at() -> Column:
    """Set once when the ORM inserts a row; never auto-changes afterward."""
    return Column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
    )


def _pg_updated_at() -> Column:
    """INSERT default=now(); ORM UPDATE refreshes via onupdate=func.now()."""
    return Column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )


class Workflow(Base):
    """
    One row per user-submitted request (e.g. "research AI startups").

    The orchestrator updates status/result as agents run; tasks hang off this row.
    """

    __tablename__ = "workflows"

    id = _pg_uuid_pk()
    # WF_1, WF_2, … assigned by Postgres sequence (workflow_request_id_seq) on INSERT.
    # Do not set in Python — avoids race conditions when many workflows are created at once.
    request_id = Column(
        String(50),
        nullable=False,
        unique=True,
        server_default=text("'WF_' || nextval('workflow_request_id_seq')::text"),
    )
    goal = Column(Text, nullable=False)
    # CHECK in SQL enforces valid states; mirrored here so bad values fail before INSERT.
    status = Column(Text, nullable=False, server_default="pending")
    result = Column(JSONB, nullable=True)
    created_at = _pg_created_at()
    updated_at = _pg_updated_at()
    # Null until the whole workflow finishes (success or failure).
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # Planner creates many tasks per workflow; cascade matches ON DELETE CASCADE in SQL.
    tasks = relationship(
        "Task",
        back_populates="workflow",
        cascade="all, delete-orphan",
    )
    execution_logs = relationship(
        "ExecutionLog",
        back_populates="workflow",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="workflows_status_check",
        ),
        Index("idx_workflows_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Workflow {self.request_id}>"


class Task(Base):
    """
    One subtask produced by the Planner (e.g. "Search for AI startup databases").

    task_order controls sequencing; same order value means tasks may run in parallel.
    """

    __tablename__ = "tasks"

    id = _pg_uuid_pk()
    workflow_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Text, nullable=False, server_default="pending")
    result = Column(JSONB, nullable=True)
    retry_count = Column(Integer, nullable=False, server_default="0")
    max_retries = Column(Integer, nullable=False, server_default="3")
    task_order = Column(Integer, nullable=False, server_default="1")
    created_at = _pg_created_at()
    updated_at = _pg_updated_at()
    finished_at = Column(DateTime(timezone=True), nullable=True)

    workflow = relationship("Workflow", back_populates="tasks")
    # Append-only audit trail per task; app should INSERT only, not UPDATE.
    execution_logs = relationship(
        "ExecutionLog",
        back_populates="task",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'retrying')",
            name="tasks_status_check",
        ),
        Index("idx_tasks_workflow_id", "workflow_id"),
        Index("idx_tasks_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Task {self.name!r}>"


class ExecutionLog(Base):
    """
    Append-only log of agent steps (LLM decisions, tool runs, errors).

    Never UPDATE rows—only INSERT—so you keep a full trace for debugging.
    """

    __tablename__ = "execution_logs"

    id = _pg_uuid_pk()
    workflow_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(Text, nullable=False)
    message = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=True)
    created_at = _pg_created_at()

    workflow = relationship("Workflow", back_populates="execution_logs")
    task = relationship("Task", back_populates="execution_logs")

    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'llm_decision', 'tool_selection', 'tool_run', 'tool_result', "
            "'task_started', 'task_completed', 'results_summary', 'error'"
            ")",
            name="execution_logs_event_type_check",
        ),
        Index("idx_execution_logs_workflow_id", "workflow_id", "created_at"),
        Index("idx_execution_logs_task_id", "task_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ExecutionLog {self.event_type}>"
