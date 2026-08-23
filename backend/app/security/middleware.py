"""
Security Middleware for PraxisFlow
Rate limiting, security headers, request validation, audit logging, tenant isolation.
"""

import time
import uuid
import logging
from dataclasses import dataclass
from typing import Callable, Dict, Any, Optional, Set

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from redis.asyncio import Redis

from app.core.config import settings
from app.security.secrets import get_redis_url

logger = logging.getLogger(__name__)


# ─── Tenant Isolation Middleware ───

class TenantIsolationMiddleware(BaseHTTPMiddleware):
    """
    Ensures strict tenant isolation at the middleware level.
    Extracts tenant from JWT, validates, and sets RLS context.
    """

    EXEMPT_PATHS = {
        "/health", "/ready", "/live",
        "/docs", "/redoc", "/openapi.json",
        "/metrics", "/favicon.ico",
    }

    def __init__(self, app, exempt_paths: Set[str] = None):
        super().__init__(app)
        self.exempt_paths = exempt_paths or self.EXEMPT_PATHS

    # Webhook receivers authenticate via provider HMAC signatures instead of
    # user JWTs. Only concrete provider slugs are exempt — management paths
    # (/webhooks/register) and HITL paths (/webhooks/hitl/*) stay JWT-gated.
    WEBHOOK_RECEIVER_PREFIX = "/api/v1/webhooks/"
    WEBHOOK_RECEIVER_PROVIDERS = {"jira", "asana", "linear", "github", "slack", "teams", "gitlab"}

    def _is_webhook_receiver(self, request: Request) -> bool:
        path = request.url.path
        if not path.startswith(self.WEBHOOK_RECEIVER_PREFIX):
            return False
        rest = path[len(self.WEBHOOK_RECEIVER_PREFIX):]
        return rest.lower() in self.WEBHOOK_RECEIVER_PROVIDERS and request.method == "POST"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip exempt paths
        if request.url.path in self.exempt_paths:
            return await call_next(request)

        # Provider webhook receivers are HMAC-authenticated inside the router
        if self._is_webhook_receiver(request):
            return await call_next(request)

        # Extract tenant from Authorization header
        from app.security.auth import verify_access_token, extract_bearer_token, AuthError

        token = extract_bearer_token(request.headers.get("Authorization"))
        if not token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing or invalid Authorization header"},
            )

        try:
            verified = await verify_access_token(token)
        except AuthError as e:
            logger.warning(f"Token validation failed: {e}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or expired token"},
            )

        # Verify the tenant exists and is active (cached briefly per process)
        if not await self._verify_tenant(verified.tenant_id):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Tenant not found or inactive"},
            )

        # Identity is authoritative here — routers must scope every query by
        # these values and never trust client-supplied tenant identifiers.
        request.state.tenant_id = verified.tenant_id
        request.state.user_id = verified.user_id
        request.state.role = verified.role
        request.state.claims = verified.claims

        # Bind the RLS context for this async context; used by tenant_tx()
        from app.db.prisma import set_request_tenant

        set_request_tenant(verified.tenant_id)

        # NOTE: Postgres RLS is NOT yet enforced on Prisma-generated tables.
        # Tenant isolation is enforced at the application layer until the
        # schema is aligned (@@map + RLS policies). Do not rely on RLS here.

        response = await call_next(request)
        response.headers["X-Tenant-ID"] = verified.tenant_id

        return response

    _tenant_cache: Dict[str, tuple] = {}

    async def _verify_tenant(self, tenant_id: str) -> bool:
        """Verify tenant exists and is active (60s in-process cache)."""
        import time as _time

        cached = self._tenant_cache.get(tenant_id)
        if cached and (_time.time() - cached[1]) < 60:
            return cached[0]

        try:
            from app.db.prisma import get_prisma

            db = await get_prisma()
            tenant = await db.tenant.find_unique(where={"id": tenant_id})
            ok = bool(tenant and getattr(tenant, "status", "active") == "active")
        except Exception as e:
            # Fail closed on DB errors — never authenticate against an
            # unverifiable tenant during infrastructure outages.
            logger.error(f"Tenant verification failed: {e}")
            ok = False

        self._tenant_cache[tenant_id] = (ok, _time.time())
        return ok


# ─── Rate Limiting Middleware ───

