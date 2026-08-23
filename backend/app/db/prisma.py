from prisma import Prisma
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Prisma client instance
prisma_client: Prisma | None = None


async def get_prisma() -> Prisma:
    """Get or create Prisma client instance."""
    global prisma_client
    if prisma_client is None:
        from prisma import get_client
        from prisma.errors import ClientNotRegisteredError
        try:
            prisma_client = get_client()
        except ClientNotRegisteredError:
            prisma_client = Prisma(
                datasource={
                    "url": settings.DATABASE_URL
                },
                auto_register=True,
                log_queries=settings.LOG_LEVEL == "DEBUG",
            )
        if not prisma_client.is_connected():
            import sys
            has_fileno = hasattr(sys.stdout, 'fileno')
            if not has_fileno:
                sys.stdout.fileno = lambda: 1
            await prisma_client.connect()
            if not has_fileno:
                del sys.stdout.fileno
        logger.info("Prisma client connected")
    elif not prisma_client.is_connected():
        import sys
        has_fileno = hasattr(sys.stdout, 'fileno')
        if not has_fileno:
            sys.stdout.fileno = lambda: 1
        await prisma_client.connect()
        if not has_fileno:
            del sys.stdout.fileno
        logger.info("Prisma client reconnected")
    return prisma_client


async def close_prisma() -> None:
    """Close Prisma client connection."""
    global prisma_client
    if prisma_client and prisma_client.is_connected():
        await prisma_client.disconnect()
        prisma_client = None
        logger.info("Prisma client disconnected")


@asynccontextmanager
async def prisma_context() -> AsyncGenerator[Prisma, None]:
    """Context manager for Prisma client."""
    client = await get_prisma()
    try:
        yield client
    except Exception:
        # Connection might be lost, try to reconnect next time
        global prisma_client
        if prisma_client:
            await prisma_client.disconnect()
            prisma_client = None
        raise


# Dependency for FastAPI
async def get_db() -> AsyncGenerator[Prisma, None]:
    """FastAPI dependency for database access."""
    async with prisma_context() as db:
        yield db


# RLS Helpers
# NOTE: parameterized — tenant_id is never interpolated into SQL. Callers must
# still treat these as no-ops until RLS policies exist on the Prisma-managed
# tables (see middleware note on application-layer isolation).

import re as _re

_UUID_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.IGNORECASE
)


async def set_tenant_context(db: Prisma, tenant_id: str) -> None:
    """Set PostgreSQL RLS context for the current tenant (parameterized)."""
    if not _UUID_RE.match(tenant_id or ""):
        raise ValueError("tenant_id must be a UUID")
    await db.execute_raw("SELECT set_current_tenant($1)", tenant_id)


async def clear_tenant_context(db: Prisma) -> None:
    """Clear PostgreSQL RLS context."""
    await db.execute_raw("RESET app.current_tenant")