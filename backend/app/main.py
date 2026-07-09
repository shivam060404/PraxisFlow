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
    logger.info("Starting AMI Backend", environment=settings.ENVIRONMENT)
    
    # Initialize Prisma
    await get_prisma()
    
    # Initialize Kafka consumers
    await startup_kafka()
    
    yield
    
    # Shutdown
    logger.info("Shutting down AMI Backend")
    await shutdown_kafka()
    await close_prisma()


app = FastAPI(
    title="AI Meeting Intelligence & Action Command Center",
    description="Transform passive meeting recordings into structured, trackable, and accountable execution workflows",
    version="0.1.0",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Middleware ───

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add X-Process-Time header and log requests."""
    start_time = time.time()
    request_id = str(uuid.uuid4())
    
    # Add request ID to structlog context
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Request-ID"] = request_id
    
    logger.info(
        "HTTP Request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        process_time_ms=round(process_time * 1000, 2),
    )
    
    return response


@app.middleware("http")
async def tenant_isolation_middleware(request: Request, call_next):
    """Extract tenant from JWT and set RLS context."""
    # Skip for health checks and docs
    if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"]:
        return await call_next(request)
    
    # Extract tenant from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Missing or invalid Authorization header"},
        )
    
    token = auth_header.replace("Bearer ", "")
    
    # TODO: Validate JWT and extract tenant_id
    # For now, use dev tenant
    tenant_id = "00000000-0000-0000-0000-000000000001"
    
    # Set RLS context for this request
    db = await get_prisma()
    await set_tenant_context(db, tenant_id)
    
    # Add tenant_id to request state for downstream use
    request.state.tenant_id = tenant_id
    
    response = await call_next(request)
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
    
    return HealthResponse(
        status="healthy" if db_healthy else "degraded",
        version="0.1.0",
        environment=settings.ENVIRONMENT,
        services={
            "database": "healthy" if db_healthy else "unhealthy",
            "qdrant": "unknown",
            "neo4j": "unknown",
            "kafka": "unknown",
            "redis": "unknown",
        },
    )


# ─── API Routes ───

from app.api import meetings, tasks, transcripts, integrations, websocket, users, metrics

app.include_router(meetings.router, prefix=settings.API_V1_PREFIX)
app.include_router(tasks.router, prefix=settings.API_V1_PREFIX)
app.include_router(transcripts.router, prefix=settings.API_V1_PREFIX)
app.include_router(integrations.router, prefix=settings.API_V1_PREFIX)
app.include_router(websocket.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(metrics.router, prefix=settings.API_V1_PREFIX)


# ─── Root ───

@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "AI Meeting Intelligence & Action Command Center",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }