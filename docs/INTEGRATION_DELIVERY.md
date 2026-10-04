# Reliable integration delivery

PraxisFlow treats PostgreSQL as the source of truth for extracted tasks and
uses a transactional outbox for external task delivery.

1. A task mutation and its `TaskOutbox` event are written together.
2. Celery Beat invokes the relay every 15 seconds.
3. The relay claims events with a compare-and-set update, so multiple workers
   can run safely.
4. Provider calls are retried with exponential backoff. A worker crash leaves a
   lease that is recovered after 15 minutes.
5. A successful delivery updates the local task and marks the outbox event
   `SYNCED`. The idempotency key prevents duplicate enqueueing.

Provider adapters must therefore tolerate at-least-once delivery. Webhooks
are first stored in `IntegrationWebhookEvent` after signature verification.
They are then processed asynchronously, deduplicated by provider delivery ID
or a deterministic body hash, and append a `TaskAuditLog` entry for every
local transition. Failed events are retried and eventually moved to
`DEAD_LETTER`; tenant administrators can inspect and replay them through the
admin webhook-event endpoints.

Run a worker with Celery Beat enabled in production, for example:

```bash
celery -A app.workers.celery_app worker --beat -Q integrations
```
