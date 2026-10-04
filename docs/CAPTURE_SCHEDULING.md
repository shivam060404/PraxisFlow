# Automatic capture scheduling

Celery Beat runs `schedule_upcoming_captures` every minute. It finds
tenant-owned meetings beginning within the next 15 minutes and leases each
meeting with a unique `MeetingCapture` row in `SCHEDULING` state before calling
Recall.ai.

The scheduler is disabled by default. Enable it only after configuring:

```env
CAPTURE_SCHEDULER_ENABLED=true
RECALL_API_KEY=...
RECALL_API_URL=https://us-west-2.recall.ai/api/v1
```

The lease prevents two workers from scheduling the same meeting. Successful
scheduling replaces the temporary lease ID with the provider bot ID and
persists a per-capture callback secret. Failed attempts are retained as
`FAILED` with an error and attempt timestamp; the next scheduler pass may
retry them. A meeting without a conferencing join URL fails explicitly
instead of creating a bot that cannot join.

The current Recall adapter sends the meeting join URL, bot name, and scheduled
join time. Fireflies can use the same lifecycle model once its API credentials
and scheduling contract are configured.
