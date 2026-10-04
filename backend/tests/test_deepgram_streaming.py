import json
import pytest

from app.core.config import settings
from app.services.deepgram_streaming import (
    BoundedAudioBuffer,
    BufferLimitExceeded,
    DeepgramStreamingRelay,
    LiveTranscriptEvent,
    StreamingConfigurationError,
)


@pytest.mark.asyncio
async def test_buffer_fails_closed_when_full():
    buffer = BoundedAudioBuffer(max_chunks=1, max_bytes=4)
    await buffer.put(b"1234")
    with pytest.raises(BufferLimitExceeded):
        await buffer.put(b"5")


def test_parse_deepgram_transcript_event():
    event = DeepgramStreamingRelay.parse_event(json.dumps({
        "is_final": True,
        "speech_final": True,
        "start": 1.5,
        "duration": 2,
        "channel": {"alternatives": [{"transcript": "hello", "confidence": 0.9}]},
    }))
    assert event == LiveTranscriptEvent(
        type="transcript", text="hello", is_final=True, speech_final=True,
        start=1.5, duration=2, confidence=0.9,
    )


@pytest.mark.asyncio
async def test_relay_requires_explicit_enablement(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_TRANSCRIPT_ENABLED", False)
    relay = DeepgramStreamingRelay(event_callback=lambda _: None, api_key="test")
    with pytest.raises(StreamingConfigurationError):
        await relay.start()
