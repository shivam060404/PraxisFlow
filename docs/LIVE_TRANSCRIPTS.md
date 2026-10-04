# Live transcript boundary

Live transcription is an explicit, disabled-by-default boundary around the
Deepgram streaming API. This implementation does **not** implement vendor
OAuth, token exchange, recording persistence, or claim live external
connectivity.

## Contract

1. An authenticated tenant member calls
   `POST /api/v1/live-transcripts/sessions/{meeting_id}`.
2. The client opens
   `WS /api/v1/live-transcripts/ws/{meeting_id}?token={access_token}`.
3. The client sends binary, 16 kHz linear PCM audio frames. The server sends
   versioned JSON `live_transcript` events containing interim and final text.
4. `DELETE /api/v1/live-transcripts/sessions/{meeting_id}` closes a relay.

The token tenant and active database user are checked before the socket is
accepted, and the meeting must belong to that tenant. Audio is never accepted
from a different tenant or meeting.

## Safety behavior

Set `LIVE_TRANSCRIPT_ENABLED=true` only with `DEEPGRAM_API_KEY` configured.
Otherwise the socket returns an unavailable error and fails closed. The relay
rejects chunks over `LIVE_TRANSCRIPT_MAX_CHUNK_BYTES`, and rejects writes when
its bounded queue or byte budget is exhausted (WebSocket close code `4429`).
No audio is silently dropped. Redis fanout is intentionally not used for raw
audio; existing tenant-scoped websocket fanout remains suitable for persisted
application events.
