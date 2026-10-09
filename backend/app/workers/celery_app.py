from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Create Celery app
celery_app = Celery(
    "ami_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks",
    ],
)

# Configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    task_soft_time_limit=3000,
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=100,
    result_expires=86400,  # 24 hours
)

# Task routing
celery_app.conf.task_routes = {
    "app.workers.tasks.process_meeting": {"queue": "asr"},
    "app.workers.tasks.run_extraction": {"queue": "extraction"},
    "app.workers.tasks.sync_task_to_integrations": {"queue": "integrations"},
    "app.workers.tasks.retry_failed_sync": {"queue": "integrations"},
}


@worker_process_init.connect
def init_worker_process(**kwargs):
    """Initialize per-process resources (DB + persistent checkpointer)."""
    import asyncio
    from app.ai.agents.checkpointer import init_checkpointer

    try:
        settings.validate_security_settings()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(init_checkpointer())
    except Exception:
        logger.exception("Celery worker process initialization failed")
        raise
    logger.info("Celery worker process initialized")


@worker_process_shutdown.connect
def shutdown_worker_process(**kwargs):
    """Cleanup worker resources."""
    try:
        from app.ai.agents.checkpointer import close_checkpointer
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.run_until_complete(close_checkpointer())
    except Exception:
        logger.exception("Error closing worker resources")
    logger.info("Celery worker process shutting down")


# ─── Async Task Wrapper ───

def async_task(task_func):
    """Decorator to run async functions in Celery tasks."""
    def wrapper(*args, **kwargs):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(task_func(*args, **kwargs))
    return wrapper
