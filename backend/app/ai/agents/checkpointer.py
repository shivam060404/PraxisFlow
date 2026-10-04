"""
Checkpointer lifecycle for the LangGraph extraction pipeline.

Backends:
  - "postgres": AsyncPostgresSaver over a psycopg pool. HITL thread state
    survives restarts and is shared across all API workers and Celery
    processes. Requires DATABASE_URL.
  - "memory": in-process MemorySaver (single-instance dev only).

The backend is selected with CHECKPOINTER_BACKEND (default: postgres).
Production never falls back to memory because that would silently lose HITL
state on restart.
"""

import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_checkpointer = None
_pool = None


def get_shared_checkpointer():
    """Return the initialized checkpointer.

    A memory checkpointer is allowed only for explicit development/test
    configuration. Production callers fail closed if startup initialization
    did not complete.
    """
    global _checkpointer
    if _checkpointer is None:
        if settings.ENVIRONMENT.lower() in {"production", "prod", "staging"}:
            raise RuntimeError(
                "LangGraph checkpointer is not initialized; refusing to run "
                "without durable HITL state"
            )
        from langgraph.checkpoint.memory import MemorySaver

        _checkpointer = MemorySaver()
        logger.warning(
            "Checkpointer not initialized; falling back to in-memory MemorySaver. "
            "HITL state will NOT survive restarts."
        )
    return _checkpointer


async def init_checkpointer() -> None:
    """Initialize the configured checkpointer backend. Call once at startup."""
    global _checkpointer, _pool

    backend = getattr(settings, "CHECKPOINTER_BACKEND", "postgres")

    if backend == "postgres":
        try:
            import psycopg_pool
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            conninfo = settings.DATABASE_URL
            if conninfo.startswith("postgresql://"):
                conninfo = "postgres" + conninfo[len("postgresql"):]

            _pool = psycopg_pool.AsyncConnectionPool(
                conninfo=conninfo,
                min_size=1,
                max_size=5,
                open=False,
            )
            await _pool.open()

            saver = AsyncPostgresSaver(_pool)
            await saver.setup()  # creates/verifies checkpoint tables

            _checkpointer = saver
            logger.info("LangGraph checkpointer: postgres backend ready")
            return
        except Exception as e:
            if settings.ENVIRONMENT.lower() in {"production", "prod", "staging"}:
                logger.critical("Postgres checkpointer initialization failed: %s", e)
                raise RuntimeError(
                    "Durable LangGraph checkpointer initialization failed"
                ) from e
            logger.warning(
                "Postgres checkpointer initialization failed in non-production: %s",
                e,
            )

    # memory backend or fallback
    from langgraph.checkpoint.memory import MemorySaver

    _checkpointer = MemorySaver()
    logger.info("LangGraph checkpointer: memory backend")


async def close_checkpointer() -> None:
    """Release the connection pool on shutdown."""
    global _pool, _checkpointer
    if _pool is not None:
        try:
            await _pool.close()
        except Exception as e:
            logger.warning(f"Error closing checkpoint pool: {e}")
    _pool = None
    _checkpointer = None
