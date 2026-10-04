# Notification delivery

When extraction completes, PraxisFlow creates one durable email delivery per
active tenant user. The idempotency key is derived from meeting, channel, and
recipient, so retries and repeated extraction callbacks do not duplicate
notifications.

Celery Beat runs the delivery worker every 15 seconds. Each delivery is
claimed with a compare-and-set update, retried with exponential backoff, and
moved to `DEAD_LETTER` after five failed attempts. Stale worker leases are
returned to `PENDING` every five minutes.

Email uses SMTP and must be explicitly configured:

```env
NOTIFICATION_SMTP_HOST=smtp.example.com
NOTIFICATION_SMTP_PORT=587
NOTIFICATION_SMTP_TLS=true
NOTIFICATION_SMTP_USERNAME=...
NOTIFICATION_SMTP_PASSWORD=...
NOTIFICATION_FROM_EMAIL=notifications@example.com
```

Slack and Teams deliveries use a configured incoming webhook URL as the
recipient. Slack uses a Block Kit payload and Teams uses an Adaptive Card
payload. Both can include Verify and Reject links for reviewable tasks.

Action links are HMAC signed and expire after `NOTIFICATION_ACTION_TTL_SECONDS`.
They do not require an OAuth installation: webhook URLs and the action signing
secret are configuration-driven:

```env
NOTIFICATION_ACTION_SECRET=replace-with-a-dedicated-random-secret
NOTIFICATION_ACTION_BASE_URL=https://app.example.com/api/v1/notifications/actions
NOTIFICATION_ACTION_TTL_SECONDS=604800
```

`GET /api/v1/notifications/actions/{verify|reject}?token=...` atomically
transitions a task and records the audit event. Replaying a link is safe and
returns `already_applied`; stale or mismatched links are rejected.
