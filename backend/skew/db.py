"""SQLite engine and session plumbing.

Small addition to the module map in docs/01-ARCHITECTURE.md §1: the ORM tables
live in ``skew/audit/models.py`` as specified, but the engine and session factory
are infrastructure shared by both the audit log and the IV snapshot store, so
they sit here rather than being imported across a sideways module boundary.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from skew.config import settings


class Base(DeclarativeBase):
    """Declarative base for every SKEW table."""


def _make_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    eng = create_engine(url, future=True, connect_args=connect_args)

    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            # WAL lets the API read while the loop writes.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return eng


engine: Engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create every table. Idempotent; safe to call on each start."""
    from skew.audit import models as _models  # noqa: F401 — registers the tables

    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception.

    No bare except: the exception is re-raised after rollback so failures are
    loud, per CLAUDE.md.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
