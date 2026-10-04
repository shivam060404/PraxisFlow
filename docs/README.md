# PraxisFlow engineering documentation

This directory documents implemented application boundaries and deployment
prerequisites. A code path is not evidence of a certification, signed vendor
agreement, regional residency, or production provisioning.

## Phase 1–5 runbooks

| Area | Document | Scope |
|---|---|---|
| Ambient capture | [AMBIENT_INGESTION.md](./AMBIENT_INGESTION.md) | Bot registration, callbacks, signed audio ingress |
| Capture scheduling | [CAPTURE_SCHEDULING.md](./CAPTURE_SCHEDULING.md) | Consent-gated Recall scheduling and retries |
| Calendar | [CALENDAR_SYNC.md](./CALENDAR_SYNC.md) | Google/Microsoft OAuth, refresh, delta sync |
| Live transcripts | [LIVE_TRANSCRIPTS.md](./LIVE_TRANSCRIPTS.md) | Deepgram relay and versioned WebSocket contract |
| Task delivery | [INTEGRATION_DELIVERY.md](./INTEGRATION_DELIVERY.md) | Transactional outbox and provider delivery |
| Notifications | [NOTIFICATION_DELIVERY.md](./NOTIFICATION_DELIVERY.md) | Email, Slack, Teams, retries, signed actions |
| Trust and retention | [TRUST_AND_RETENTION.md](./TRUST_AND_RETENTION.md) | Consent, redaction, retention, KMS boundaries |
| LLM governance | [LLM_COST_GOVERNANCE.md](./LLM_COST_GOVERNANCE.md) | Budgets, usage ledger, ClickHouse projection |
| Security boundaries | [SECURITY_BOUNDARIES.md](./SECURITY_BOUNDARIES.md) | Tenant isolation and authorization invariants |
| Compliance inventory | [COMPLIANCE.md](./COMPLIANCE.md) | Evidence status; not a certification |

## Release checklist

Before enabling a production tenant:

1. Apply committed Prisma migrations with `prisma migrate deploy`.
2. Generate and smoke-test the Prisma Python client in the supported CI
   environment.
3. Configure Clerk, OAuth applications, meeting-bot credentials, Deepgram,
   Redis, Postgres, MinIO/S3, and the LiteLLM gateway.
4. Configure KMS grants and verify the tenant key region matches the declared
   data region.
5. Run service-backed tests and Playwright E2E from
   [ci.yml](../.github/workflows/ci.yml).
6. Verify vendor webhook signatures and rate limits against each production
   provider contract.
7. Attach legal, security, incident-response, backup/restore, and independent
   audit evidence before making compliance claims.

## Source of truth

- Prisma schema: `backend/prisma/schema.prisma`
- Migration history: `backend/prisma/migrations/`
- Runtime configuration: `.env.example`
- Production composition: `docker-compose.prod.yml`
- Release gates: `.github/workflows/ci.yml`
