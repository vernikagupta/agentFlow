"""
SQLAlchemy database setup for agentFlow.

Loads config from .env, builds a PostgreSQL URL from DB_* variables,
and exposes engine/session helpers for routes and models.
"""

import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker

# Load .env from the project root (parent of backend/), not the backend folder itself,
# so `uvicorn backend.main:app` still finds secrets when run from the repo root.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def build_database_url() -> str:
    """Build a PostgreSQL connection URL from separate DB_* env vars."""
    # Split vars (see .env.example) keep secrets out of git and match how Docker/Postgres are configured.
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "agentflow")
    # quote_plus encodes @, :, etc. in passwords so the URL stays valid.
    user = quote_plus(os.getenv("DB_USER", "postgres"))
    password = quote_plus(os.getenv("DB_PASSWORD", "postgres"))
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


# Built once at import time so all modules share the same connection settings.
DATABASE_URL = build_database_url()

# Engine: connection pool to Postgres. Reused across requests instead of opening a new TCP connection each time.
engine = create_engine(DATABASE_URL)

# SessionLocal: factory for per-request DB sessions (queries, commits). Not thread-safe on its own—one session per request.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base: registry + parent class for all ORM models (Workflow, Task, ExecutionLog in models.py).
# Every model must inherit from this same Base (class Workflow(Base): ...).
# Without it, plain Python classes are just classes—SQLAlchemy would not know which
# objects belong to which Postgres tables, columns, or relationships. Base collects
# subclasses at import time so the ORM can map rows ↔ instances and generate SQL.
Base = declarative_base()


def create_database_connection():
    """Return True if Postgres is reachable; None on failure (for startup checks or /health)."""
    try:
        with engine.connect() as conn:
            # text() is required in SQLAlchemy 2.x for raw SQL strings.
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as e:
        print(f"Error connecting to the database: {e}")
        return None


def get_db():
    """
    FastAPI dependency: yield one session per request, then close it.

    Why yield + finally: FastAPI runs code after yield when the response is sent,
    so the session is always closed even if the route raises an error.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
