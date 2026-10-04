"""Durable meeting notification delivery."""

import hashlib
import html
import base64
import hmac
import json
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

import httpx

from app.core.config import settings
from app.db.prisma import get_prisma


def _key(meeting_id: str, channel: str, recipient: str) -> str:
    return hashlib.sha256(f"{meeting_id}:{channel}:{recipient}".encode()).hexdigest()


async def enqueue_meeting_notifications(meeting: Any, users: list[Any], db: Any = None) -> int:
    client = db or await get_prisma()
    created = 0
    for user in users:
        key = _key(str(meeting.id), "email", user.email)
        result = await client.notificationdelivery.upsert(
            where={"idempotencyKey": key},
            data={
                "create": {
                    "tenantId": meeting.tenantId,
                    "meetingId": meeting.id,
                    "channel": "email",
                    "recipient": user.email,
                    "idempotencyKey": key,
                },
                "update": {},
            },
        )
        if result.status == "PENDING":
            created += 1
    return created


def _summary(meeting: Any) -> tuple[str, str]:
    title = html.escape(meeting.title)
    text = (
        f"PraxisFlow processed meeting: {meeting.title}\n"
        f"Meeting ID: {meeting.id}\n"
        "Open PraxisFlow to review the transcript and extracted action items."
    )
    body = (
        f"<h2>{title}</h2>"
        "<p>Your meeting has been processed. Review the transcript and "
        "AI-extracted action items in PraxisFlow.</p>"
    )
    return text, body


def _action_secret() -> str:
    return settings.NOTIFICATION_ACTION_SECRET or settings.JWT_SECRET


def create_action_token(task_id: str, tenant_id: str, action: str, *, now: int | None = None) -> str:
    """Create a short, signed, opaque action token for a notification button."""
    issued = now or int(datetime.now(timezone.utc).timestamp())
    payload = {"task_id": task_id, "tenant_id": tenant_id, "action": action,
               "exp": issued + settings.NOTIFICATION_ACTION_TTL_SECONDS}
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    signature = hmac.new(_action_secret().encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def verify_action_token(token: str, *, now: int | None = None) -> dict[str, Any]:
    """Validate a signed action token without trusting any client-supplied fields."""
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(_action_secret().encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if int(payload["exp"]) < (now or int(datetime.now(timezone.utc).timestamp())):
            raise ValueError("expired action")
        if payload["action"] not in {"verify", "reject"}:
            raise ValueError("unsupported action")
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid action token") from exc


def _action_url(task: Any, action: str) -> str:
    token = create_action_token(str(task.id), str(task.tenantId), action)
    return f"{settings.NOTIFICATION_ACTION_BASE_URL}/{action}?token={token}"


def build_slack_payload(meeting: Any, tasks: list[Any] | None = None) -> dict[str, Any]:
    """Build an Incoming Webhook Block Kit message, including signed HITL links."""
    text, _ = _summary(meeting)
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "PraxisFlow meeting ready"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{html.escape(meeting.title)}*\n{text}"}},
    ]
    review_tasks = [task for task in (tasks if tasks is not None else getattr(meeting, "tasks", []))
                    if getattr(task, "status", "PENDING_REVIEW") in {"EXTRACTED", "PENDING_REVIEW"}]
    for task in review_tasks:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Action:* {html.escape(task.title)}"},
                       "accessory": {"type": "overflow", "action_id": f"task-{task.id}",
                                     "options": [{"text": {"type": "plain_text", "text": "Review in PraxisFlow"}, "value": str(task.id)}]}})
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Verify"}, "style": "primary",
             "url": _action_url(task, "verify"), "action_id": f"verify-{task.id}"},
            {"type": "button", "text": {"type": "plain_text", "text": "Reject"}, "style": "danger",
             "url": _action_url(task, "reject"), "action_id": f"reject-{task.id}"},
        ]})
    return {"text": text, "blocks": blocks}


def build_teams_payload(meeting: Any, tasks: list[Any] | None = None) -> dict[str, Any]:
    """Build a Teams Incoming Webhook Adaptive Card with signed HITL links."""
    text, _ = _summary(meeting)
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": meeting.title},
        {"type": "TextBlock", "text": text, "wrap": True},
    ]
    review_tasks = [task for task in (tasks if tasks is not None else getattr(meeting, "tasks", []))
                    if getattr(task, "status", "PENDING_REVIEW") in {"EXTRACTED", "PENDING_REVIEW"}]
    for task in review_tasks:
        body.extend([
            {"type": "TextBlock", "text": f"Action: {task.title}", "wrap": True, "weight": "Bolder"},
            {"type": "ActionSet", "actions": [
                {"type": "Action.OpenUrl", "title": "Verify", "url": _action_url(task, "verify")},
                {"type": "Action.OpenUrl", "title": "Reject", "url": _action_url(task, "reject")},
            ]},
        ])
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
        "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                    "version": "1.4", "body": body}}]}


# Descriptive public names for provider adapters.
build_slack_block_kit_payload = build_slack_payload
build_teams_adaptive_card_payload = build_teams_payload


async def deliver_notification(delivery: Any, meeting: Any) -> None:
    text, body = _summary(meeting)
    if delivery.channel == "email":
        if not settings.NOTIFICATION_SMTP_HOST:
            raise RuntimeError("NOTIFICATION_SMTP_HOST is not configured")
        message = EmailMessage()
        message["Subject"] = f"PraxisFlow: {meeting.title}"
        message["From"] = settings.NOTIFICATION_FROM_EMAIL
        message["To"] = delivery.recipient
        message.set_content(text)
        message.add_alternative(body, subtype="html")
        with smtplib.SMTP(settings.NOTIFICATION_SMTP_HOST, settings.NOTIFICATION_SMTP_PORT) as smtp:
            if settings.NOTIFICATION_SMTP_TLS:
                smtp.starttls()
            if settings.NOTIFICATION_SMTP_USERNAME:
                smtp.login(settings.NOTIFICATION_SMTP_USERNAME, settings.NOTIFICATION_SMTP_PASSWORD or "")
            smtp.send_message(message)
        return

    url = delivery.recipient
    payload = (
        build_slack_payload(meeting)
        if delivery.channel == "slack"
        else build_teams_payload(meeting)
    )
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


async def claim_delivery(delivery_id: str, db: Any = None) -> bool:
    client = db or await get_prisma()
    return bool(await client.notificationdelivery.update_many(
        where={"id": delivery_id, "status": "PENDING", "availableAt": {"lte": datetime.utcnow()}},
        data={"status": "PROCESSING", "attempts": {"increment": 1}, "lastAttemptAt": datetime.utcnow()},
    ))


async def requeue_stale_notifications(db: Any = None) -> int:
    client = db or await get_prisma()
    cutoff = datetime.utcnow() - timedelta(minutes=15)
    return await client.notificationdelivery.update_many(
        where={"status": "PROCESSING", "lastAttemptAt": {"lt": cutoff}},
        data={"status": "PENDING"},
    )
