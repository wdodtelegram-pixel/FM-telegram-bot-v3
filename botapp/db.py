"""
Database access for a bot that has no web framework.

The original bot borrowed Flask-SQLAlchemy through the API's app factory. This
is the same idea without Flask: one engine, and a session that lives exactly as
long as one handler call.

Two rules carried over unchanged from the old bridge:

1. **A fresh session per handler.** Each call to run_db() ends with
   Session.remove(), so the next handler never sees a stale identity map and
   sees commits made by the web app straight away.
2. **No blocking the event loop.** SQLAlchemy is synchronous, so the work goes
   to a worker thread with asyncio.to_thread.

Because the session is closed when run_db() returns, return plain strings or
dicts, never model instances: touching a lazy relationship afterwards raises
DetachedInstanceError. Query AND render inside the callable.

`Base.query` and `db.session` exist so the service code reads exactly like the
API's (`Defect.query.filter(...)`, `db.session.add(...)`).
"""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from botapp import config

Session = scoped_session(sessionmaker(autoflush=True, expire_on_commit=True))
Base = declarative_base()
Base.query = Session.query_property()


class _DB:
    """Just enough of Flask-SQLAlchemy's `db` for the ported services."""
    session = Session


db = _DB()
_engine = None


def init_engine(url=None):
    global _engine
    _engine = create_engine(url or config.database_url(), pool_pre_ping=True, future=True)
    Session.configure(bind=_engine)
    return _engine


def get_engine():
    if _engine is None:
        init_engine()
    return _engine


async def run_db(fn, *args, **kwargs):
    """Run a synchronous, database-touching function off the event loop."""
    def _call():
        try:
            return fn(*args, **kwargs)
        except Exception:
            Session.rollback()
            raise
        finally:
            Session.remove()

    return await asyncio.to_thread(_call)