@dataclass
class RateLimitConfig:
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_allowance: int = 10


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Multi-tier rate limiting: per-IP, per-tenant, per-user, per-endpoint.
    Uses Redis for distributed rate limiting.
    """

    def __init__(
        self,
        app,
        config: RateLimitConfig = None,
        redis_url: str = None,
    ):
        super().__init__(app)
        self.config = config or RateLimitConfig()
        self.redis_url = redis_url or get_redis_url()
        self._redis: Optional[Redis] = None

    async def _get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip health checks
        if request.url.path in {"/health", "/ready", "/live", "/metrics"}:
            return await call_next(request)

        # Identify client
        client_ip = request.client.host if request.client else "unknown"
        tenant_id = getattr(request.state, "tenant_id", "anonymous")
        user_id = getattr(request.state, "user_id", "anonymous")
        endpoint = request.url.path

        # Check rate limits. A violation must be answered with a real 429
        # response here — HTTPException raised inside BaseHTTPMiddleware is
        # NOT caught by the app's exception handlers and surfaces as a 500.
        for namespace, identifier, limit in (
            ("ip", client_ip, self.config.requests_per_minute),
            ("tenant", tenant_id, self.config.requests_per_minute * 10),
            ("user", user_id, self.config.requests_per_minute * 5),
            ("endpoint", f"{tenant_id}:{endpoint}", self.config.requests_per_minute),
        ):
            retry_after = await self._check_rate_limit(
                namespace, identifier, limit, 60
            )
            if retry_after is not None:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Rate limit exceeded",
                        "namespace": namespace,
                        "limit": limit,
                        "retry_after": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )

        # Add rate limit headers
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.config.requests_per_minute)
        return response

    async def _check_rate_limit(
        self,
        namespace: str,
        identifier: str,
        limit: int,
        window_seconds: int,
    ):
        """Check and increment rate limit counter."""
        redis = await self._get_redis()
        key = f"ratelimit:{namespace}:{identifier}"

        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, window_seconds)

        if current > limit:
            return max(await redis.ttl(key), 1)
        return None


# ─── Security Headers Middleware ───

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to all responses."""

    def __init__(self, app, csp_policy: str = None):
        super().__init__(app)
        self.csp_policy = csp_policy or self._default_csp()

    def _default_csp(self) -> str:
        return (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' wss: https:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = self.csp_policy

        # HSTS (only in production with HTTPS)
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        return response


# ─── Request Validation Middleware ───

class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Validates request size, content type, and structure."""

    MAX_REQUEST_SIZE = 50 * 1024 * 1024  # 50MB
    ALLOWED_CONTENT_TYPES = {
        "application/json",
        "multipart/form-data",
        "application/x-www-form-urlencoded",
    }

    def __init__(self, app, max_size: int = None):
        super().__init__(app)
        self.max_size = max_size or self.MAX_REQUEST_SIZE

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check content length
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": f"Request too large. Maximum size: {self.max_size} bytes"},
            )

        # Check content type for POST/PUT/PATCH
        if request.method in {"POST", "PUT", "PATCH"}:
            content_type = request.headers.get("content-type", "").split(";")[0]
            if content_type and content_type not in self.ALLOWED_CONTENT_TYPES:
                return JSONResponse(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    content={"detail": f"Unsupported content type: {content_type}"},
                )

        # Validate JSON structure if applicable
        if request.method in {"POST", "PUT", "PATCH"}:
            content_type = request.headers.get("content-type", "")
            if content_type.startswith("application/json"):
                try:
                    body = await request.body()
                    if body:
                        import json
                        json.loads(body)
                except json.JSONDecodeError as e:
                    return JSONResponse(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        content={"detail": f"Invalid JSON: {str(e)}"},
                    )

        return await call_next(request)


# ─── Audit Logging Middleware ───

class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Logs all API requests for audit trail."""

    SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key", "x-auth-token"}
    SENSITIVE_PATHS = {"/auth/login", "/auth/register", "/auth/refresh"}

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        request_id = str(uuid.uuid4())[:8]

        # Extract context
        tenant_id = getattr(request.state, "tenant_id", "anonymous")
        user_id = getattr(request.state, "user_id", "anonymous")

        # Log request
        await self._log_request(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            tenant_id=tenant_id,
            user_id=user_id,
            ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", ""),
        )

        try:
            response = await call_next(request)

            # Log response
            duration_ms = (time.time() - start_time) * 1000
            await self._log_response(
                request_id=request_id,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

            # Add request ID to response
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            await self._log_response(
                request_id=request_id,
                status_code=500,
                duration_ms=duration_ms,
                error=str(e),
            )
            raise

    async def _log_request(self, **kwargs):
        """Log request details."""
        # Sanitize sensitive data
        log_data = {k: v for k, v in kwargs.items() if k not in self.SENSITIVE_HEADERS}
        logger.info("API Request", extra={"audit": True, **log_data})

    async def _log_response(self, **kwargs):
        """Log response details."""
        logger.info("API Response", extra={"audit": True, **kwargs})


# ─── CORS Configuration ───

def get_cors_config() -> Dict[str, Any]:
    """Get CORS configuration based on environment."""
    if settings.ENVIRONMENT == "production":
        return {
            "allow_origins": ["https://app.praxisflow.com", "https://api.praxisflow.com"],
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["*"],
            "expose_headers": ["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
            "max_age": 86400,
        }
    else:
        return {
            "allow_origins": ["http://localhost:3000", "http://localhost:8000"],
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }


# ─── Middleware Stack Builder ───

def build_security_middleware_stack(app) -> None:
    """Apply all security middleware in correct order."""

    # Order matters: outer to inner
    # 1. Audit logging (outermost - logs everything)
    app.add_middleware(AuditLoggingMiddleware)

    # 2. Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # 3. Request validation
    app.add_middleware(RequestValidationMiddleware)

    # 4. Rate limiting
    app.add_middleware(RateLimitMiddleware)

    # 5. Tenant isolation (innermost - sets context for handlers)
    app.add_middleware(TenantIsolationMiddleware)


# ─── Exports ───

__all__ = [
    "TenantIsolationMiddleware",
    "RateLimitMiddleware",
    "RateLimitConfig",
    "SecurityHeadersMiddleware",
    "RequestValidationMiddleware",
    "AuditLoggingMiddleware",
    "get_cors_config",
    "build_security_middleware_stack",
]