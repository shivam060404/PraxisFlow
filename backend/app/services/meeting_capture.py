"""Vendor-neutral meeting capture lifecycle helpers."""

import hashlib
import hmac
import json
import secrets
import httpx
from datetime import datetime
from typing import Any

from app.db.prisma import get_prisma
from app.core.config import settings


def verify_capture_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Verify an HMAC-SHA256 callback from a configured capture session."""
    if not signature:
        return False
    supplied = signature.removeprefix("sha256=")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


def normalize_capture_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize common Recall.ai/Fireflies callback shapes."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = str(data.get("status") or data.get("event") or "").lower()
    status_map = {
        "bot_joining": "JOINING",
        "joining": "JOINING",
        "in_progress": "IN_PROGRESS",
        "recording_started": "IN_PROGRESS",
        "completed": "COMPLETED",
        "recording_ready": "COMPLETED",
        "failed": "FAILED",
        "cancelled": "CANCELLED",
    }
    return {
        "external_bot_id": str(
            data.get("bot_id") or data.get("botId") or data.get("meeting_bot_id") or ""
        ),
        "status": status_map.get(status, "FAILED" if status else "JOINING"),
        "recording_url": data.get("recording_url")
        or data.get("recordingUrl")
        or data.get("transcript_url"),
        "error_message": data.get("error") or data.get("error_message"),
        "raw_payload": json.loads(json.dumps(payload, default=str)),
    }


async def apply_capture_event(payload: dict[str, Any], provider: str, db: Any = None):
    client = db or await get_prisma()
    event = normalize_capture_event(payload)
    if not event["external_bot_id"]:
        raise ValueError("Capture callback is missing external bot ID")

    capture = await client.meetingcapture.find_first(
        where={
            "provider": provider,
            "externalBotId": event["external_bot_id"],
        }
    )
    if not capture:
        raise LookupError("Unknown meeting capture")

    update = {
        "status": event["status"],
        "lastEventAt": datetime.utcnow(),
        "rawPayload": event["raw_payload"],
        "errorMessage": event["error_message"],
    }
    if event["status"] == "IN_PROGRESS":
        update["startedAt"] = capture.startedAt or datetime.utcnow()
    if event["status"] == "COMPLETED":
        update["endedAt"] = datetime.utcnow()
        if event["recording_url"]:
            update["recordingUrl"] = event["recording_url"]

    updated = await client.meetingcapture.update(
        where={"id": capture.id},
        data=update,
    )

    if event["status"] == "IN_PROGRESS":
        await client.meeting.update(
            where={"id": capture.meetingId},
            data={"status": "CAPTURING"},
        )
    elif event["status"] == "COMPLETED" and event["recording_url"]:
        await client.meeting.update(
            where={"id": capture.meetingId},
            data={
                "status": "UPLOADED",
                "audioUrl": event["recording_url"],
                "recordingSource": provider,
            },
        )
        from app.workers.tasks import process_meeting

        process_meeting.delay(capture.meetingId)
    elif event["status"] in {"FAILED", "CANCELLED"}:
        await client.meeting.update(
            where={"id": capture.meetingId},
            data={"status": "ERROR"},
        )

    return updated


async def schedule_recall_capture(meeting: Any, db: Any = None) -> Any:
    """Schedule a Recall bot and persist its lifecycle atomically enough for retries."""
    if not settings.CAPTURE_SCHEDULER_ENABLED:
        raise RuntimeError("Capture scheduler is disabled")
    if not settings.RECALL_API_KEY:
        raise RuntimeError("RECALL_API_KEY is not configured")
    join_url = getattr(getattr(meeting, "calendarEvent", None), "joinUrl", None)
    if not join_url:
        raise ValueError("Meeting has no conferencing join URL")

    callback_secret = secrets.token_urlsafe(32)
    scheduled_for = meeting.scheduledAt
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.RECALL_API_URL.rstrip('/')}/bot/",
            headers={
                "Authorization": f"Token {settings.RECALL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "meeting_url": join_url,
                "bot_name": settings.RECALL_BOT_NAME,
                "join_at": scheduled_for.isoformat(),
            },
        )
        response.raise_for_status()
        result = response.json()

    external_bot_id = str(result.get("id") or result.get("bot_id") or "")
    if not external_bot_id:
        raise RuntimeError("Recall response did not include a bot ID")
    client = db or await get_prisma()
    pending = await client.meetingcapture.find_first(
        where={
            "meetingId": meeting.id,
            "provider": "recall",
            "status": "SCHEDULING",
        }
    )
    if not pending:
        raise RuntimeError("Capture scheduling lease was lost")
    return await client.meetingcapture.update(
        where={"id": pending.id},
        data={
            "externalBotId": external_bot_id,
            "webhookSecret": callback_secret,
            "scheduledFor": scheduled_for,
            "status": "SCHEDULED",
        },
    )
