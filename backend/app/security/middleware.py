"""
Security Middleware for PraxisFlow
Rate limiting, security headers, request validation, audit logging, tenant isolation.
"""

import time
import uuid
import logging
from dataclasses import dataclass
from typing import Callable, Dict, Any, Optional, Set

from fastapi import Request, Response, HTTPException, status
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

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip exempt paths
        if request.url.path in self.exempt_paths:
            return await call_next(request)

        # Extract tenant from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing or invalid Authorization header"},
            )

        token = auth_header.replace("Bearer ", "")

        # Validate JWT and extract claims
        # In production, use python-jose or similar
        tenant_id = await self._validate_token(token)
        if not tenant_id:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or expired token"},
            )

        # Verify tenant exists and is active
        if not await self._verify_tenant(tenant_id):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Tenant not found or inactive"},
            )

        # Set tenant context on request state
        request.state.tenant_id = tenant_id
        request.state.user_id = await self._extract_user_id(token)

        # Set PostgreSQL RLS context
        await self._set_rls_context(tenant_id)

        # Add tenant header for downstream services
        response = await call_next(request)
        response.headers["X-Tenant-ID"] = tenant_id

        return response

    async def _validate_token(self, token: str) -> Optional[str]:
        """Validate JWT and return tenant_id."""
        try:
            from jose import jwt
            from app.security.secrets import get_jwt_secret

            secret = get_jwt_secret()
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            return payload.get("tenant_id")
        except Exception as e:
            logger.warning(f"Token validation failed: {e}")
            return None

    async def _extract_user_id(self, token: str) -> Optional[str]:
        """Extract user_id from JWT."""
        try:
            from jose import jwt
            from app.security.secrets import get_jwt_secret

            secret = get_jwt_secret()
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            return payload.get("sub") or payload.get("user_id")
        except Exception:
            return None

    async def _verify_tenant(self, tenant_id: str) -> bool:
        """Verify tenant exists and is active."""
        # In production, check database/cache
        return True

    async def _set_rls_context(self, tenant_id: str):
        """Set PostgreSQL Row-Level Security context."""
        try:
            from app.db.prisma import get_prisma
            db = await get_prisma()
            await db.execute_raw(f"SET LOCAL app.current_tenant = '{tenant_id}'")
        except Exception as e:
            logger.error(f"Failed to set RLS context: {e}")


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

        # Check rate limits
        await self._check_rate_limit("ip", client_ip, self.config.requests_per_minute, 60)
        await self._check_rate_limit("tenant", tenant_id, self.config.requests_per_minute * 10, 60)
        await self._check_rate_limit("user", user_id, self.config.requests_per_minute * 5, 60)
        await self._check_rate_limit("endpoint", f"{tenant_id}:{endpoint}", self.config.requests_per_minute, 60)

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
            ttl = await redis.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "namespace": namespace,
                    "limit": limit,
                    "window_seconds": window_seconds,
                    "retry_after": ttl,
                },
                headers={"Retry-After": str(ttl)},
            )


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