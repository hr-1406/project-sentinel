"""
Phase 0 - Database Engine & Session Factory
Project Sentinel

Connects to a local PostgreSQL instance using SQLAlchemy 2.0.
Reads the connection string from the DATABASE_URL environment variable,
falling back to a local default for development.

Usage:
    from database import engine, SessionLocal, init_db

    # Create all tables (idempotent)
    init_db()

    # Use a session
    with SessionLocal() as session:
        ...
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base

# -------------------------------------------------------------------
# Connection string
# Default assumes: PostgreSQL running locally on port 5432,
# database "sentinel_db", user "postgres", password "postgres".
# Override by setting the DATABASE_URL environment variable.
# -------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:raphael1111@localhost:5432/sentinel_db",
)

engine = create_engine(
    DATABASE_URL,
    echo=False,          # Set True for SQL debug logging
    pool_pre_ping=True,  # Reconnect on stale connections
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def init_db() -> None:
    """Create all tables defined in models.py (skips existing tables)."""
    Base.metadata.create_all(bind=engine)
    print("Database tables created / verified successfully.")


if __name__ == "__main__":
    init_db()
