"""Durable inbound webhook persistence and processing helpers."""

import hashlib
import json
from datetime import datetime
from typing import Any

from app.db.prisma import get_prisma


def delivery_key(provider: str, body: bytes, request_id: str | None = None) -> str:
    """Prefer provider delivery IDs, with a stable payload hash fallback."""
    if request_id:
        return f"{provider}:{request_id}"
    return f"{provider}:sha256:{hashlib.sha256(body).hexdigest()}"


async def persist_webhook_event(
    *,
    integration: Any,
    provider: str,
    key: str,
    normalized: Any,
    payload: dict[str, Any],
    db: Any = None,
) -> tuple[Any, bool]:
    """Persist one verified event; return (event, created)."""
    client = db or await get_prisma()
    existing = await client.integrationwebhookevent.find_unique(
        where={"integrationId_deliveryKey": {"integrationId": integration.id, "deliveryKey": key}}
    )
    if existing:
        return existing, False

    event = await client.integrationwebhookevent.create(
        data={
            "tenantId": integration.tenantId,
            "integrationId": integration.id,
            "provider": provider,
            "deliveryKey": key,
            "externalId": normalized.external_id or None,
            "externalStatus": normalized.status or None,
            "externalUrl": normalized.external_url or None,
            "changedAt": normalized.changed_at,
            "payload": json.loads(json.dumps(payload, default=str)),
        }
    )
    return event, True


async def claim_webhook_event(event_id: str, db: Any = None) -> bool:
    client = db or await get_prisma()
    claimed = await client.integrationwebhookevent.update_many(
        where={"id": event_id, "status": "PENDING"},
        data={
            "status": "PROCESSING",
            "lockedAt": datetime.utcnow(),
            "attempts": {"increment": 1},
        },
    )
    return bool(claimed)


async def requeue_stale_webhook_events(db: Any = None, lease_minutes: int = 15) -> int:
    client = db or await get_prisma()
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(minutes=lease_minutes)
    return await client.integrationwebhookevent.update_many(
        where={"status": "PROCESSING", "lockedAt": {"lt": cutoff}},
        data={"status": "PENDING", "lockedAt": None},
    )
