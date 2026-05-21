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
# override=True: .env wins over stale shell env vars (e.g. old DB_PASSWORD).
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)


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

# Engine: pool of connections to Postgres (reuse TCP links across requests).
engine = create_engine(DATABASE_URL)

# Connection → run SQL directly (SELECT 1, raw queries).
# Session → work with Python objects (Workflow, Task), and SQLAlchemy turns that into SQL
# using a connection from the pool when you db.add(), commit(), or query.
# Routes use session (get_db), not raw connections — except health checks / one-off SQL.

# SessionLocal: factory for one session per request (not thread-safe — create one per request).
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base: registry + parent class for all ORM models (Workflow, Task, ExecutionLog in models.py).
# Every model must inherit from this same Base (class Workflow(Base): ...).
# Without it, plain Python classes are just classes—SQLAlchemy would not know which
# objects belong to which Postgres tables, columns, or relationships. Base collects
# subclasses at import time so the ORM can map rows ↔ instances and generate SQL.
Base = declarative_base()


def create_database_connection():
    """Return True if Postgres is reachable; None on failure (for startup checks or /health)."""
    # Uses a connection (raw SQL), not a session — we only need to ping the database.
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

    Use this in routes (Depends(get_db)) to work with ORM models — not engine.connect().
    Why yield + finally: FastAPI runs code after yield when the response is sent,
    so the session is always closed even if the route raises an error.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# fastapi dependency to get the database session for the request
#we use depends(get_db) to get the database session for the request
# without this, we would have to manually create a database session for each request
# and close it after the request is processed
# but if soemhow before closing the session, some error occurs, the session will not be closed
#and databse will stay open and not be able to handle the next request or if this happens multiple times
#then the database will run out of memory and crash
# so we use depends(get_db) to get the database session for the request

# why yield + finally: FastAPI runs code after yield when the response is sent,
# so the session is always closed even if the route raises an error.
# so we use yield + finally to close the session even if the route raises an error.
# this is a good practice to avoid memory leaks and to ensure that the database is always closed after the request is processed.