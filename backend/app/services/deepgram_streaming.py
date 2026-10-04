"""Fail-closed, bounded Deepgram live transcription relay.

This module owns only the vendor boundary. It does not persist audio or
transcripts and does not claim OAuth or vendor connectivity. Callers provide
an event callback and decide how events are authorized and delivered.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class StreamingConfigurationError(RuntimeError):
    """Raised when live streaming cannot safely be started."""


class BufferLimitExceeded(RuntimeError):
    """Raised when accepting another audio chunk would exceed the bound."""


@dataclass(frozen=True)
class LiveTranscriptEvent:
    type: str
    text: str = ""
    is_final: bool = False
    speech_final: bool = False
    start: float = 0.0
    duration: float = 0.0
    confidence: float = 0.0

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "text": self.text,
            "is_final": self.is_final,
            "speech_final": self.speech_final,
            "start": self.start,
            "duration": self.duration,
            "confidence": self.confidence,
        }


class BoundedAudioBuffer:
    """FIFO buffer bounded by both chunks and bytes; never silently drops audio."""

    def __init__(self, max_chunks: int, max_bytes: int):
        if max_chunks < 1 or max_bytes < 1:
            raise ValueError("buffer bounds must be positive")
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max_chunks)
        self._max_bytes = max_bytes
        self._bytes = 0
        self._lock = asyncio.Lock()

    @property
    def buffered_bytes(self) -> int:
        return self._bytes

    async def put(self, chunk: bytes) -> None:
        if not chunk:
            return
        async with self._lock:
            if len(chunk) > self._max_bytes or self._bytes + len(chunk) > self._max_bytes:
                raise BufferLimitExceeded("live audio buffer limit exceeded")
            if self._queue.full():
                raise BufferLimitExceeded("live audio queue is full")
            self._bytes += len(chunk)
            self._queue.put_nowait(chunk)

    async def get(self) -> bytes:
        chunk = await self._queue.get()
        async with self._lock:
            self._bytes -= len(chunk)
        self._queue.task_done()
        return chunk


EventCallback = Callable[[LiveTranscriptEvent], Awaitable[None]]


class DeepgramStreamingRelay:
    """One authenticated audio stream to Deepgram's websocket endpoint."""

    def __init__(
        self,
        *,
        event_callback: EventCallback,
        api_key: Optional[str] = None,
        websocket_factory=None,
        max_queue_size: Optional[int] = None,
        max_buffer_bytes: Optional[int] = None,
    ):
        self.event_callback = event_callback
        self.api_key = api_key if api_key is not None else settings.DEEPGRAM_API_KEY
        self._websocket_factory = websocket_factory
        self._buffer = BoundedAudioBuffer(
            max_queue_size or settings.LIVE_TRANSCRIPT_QUEUE_SIZE,
            max_buffer_bytes or settings.LIVE_TRANSCRIPT_MAX_BUFFER_BYTES,
        )
        self._socket = None
        self._sender: Optional[asyncio.Task] = None
        self._receiver: Optional[asyncio.Task] = None
        self._closed = False

    @property
    def buffered_bytes(self) -> int:
        return self._buffer.buffered_bytes

    async def start(self) -> None:
        if not settings.LIVE_TRANSCRIPT_ENABLED:
            raise StreamingConfigurationError("live transcript relay is disabled")
        if not self.api_key:
            raise StreamingConfigurationError("DEEPGRAM_API_KEY is required")
        if self._socket is not None:
            raise RuntimeError("relay already started")
        factory = self._websocket_factory or self._default_websocket_factory
        self._socket = await factory(self._url(), {"Authorization": f"Token {self.api_key}"})
        self._closed = False
        self._sender = asyncio.create_task(self._send_loop())
        self._receiver = asyncio.create_task(self._receive_loop())

    def _url(self) -> str:
        from urllib.parse import urlencode

        params = urlencode({
            "model": settings.DEEPGRAM_MODEL,
            "language": settings.DEEPGRAM_LANGUAGE,
            "diarize": str(settings.DEEPGRAM_DIARIZE).lower(),
            "punctuate": str(settings.DEEPGRAM_PUNCTUATE).lower(),
            "interim_results": "true",
            "utterances": str(settings.DEEPGRAM_UTTERANCES).lower(),
            "encoding": "linear16",
            "sample_rate": "16000",
        })
        return f"wss://api.deepgram.com/v1/listen?{params}"

    async def _default_websocket_factory(self, url: str, headers: dict):
        import websockets

        kwargs = {"open_timeout": settings.LIVE_TRANSCRIPT_IDLE_TIMEOUT_SECONDS}
        # websockets renamed this argument in v14; support the pinned
        # production version and newer environments without weakening auth.
        try:
            return await websockets.connect(url, additional_headers=headers, **kwargs)
        except TypeError as exc:
            if "additional_headers" not in str(exc):
                raise
            return await websockets.connect(url, extra_headers=headers, **kwargs)

    async def send_audio(self, chunk: bytes) -> None:
        if self._closed or self._socket is None:
            raise RuntimeError("relay is not running")
        if len(chunk) > settings.LIVE_TRANSCRIPT_MAX_CHUNK_BYTES:
            raise BufferLimitExceeded("audio chunk exceeds configured limit")
        await self._buffer.put(chunk)

    async def _send_loop(self) -> None:
        while not self._closed:
            await self._socket.send(await self._buffer.get())

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._socket:
                if isinstance(raw, bytes):
                    continue
                event = self.parse_event(raw)
                if event is not None:
                    await self.event_callback(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Deepgram streaming connection failed")
            await self.event_callback(LiveTranscriptEvent(type="error"))

    @staticmethod
    def parse_event(raw: str | bytes) -> Optional[LiveTranscriptEvent]:
        try:
            payload = json.loads(raw)
            if payload.get("type") == "Metadata":
                return LiveTranscriptEvent(type="metadata")
            channel = (payload.get("channel") or {})
            alternatives = channel.get("alternatives") or []
            alternative = alternatives[0] if alternatives else {}
            return LiveTranscriptEvent(
                type="transcript",
                text=alternative.get("transcript", ""),
                is_final=bool(payload.get("is_final")),
                speech_final=bool(payload.get("speech_final")),
                start=float(payload.get("start", 0)),
                duration=float(payload.get("duration", 0)),
                confidence=float(alternative.get("confidence", 0)),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return LiveTranscriptEvent(type="error")

    async def stop(self) -> None:
        self._closed = True
        for task in (self._sender, self._receiver):
            if task:
                task.cancel()
        if self._socket is not None:
            try:
                await self._socket.close()
            finally:
                self._socket = None
        self._sender = self._receiver = None
