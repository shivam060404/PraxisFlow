"""Transactional outbox helpers for integration delivery."""

from datetime import datetime, timedelta
from typing import Any

from app.db.prisma import get_prisma


def _idempotency_key(task_id: str, integration_id: str, event_type: str) -> str:
    return f"{task_id}:{integration_id}:{event_type}"


async def enqueue_task_sync(
    task: Any,
    integration: Any,
    *,
    event_type: str = "CREATE",
    db: Any = None,
) -> Any:
    """Create one durable delivery record, safely usable inside a Prisma tx."""
    client = db or await get_prisma()
    return await client.taskoutbox.upsert(
        where={
            "idempotencyKey": _idempotency_key(
                str(task.id), str(integration.id), event_type
            )
        },
        data={
            "create": {
                "tenantId": str(task.tenantId),
                "taskId": str(task.id),
                "integrationId": str(integration.id),
                "eventType": event_type,
                "idempotencyKey": _idempotency_key(
                    str(task.id), str(integration.id), event_type
                ),
            },
            "update": {
                # A failed delivery can be explicitly re-enqueued without
                # creating a second event for the same task/integration pair.
                "status": "PENDING",
                "availableAt": datetime.utcnow(),
                "lastError": None,
            },
        },
    )


async def requeue_stale_outbox_events(db: Any = None, lease_minutes: int = 15) -> int:
    """Return abandoned PROCESSING records to the relay after a worker crash."""
    client = db or await get_prisma()
    cutoff = datetime.utcnow() - timedelta(minutes=lease_minutes)
    result = await client.taskoutbox.update_many(
        where={"status": "PROCESSING", "lockedAt": {"lt": cutoff}},
        data={"status": "PENDING", "lockedAt": None},
    )
    return result
