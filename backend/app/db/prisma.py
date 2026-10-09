from prisma import Prisma
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Prisma client instance
prisma_client: Prisma | None = None
webhook_lookup_client: Prisma | None = None
_tenant_proxy = None


class _TenantModelProxy:
    def __init__(self, client, model_name: str):
        self._client = client
        self._model_name = model_name

    def __getattr__(self, operation: str):
        async def invoke(*args, **kwargs):
            if not settings.RLS_ENFORCED:
                return await getattr(getattr(self._client, self._model_name), operation)(*args, **kwargs)
            tenant_id = get_request_tenant()
            if settings.RLS_ENFORCED and not _UUID_RE.match(tenant_id or ""):
                raise RuntimeError("Tenant-scoped database operation requires a verified tenant context")
            async with self._client.tx() as tx:
                if tenant_id:
                    await tx.execute_raw("SELECT set_config('app.current_tenant', $1, true)", tenant_id)
                return await getattr(getattr(tx, self._model_name), operation)(*args, **kwargs)
        return invoke


class TenantScopedPrisma:
    """Run each Prisma operation in a transaction bound to verified tenant RLS."""
    _models = {
        "tenant", "user", "meeting", "task", "integration", "aiauditlog",
        "datasubjectrequest", "complianceexport", "transcript", "utterance",
        "attendee", "meetingflag", "taskauditlog", "humanreview",
    }

    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        if name.lower() in self._models:
            return _TenantModelProxy(self._client, name)
        if name in {"execute_raw", "query_raw"}:
            async def execute(*args, **kwargs):
                if not settings.RLS_ENFORCED:
                    return await getattr(self._client, name)(*args, **kwargs)
                tenant_id = get_request_tenant()
                if settings.RLS_ENFORCED and not _UUID_RE.match(tenant_id or ""):
                    statement = str(args[0] if args else kwargs.get("query", "")).strip().rstrip(";").lower()
                    if statement == "select 1":
                        return await getattr(self._client, name)(*args, **kwargs)
                    raise RuntimeError("Tenant-scoped raw query requires a verified tenant context")
                async with self._client.tx() as tx:
                    if tenant_id:
                        await tx.execute_raw("SELECT set_config('app.current_tenant', $1, true)", tenant_id)
                    return await getattr(tx, name)(*args, **kwargs)
            return execute
        if name == "tx":
            return self._transaction
        return getattr(self._client, name)

    @asynccontextmanager
    async def _transaction(self):
        tenant_id = get_request_tenant()
        if settings.RLS_ENFORCED and not _UUID_RE.match(tenant_id or ""):
            raise RuntimeError("Tenant-scoped transaction requires a verified tenant context")
        async with self._client.tx() as tx:
            if tenant_id:
                await tx.execute_raw("SELECT set_config('app.current_tenant', $1, true)", tenant_id)
            yield tx


async def get_prisma() -> Prisma:
    """Get or create Prisma client instance."""
    global prisma_client, _tenant_proxy
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
    if _tenant_proxy is None or _tenant_proxy._client is not prisma_client:
        _tenant_proxy = TenantScopedPrisma(prisma_client)
    return _tenant_proxy


async def close_prisma() -> None:
    """Close Prisma client connection."""
    global prisma_client, _tenant_proxy
    if prisma_client and prisma_client.is_connected():
        await prisma_client.disconnect()
        prisma_client = None
        _tenant_proxy = None
        logger.info("Prisma client disconnected")
    global webhook_lookup_client
    if webhook_lookup_client and webhook_lookup_client.is_connected():
        await webhook_lookup_client.disconnect()
    webhook_lookup_client = None


async def get_webhook_lookup_prisma() -> Prisma:
    """Restricted read-only connection for resolving signed webhook tenants."""
    global webhook_lookup_client
    if not settings.WEBHOOK_LOOKUP_DATABASE_URL:
        if settings.ENVIRONMENT.lower() in {"production", "prod"}:
            raise RuntimeError("Webhook lookup database role is not configured")
        return await get_prisma()
    if webhook_lookup_client is None:
        webhook_lookup_client = Prisma(
            datasource={"url": settings.WEBHOOK_LOOKUP_DATABASE_URL},
            auto_register=True,
        )
    if not webhook_lookup_client.is_connected():
        await webhook_lookup_client.connect()
    return webhook_lookup_client


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


@asynccontextmanager
async def tenant_tx(db: Prisma):
    """
    Interactive transaction with the Row-Level-Security tenant bound to the
    connection. All queries inside run under `app.current_tenant`, enforced
    by the database itself (when the app connects as the restricted role).

    Usage:
        async with tenant_tx(db) as tx:
            tasks = await tx.task.find_many(where={...})
    """
    tenant_id = get_request_tenant()
    if not _UUID_RE.match(tenant_id or ""):
        raise RuntimeError(
            "tenant_tx() requires an authenticated tenant context "
            "(middleware must run first)"
        )

    async with db.tx() as tx:
        # is_local=true scopes the setting to THIS transaction only, which is
        # what makes it safe with pooled connections.
        await tx.execute_raw(
            "SELECT set_config('app.current_tenant', $1, true)", tenant_id
        )
        yield tx


# Dependency for FastAPI
async def get_db() -> AsyncGenerator[Prisma, None]:
    """FastAPI dependency for database access."""
    async with prisma_context() as db:
        yield db


# ─── RLS support ───
# The middleware records the verified tenant on this ContextVar per request;
# tenant_tx() binds it to the transaction's connection via set_config(...,
# is_local=true), satisfying the policies in infrastructure/docker/rls-setup.sql.
import re as _re
from contextvars import ContextVar as _ContextVar

_current_tenant_cv: _ContextVar = _ContextVar("current_rls_tenant", default="")


def set_request_tenant(tenant_id: str):
    """Record the verified tenant for the current async context."""
    return _current_tenant_cv.set(tenant_id or "")


def reset_request_tenant(token) -> None:
    _current_tenant_cv.reset(token)


def get_request_tenant() -> str:
    return _current_tenant_cv.get()

_UUID_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.IGNORECASE
)


async def set_tenant_context(db: Prisma, tenant_id: str) -> None:
    """Set PostgreSQL RLS context for the current tenant (parameterized)."""
    if not _UUID_RE.match(tenant_id or ""):
        raise ValueError("tenant_id must be a UUID")
    await db.execute_raw("SELECT set_config('app.current_tenant', $1, true)", tenant_id)


async def clear_tenant_context(db: Prisma) -> None:
    """Clear PostgreSQL RLS context."""
    await db.execute_raw("RESET app.current_tenant")
