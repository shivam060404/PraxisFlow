"""Provider-neutral calendar event normalization and upsert."""

from datetime import datetime, timezone
from typing import Any

from app.db.prisma import get_prisma


def _parse_datetime(value: Any) -> datetime:
    if not value:
        raise ValueError("Calendar event is missing start time")
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_calendar_event(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Google Calendar and Microsoft Graph event shapes."""
    if provider == "google":
        event_id = payload.get("id")
        title = payload.get("summary") or "Untitled meeting"
        description = payload.get("description")
        start = payload.get("start")
        end = payload.get("end")
        organizer = (payload.get("organizer") or {}).get("email")
        join_url = payload.get("hangoutLink")
        status = payload.get("status", "confirmed")
    elif provider == "microsoft":
        event_id = payload.get("id")
        title = payload.get("subject") or "Untitled meeting"
        description = payload.get("bodyPreview")
        start = payload.get("start")
        end = payload.get("end")
        organizer = ((payload.get("organizer") or {}).get("emailAddress") or {}).get("address")
        join_url = payload.get("onlineMeeting", {}).get("joinUrl")
        status = payload.get("showAs", "confirmed")
    else:
        raise ValueError(f"Unsupported calendar provider: {provider}")

    if not event_id:
        raise ValueError("Calendar event is missing provider event ID")
    scheduled_at = _parse_datetime(start)
    duration = None
    if end:
        duration = max(0, int((_parse_datetime(end) - scheduled_at).total_seconds() / 60))
    return {
        "externalEventId": str(event_id),
        "title": title,
        "description": description,
        "scheduledAt": scheduled_at,
        "durationMinutes": duration,
        "organizerEmail": organizer,
        "joinUrl": join_url,
        "status": status,
        "rawPayload": payload,
    }


async def upsert_calendar_event(
    *,
    connection: Any,
    payload: dict[str, Any],
    db: Any = None,
) -> Any:
    client = db or await get_prisma()
    normalized = normalize_calendar_event(str(connection.provider), payload)
    existing = await client.calendarevent.find_unique(
        where={
            "connectionId_externalEventId": {
                "connectionId": connection.id,
                "externalEventId": normalized["externalEventId"],
            }
        }
    )
    if existing:
        return await client.calendarevent.update(
            where={"id": existing.id},
            data={**normalized, "lastSeenAt": datetime.utcnow()},
        )

    meeting = await client.meeting.create(
        data={
            "tenantId": connection.tenantId,
            "title": normalized["title"],
            "description": normalized["description"],
            "scheduledAt": normalized["scheduledAt"],
            "durationMinutes": normalized["durationMinutes"],
            "recordingSource": str(connection.provider),
            "calendarEventId": normalized["externalEventId"],
            "status": "SCHEDULED",
        }
    )
    return await client.calendarevent.create(
        data={
            **normalized,
            "tenantId": connection.tenantId,
            "connectionId": connection.id,
            "meetingId": meeting.id,
        }
    )
