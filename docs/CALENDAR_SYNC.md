# Calendar synchronization

Calendar connections are tenant-scoped and store references to OAuth secrets,
not raw access tokens. Secret references should resolve through Vault or AWS
Secrets Manager in the connector worker.

Supported providers:

- Google Calendar
- Microsoft Graph Calendar

The connector normalizes provider events through
`app.services.calendar_sync.normalize_calendar_event` and upserts them using
`(connection_id, external_event_id)`. A new event creates a scheduled
PraxisFlow meeting. Repeated provider deliveries update the existing calendar
event instead of creating duplicate meetings.

The current API is intentionally provider-neutral:

```http
POST /api/v1/calendar/connections
POST /api/v1/calendar/connections/{connection_id}/events
```

OAuth is exposed through signed, ten-minute state values:

```http
GET /api/v1/calendar/oauth/{provider}/authorize?external_account=user@example.com
GET /api/v1/calendar/oauth/callback?code=...&state=...
POST /api/v1/calendar/connections/{connection_id}/sync
```

The callback stores access and refresh tokens as encrypted secret references
(`encrypted://...`); raw bearer tokens are rejected by the connection API and
are never returned in responses. Deployments may replace the fallback
`EncryptedSecretStore` with Vault/AWS Secrets Manager using the same protocol.
Expired or rejected credentials move the connection to `REAUTH_REQUIRED`.

`sync` returns an opaque provider cursor and deleted external IDs. Google
`nextSyncToken` and Graph `@odata.deltaLink` values are persisted without
interpretation; a provider HTTP 410 resets the cursor for a full resync.
Meeting capture scheduling consumes new `Meeting` records whose status is
`SCHEDULED`.
