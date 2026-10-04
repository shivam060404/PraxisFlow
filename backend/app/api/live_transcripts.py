"""Authenticated tenant-scoped contract for live transcript audio/events."""

from __future__ import annotations

import logging
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.api.websocket import get_tenant_user_from_token
from app.core.config import settings
from app.db.prisma import get_prisma
from app.security.base import Subject, get_current_subject
from app.services.deepgram_streaming import (
    BufferLimitExceeded,
    DeepgramStreamingRelay,
    LiveTranscriptEvent,
    StreamingConfigurationError,
)

router = APIRouter(prefix="/live-transcripts", tags=["Live transcripts"])
logger = logging.getLogger(__name__)
_relays: Dict[str, DeepgramStreamingRelay] = {}
_live_text: Dict[str, list[str]] = {}


class LiveTranscriptSession(BaseModel):
    meeting_id: str
    websocket_path: str
    status: str


async def _tenant_meeting(meeting_id: str, tenant_id: str):
    db = await get_prisma()
    meeting = await db.meeting.find_first(where={"id": meeting_id, "tenantId": tenant_id})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.post("/sessions/{meeting_id}", response_model=LiveTranscriptSession, status_code=201)
async def start_live_transcript(meeting_id: str, subject: Subject = Depends(get_current_subject)):
    """Reserve a live session; audio is sent only over the authenticated WS."""
    if not settings.LIVE_TRANSCRIPT_ENABLED:
        raise HTTPException(status_code=503, detail="Live transcript relay is disabled")
    await _tenant_meeting(meeting_id, subject.tenant_id)
    if meeting_id in _relays:
        raise HTTPException(status_code=409, detail="Live transcript session already exists")
    # The actual vendor socket starts at WS handshake, preventing orphaned
    # vendor sessions when a client never connects.
    return LiveTranscriptSession(
        meeting_id=meeting_id,
        websocket_path=f"{settings.API_V1_PREFIX}/live-transcripts/ws/{meeting_id}",
        status="reserved",
    )


@router.delete("/sessions/{meeting_id}", status_code=204)
async def stop_live_transcript(meeting_id: str, subject: Subject = Depends(get_current_subject)):
    await _tenant_meeting(meeting_id, subject.tenant_id)
    relay = _relays.pop(meeting_id, None)
    if relay:
        await relay.stop()


@router.websocket("/ws/{meeting_id}")
async def live_transcript_websocket(
    websocket: WebSocket,
    meeting_id: str,
    token: str = Query(...),
):
    """Binary audio in, versioned JSON transcript events out.

    The token carries tenant identity, while the database verifies membership
    and meeting ownership before accepting either audio or vendor traffic.
    """
    try:
        tenant_id, user_id = await get_tenant_user_from_token(token)
        db = await get_prisma()
        user = await db.user.find_first(where={"id": user_id, "tenantId": tenant_id})
        meeting = await db.meeting.find_first(where={"id": meeting_id, "tenantId": tenant_id})
        if not user or user.status != "ACTIVE" or not meeting:
            await websocket.close(code=4403)
            return
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    async def emit(event: LiveTranscriptEvent):
        if event.is_final and event.text.strip():
            # Persist only redacted final segments; interim vendor output never
            # becomes durable data.
            try:
                from app.services.pii_redaction import redact_text
                redaction = redact_text(event.text)
                redacted = redaction["text"]
                _live_text.setdefault(meeting_id, []).append(redacted.strip())
                db = await get_prisma()
                await db.transcript.upsert(
                    where={"meetingId": meeting_id},
                    data={
                        "create": {
                            "meetingId": meeting_id,
                            "fullText": redacted,
                            "wordCount": len(redacted.split()),
                            "redactionApplied": redacted != event.text,
                        },
                        "update": {
                            "fullText": " ".join(_live_text[meeting_id]),
                            "wordCount": len(" ".join(_live_text[meeting_id]).split()),
                            "redactionApplied": redacted != event.text,
                        },
                    },
                )
            except Exception:
                logger.exception("Failed to persist redacted live transcript segment")
                raise
        await websocket.send_json({
            "version": 1,
            "type": "live_transcript",
            "meeting_id": meeting_id,
            "tenant_id": tenant_id,
            "payload": event.as_dict(),
        })

    relay = DeepgramStreamingRelay(event_callback=emit)
    try:
        await relay.start()
        _relays[meeting_id] = relay
        await websocket.send_json({
            "version": 1,
            "type": "live_transcript.ready",
            "meeting_id": meeting_id,
            "tenant_id": tenant_id,
        })
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            chunk = message.get("bytes")
            if chunk is None:
                await websocket.send_json({"version": 1, "type": "error", "code": "binary_audio_required"})
                continue
            try:
                await relay.send_audio(chunk)
            except BufferLimitExceeded:
                await websocket.send_json({"version": 1, "type": "error", "code": "backpressure"})
                await websocket.close(code=4429)
                break
    except StreamingConfigurationError as exc:
        await websocket.send_json({"version": 1, "type": "error", "code": "relay_unavailable", "detail": str(exc)})
        await websocket.close(code=1013)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("live transcript websocket failed")
    finally:
        if _relays.get(meeting_id) is relay:
            _relays.pop(meeting_id, None)
        _live_text.pop(meeting_id, None)
        await relay.stop()
