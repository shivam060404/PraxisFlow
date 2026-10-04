# LLM cost governance

All extraction, verification, repair, entity-resolution, and embedding calls
use the shared LiteLLM gateway. The gateway now provides:

- Tenant-scoped Redis token budgets with daily atomic counters.
- Fail-closed budget behavior in staging and production when Redis is
  unavailable, preventing uncontrolled provider spend.
- Tenant-configurable monthly USD limits through
  `monthlyLlmBudgetUsd`.
- Concurrency-safe monthly reservations using an atomic Redis Lua
  check-and-increment, settled to actual provider cost after each call.
- A durable `LLMUsageRecord` ledger containing provider, model, pipeline node,
  token counts, cost, and a unique request correlation identifier for
  idempotent retries.
- Monthly usage reporting through `GET /api/v1/admin/tenant/usage`.
- Existing OTel GenAI spans for latency, model, token, tenant, pipeline, and
  cost attributes.

The monthly spend check is deliberately conservative: it reserves estimated
cost before invoking a provider and atomically replaces that hold with actual
cost afterward. Abandoned holds expire with the month. The durable ledger is
the source of truth for billing and margin dashboards.

Production deployment requirements:

1. Run Redis with persistence, replication, and monitoring.
2. Generate and apply the Prisma migration for `LLMUsageRecord`,
   `monthlyLlmBudgetUsd`, and related indexes before enabling the gateway.
3. Export ledger data to ClickHouse/Grafana for long-term cost analytics.
4. Alert on budget denials, ledger write failures, fallback-provider rate, and
   tenant cost-to-MRR ratio.

## Analytics projection

The production compose profile includes ClickHouse and a provisioned Grafana
datasource. Successful usage writes are projected to the append-only
`praxisflow.llm_usage` table when `CLICKHOUSE_URL` is configured. The Prisma
ledger remains authoritative; operators must replay it to rebuild ClickHouse
after an outage. Billing/MRR is not inferred by this repository, so
cost-to-MRR alerts require an authoritative billing export before activation.
