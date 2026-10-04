# Ambient meeting ingestion contract

PraxisFlow keeps meeting capture vendor-neutral. A meeting is registered with
an external bot identifier and a per-capture callback secret after the vendor
has accepted the scheduled bot:

```http
POST /api/v1/meetings/{meeting_id}/capture
```

The vendor callback is sent to:

```http
POST /api/v1/capture-webhooks/{provider}
X-Capture-ID: <external bot id>
X-Signature: sha256=<HMAC-SHA256 body signature>
```

Supported providers are `recall` and `fireflies`. The callback handler:

1. Resolves the capture by provider and external bot ID.
2. Verifies the body with the capture-specific secret.
3. Normalizes common bot lifecycle payloads.
4. Moves the capture through `JOINING`, `IN_PROGRESS`, `COMPLETED`, or
   `FAILED`.
5. Stores the raw callback for support and audit investigations.
6. When a recording becomes available, attaches it to the tenant-owned
   meeting and queues the existing ASR pipeline.

Recall scheduling and OAuth/calendar synchronization are implemented as
adapters around this contract. Fireflies lifecycle normalization is supported,
but each vendor still requires configured credentials and a verified production
webhook contract. The core meeting and processing pipeline does not need to
know whether Recall.ai, Fireflies, Zoom, Meet, or Teams produced the recording.

For live meetings, a signed PCM body may be sent to
`POST /api/v1/capture-webhooks/{provider}/audio` using the same capture ID and
signature. The meeting must have an active authenticated live-transcript
session; otherwise the endpoint rejects the audio rather than buffering it
indefinitely.
