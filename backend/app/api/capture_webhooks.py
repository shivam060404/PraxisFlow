"""Authenticated callbacks from meeting-capture vendors."""

from fastapi import APIRouter, Header, HTTPException, Request

from app.db.prisma import get_prisma
from app.services.meeting_capture import apply_capture_event, verify_capture_signature
from app.api.live_transcripts import _relays
from app.services.deepgram_streaming import BufferLimitExceeded

router = APIRouter(prefix="/capture-webhooks", tags=["Meeting Capture"])
SUPPORTED_PROVIDERS = {"recall", "fireflies"}


@router.post("/{provider}")
async def receive_capture_webhook(
    provider: str,
    request: Request,
    x_capture_id: str | None = Header(None),
    x_signature: str | None = Header(None),
):
    """Verify and apply a provider callback for a pre-registered capture."""
    provider = provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported capture provider")
    if not x_capture_id:
        raise HTTPException(status_code=400, detail="Missing X-Capture-ID")

    body = await request.body()
    db = await get_prisma()
    capture = await db.meetingcapture.find_first(
        where={"provider": provider, "externalBotId": x_capture_id}
    )
    if not capture or not verify_capture_signature(body, x_signature, capture.webhookSecret):
        raise HTTPException(status_code=401, detail="Invalid capture callback")

    try:
        payload = await request.json()
        updated = await apply_capture_event(payload, provider, db=db)
        return {"status": "accepted", "capture_id": updated.id}
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{provider}/audio")
async def receive_capture_audio(
    provider: str,
    request: Request,
    x_capture_id: str | None = Header(None),
    x_signature: str | None = Header(None),
):
    """Accept a signed PCM chunk from the capture vendor and relay it to Deepgram.

    The browser may subscribe to the authenticated live-transcript websocket;
    the meeting bot remains the only producer of audio.
    """
    provider = provider.lower()
    if provider not in SUPPORTED_PROVIDERS or not x_capture_id:
        raise HTTPException(status_code=400, detail="Invalid capture audio request")
    body = await request.body()
    db = await get_prisma()
    capture = await db.meetingcapture.find_first(
        where={"provider": provider, "externalBotId": x_capture_id}
    )
    if not capture or not verify_capture_signature(body, x_signature, capture.webhookSecret):
        raise HTTPException(status_code=401, detail="Invalid capture audio signature")
    relay = _relays.get(capture.meetingId)
    if relay is None:
        raise HTTPException(status_code=409, detail="Live transcript session is not connected")
    try:
        await relay.send_audio(body)
    except BufferLimitExceeded as exc:
        raise HTTPException(status_code=429, detail="Audio relay backpressure") from exc
    return {"status": "accepted", "bytes": len(body)}
