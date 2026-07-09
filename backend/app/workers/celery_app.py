from celery import Celery
from celery.signals import worker_init, worker_shutdown
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
    "app.workers.tasks.sync_task_to_integration": {"queue": "integrations"},
    "app.workers.tasks.retry_failed_sync": {"queue": "integrations"},
}


@worker_init.connect
def init_worker(**kwargs):
    """Initialize worker resources."""
    logger.info("Celery worker initializing")


@worker_shutdown.connect
def shutdown_worker(**kwargs):
    """Cleanup worker resources."""
    logger.info("Celery worker shutting down")


# ─── Async Task Wrapper ───

def async_task(task_func):
    """Decorator to run async functions in Celery tasks."""
    def wrapper(*args, **kwargs):
        return asyncio.run(task_func(*args, **kwargs))
    return wrapper