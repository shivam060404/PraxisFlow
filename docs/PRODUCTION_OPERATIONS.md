# Production operations and recovery

## Deployment scope

`docker-compose.prod.yml` is a single-host reference deployment. It does not
provide multi-host scheduling, database failover, a replicated Kafka cluster,
or automatic horizontal scaling. Use managed PostgreSQL, Redis, object storage,
and a multi-broker event service for a production availability objective.
Do not treat Compose `deploy.resources` as an autoscaling policy.
Langfuse must use its own database and credentials; do not point it at the
PraxisFlow app database or a superuser connection.

The API and Celery worker can run as multiple processes/containers when they
share PostgreSQL checkpoints, Redis, the restricted application DB role, and
the same task broker. Keep the total Prisma and checkpoint connection pools
within the database connection budget. Celery worker concurrency defaults to
four in the reference stack; measure ASR and LLM provider limits before raising
it.
Redis is shared by Celery, budgets, caching, and WebSocket fanout in this
reference stack. It uses AOF persistence and `noeviction` so pressure surfaces
as write failures instead of silently evicting queue or budget keys. Monitor
memory and queue depth; use separate managed Redis deployments when scaling.

## Backup and restore

The Compose backup service runs `pg_dump -Fc` daily at 02:00 UTC, uploads the
dump to the configured off-host S3-compatible bucket, and removes local and
remote dumps older than 30 days. A successful dump is not proof of
recoverability. No restore drill has been run from this repository, so no
RPO/RTO is claimed. Use a separate account/bucket and enable provider-side
encryption, versioning, and access logging.

Before production traffic, run this drill in an isolated staging database:

1. Confirm a dated object exists in the backup bucket and record its checksum.
2. Restore it into a newly created empty database with `pg_restore`.
3. Apply the current schema and RLS setup, then connect with the restricted
   application role. Confirm the read-only `praxisflow_backup` role can dump
   all tenant rows while remaining unable to modify them.
4. Verify tenant boundaries, meeting/transcript/task relations, pending human
   reviews, AI audit records, and checkpoint tables.
5. Run one upload-to-extraction workflow and one human-review resume against
   the restored environment.
6. Record elapsed restore and validation time, missing data, and the latest
   usable backup timestamp. Repeat after changes to schema, backup tooling, or
   storage credentials.

The PostgreSQL dump does not include MinIO meeting audio. Configure object
versioning or a separate protected backup policy for audio and other required
objects before relying on meeting reprocessing after a storage incident.

## Failure and scaling behavior

| Failure | Expected behavior | Required operational check |
|---|---|---|
| Postgres/checkpointer unavailable at production startup | API and workers fail startup; no in-memory HITL fallback | Restore connectivity and confirm both worker and API initialized the Postgres saver |
| Redis unavailable | Production token-budget initialization fails closed; queued jobs and WebSocket fanout are unavailable | Restore Redis, inspect queue backlog, and verify budgets before resuming traffic |
| LLM gateway/provider unavailable | Provider fallback and bounded retries run; exhausted extraction fails the meeting and records a flag | Inspect gateway health, provider status, failed meeting flags, token budget, and retry queue |
| PII redaction unavailable | Transcript persistence stops in production | Restore Presidio/runtime resources; verify failed ingestion did not write raw transcript data |
| Worker process restart | Celery redelivers according to broker policy; checkpoint state is in Postgres and task persistence is transactional/idempotent | Confirm in-flight job state and reconcile tasks against meeting status |
| HITL resume interrupted after decision claim | Review remains `IN_REVIEW`; the same reviewer can retry against the stored LangGraph checkpoint | Inspect checkpoint state before resetting a stuck review to `PENDING` |
| Off-host object storage unavailable during backup | Backup job fails; the previous backup remains the latest recoverable point | Alert on backup service logs and age of the newest uploaded object |

The single-node Kafka configuration is notification transport only and is not
HA. Qdrant and Neo4j are also single instances in this Compose file. Use
managed/clustered services or accept their documented recovery windows.

## TLS and network entry

Only Nginx publishes host ports. Install valid certificates as
`infrastructure/nginx/ssl/fullchain.pem` and `privkey.pem` before starting the
stack; Nginx intentionally refuses to start without them. Port 80 redirects to
HTTPS. DNS for `app.praxisflow.com` and `api.praxisflow.com` must resolve to
this host, or update the Nginx `server_name` values and frontend/CORS settings
together. Do not expose the internal service ports directly to the internet.
The certificate must cover both hostnames.
The MinIO init container creates service users once. Rotate an existing user's
secret in MinIO before updating the matching environment value; changing the
environment alone does not change the already-created MinIO credential.

## Release gates

- Apply Prisma schema changes before applying/updating RLS policies; rerun the
  RLS setup after adding tenant-bearing tables. Grant new tables to the
  read-only backup role so full dumps remain complete.
- Run backend and frontend CI. Security scans currently report findings without
  blocking merges; make those jobs gating before claiming a security release
  gate. Run the live AI evaluation workflow with production-like credentials.
- Meet the configured extraction precision, recall, and quote-grounding gates
  on the committed gold set and review individual regressions.
- Complete a staging backup restore and a tenant-isolation exercise.
- Record versions, schema changes, prompts, model routes, and evaluation
  results for each release.
