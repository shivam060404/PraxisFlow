from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
import structlog
import time
import uuid

from app.core.config import settings
from app.db.prisma import get_prisma, close_prisma, set_tenant_context, get_db
from app.schemas import HealthResponse, ErrorResponse
from app.workers.kafka_consumers import startup_kafka, shutdown_kafka

# ─── Enterprise Components ───
from app.observability import init_observability, shutdown_observability, get_otel_logger, genai_tracer, LLMCallAttributes
from app.observability.langfuse_client import init_langfuse, get_langfuse_client
from app.guardrails.manager import guardrails_manager
from app.security import (
    TenantIsolationMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    RequestValidationMiddleware,
    AuditLoggingMiddleware,
    build_security_middleware_stack,
    get_cors_config,
)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting PraxisFlow Backend", environment=settings.ENVIRONMENT)
    
    # Initialize Prisma
    await get_prisma()
    
    # Initialize observability stack
    init_observability(
        service_name="praxisflow-api",
        version="2.0.0",
    )
    logger.info("OpenTelemetry initialized")
    
    # Initialize Langfuse
    init_langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
    )
    logger.info("Langfuse initialized")
    
    # Initialize guardrails
    await guardrails_manager.initialize()
    logger.info("Guardrails initialized")
    
    # Initialize Kafka consumers
    await startup_kafka()
    
    yield
    
    # Shutdown
    logger.info("Shutting down PraxisFlow Backend")
    await shutdown_kafka()
    await close_prisma()
    shutdown_observability()
    
    # Flush Langfuse
    langfuse_client = get_langfuse_client()
    if langfuse_client:
        langfuse_client.flush()


app = FastAPI(
    title="PraxisFlow - Enterprise AI Meeting Intelligence",
    description="Transform passive meeting recordings into structured, trackable, and accountable execution workflows",
    version="2.0.0",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    **get_cors_config(),
)

# ─── Security Middleware Stack (order matters: outer to inner) ───
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


# ─── Process Time Middleware (for metrics) ───
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add X-Process-Time header and log requests."""
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]
    
    # Add request ID to structlog context
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Request-ID"] = request_id
    
    # Log with OTel logger
    otel_logger = get_otel_logger("praxisflow.api")
    otel_logger.info(
        "HTTP Request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        process_time_ms=round(process_time * 1000, 2),
    )
    
    return response


# ─── Exception Handlers ───

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Validation error", errors=exc.errors(), path=request.url.path)
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning("HTTP exception", status_code=exc.status_code, detail=exc.detail, path=request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": getattr(exc, "code", None)},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# ─── Health Check ───

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    db = await get_prisma()
    
    # Check database
    db_healthy = False
    try:
        await db.execute_raw("SELECT 1")
        db_healthy = True
    except Exception:
        pass
    
    # Check other services
    services = {
        "database": "healthy" if db_healthy else "unhealthy",
        "qdrant": "unknown",
        "neo4j": "unknown",
        "kafka": "unknown",
        "redis": "unknown",
        "llm_gateway": "unknown",
    }
    
    # Try to check Qdrant
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://qdrant:6333/healthz")
            services["qdrant"] = "healthy" if resp.status_code == 200 else "unhealthy"
    except Exception:
        services["qdrant"] = "unhealthy"
    
    # Try to check Redis
    try:
        import redis.asyncio as redis
        r = redis.from_url("redis://redis:6379")
        await r.ping()
        services["redis"] = "healthy"
    except Exception:
        services["redis"] = "unhealthy"
    
    # Try to check LLM Gateway
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://llm-gateway:4000/health/liveliness")
            services["llm_gateway"] = "healthy" if resp.status_code == 200 else "unhealthy"
    except Exception:
        services["llm_gateway"] = "unhealthy"
    
    overall_status = "healthy" if all(v == "healthy" for v in services.values()) else "degraded"
    
    return HealthResponse(
        status=overall_status,
        version="2.0.0",
        environment=settings.ENVIRONMENT,
        services=services,
    )


@app.get("/ready", tags=["Health"])
async def readiness_check():
    """Kubernetes readiness probe."""
    db = await get_prisma()
    try:
        await db.execute_raw("SELECT 1")
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Not ready")


@app.get("/live", tags=["Health"])
async def liveness_check():
    """Kubernetes liveness probe."""
    return {"status": "alive"}


# ─── API Routes ───

from app.api import meetings, tasks, transcripts, integrations, websocket, users, metrics, admin, compliance, webhooks

app.include_router(meetings.router, prefix=settings.API_V1_PREFIX)
app.include_router(tasks.router, prefix=settings.API_V1_PREFIX)
app.include_router(transcripts.router, prefix=settings.API_V1_PREFIX)
app.include_router(integrations.router, prefix=settings.API_V1_PREFIX)
app.include_router(websocket.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(metrics.router, prefix=settings.API_V1_PREFIX)
app.include_router(admin.router, prefix=settings.API_V1_PREFIX)
app.include_router(compliance.router, prefix=settings.API_V1_PREFIX)
app.include_router(webhooks.router, prefix=settings.API_V1_PREFIX)


# ─── Root ───

@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "PraxisFlow - Enterprise AI Meeting Intelligence",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health",
        "readiness": "/ready",
        "liveness": "/live",
    }