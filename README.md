# PraxisFlow — Enterprise AI Meeting Intelligence & Action Command Center

An enterprise-grade agentic AI platform that transforms passive meeting recordings into structured, trackable, and accountable execution workflows. Built for regulated industries with full AI governance, compliance, and observability.

[![GitHub](https://img.shields.io/badge/GitHub-PraxisFlow-181717?logo=github)](https://github.com/shivam060404/PraxisFlow)
[![CI/CD](https://img.shields.io/github/actions/workflow/status/shivam060404/PraxisFlow/ci.yml?branch=main)](https://github.com/shivam060404/PraxisFlow/actions)

> **Status:** production-shaped Phase 1–5 implementation. Upload and ambient capture, OAuth calendar sync, provider reconciliation, live Deepgram relay, durable outbox delivery, tenant policy controls, LLM budget accounting, ClickHouse projection, migrations, and CI gates are implemented. Cloud credentials, regional deployment, provider contracts, and independent compliance audits remain deployment prerequisites.

---


---

## Architecture (as built)

```
┌──────────────────────────────────────────────────────────────────────┐
│  FRONTEND — Next.js 15 · TypeScript · TanStack Query · Zustand       │
│  Kanban board · meetings · team · admin · compliance dashboards      │
│  Dev auth: auto-minted local JWT · Prod: Clerk RS256/JWKS            │
└───────────────┬──────────────────────────────────────────────────────┘
                │ REST + WebSocket (Redis pub/sub fanout across workers)
┌───────────────▼──────────────────────────────────────────────────────┐
│  API — FastAPI                                                       │
│  JWT auth middleware → verified tenant context on every request      │
│  Rate limiting (429 w/ Retry-After) · security headers               │
│  Webhooks: per-tenant HMAC verification                              │
└───────┬───────────────────────────────────────────┬──────────────────┘
        │                                           │
┌───────▼────────────────┐            ┌─────────────▼──────────────────┐
│  CELERY WORKERS        │            │  AI PIPELINE (LangGraph)       │
│  queues: asr,          │───────────▶│ chunking → extraction → dedup  │
│  extraction,           │            │ → verification (faithfulness)  │
│  integrations, celery  │            │ → entity resolution → persist  │
└───────┬────────────────┘            │ HITL interrupts + resume       │
        │                             └─────────────┬──────────────────┘
┌───────▼────────────────┐                          │
│  Deepgram Nova-2 ASR   │            ┌─────────────▼──────────────────┐
│  Presidio PII redaction│◀───────────│ LLM calls via LiteLLM client   │
│  (pre-storage/pre-LLM) │            │ budgets(Redis) · circuit brkr  │
└────────────────────────┘            └────────────────────────────────┘

DATA: PostgreSQL16+pgvector (Prisma, RLS-ready) · Qdrant · Neo4j · Redis · MinIO
OBSERVABILITY: OpenTelemetry GenAI spans · Langfuse (optional)
CHECKPOINTS: Postgres-backed LangGraph saver (HITL survives restarts)
```

**Deployment-dependent:** regional AWS topology, customer-managed KMS grants,
Cloudflare routing, provider OAuth credentials, billing/MRR integration,
Kubernetes/Terraform, and independent SOC 2/HIPAA/GDPR evidence are not
created by this repository.

---

## Tech Stack (as built)

| Layer | Technology |
|-------|-----------|
| **ASR** | Deepgram Nova-2 (diarization, word-level timestamps) |
| **LLM** | Groq Llama-3.3-70B primary · GPT-4o fallback (LiteLLM client; optional LiteLLM proxy via `LLM_GATEWAY_URL`) |
| **Pipeline** | LangGraph 0.2 — chunking → extraction → dedup → grounded verification → entity resolution → persistence |
| **Verification** | Guardrails engine: faithfulness scoring, hallucination detection, contradiction & deadline-conflict detection, HITL routing |
| **PII redaction** | Microsoft Presidio (applied before storage and before any LLM call) |
| **Entity resolution** | Neo4j graph traversal + rapidfuzz fuzzy matching |
| **Database** | PostgreSQL 16 + pgvector via Prisma; RLS policies provided (`infrastructure/docker/rls-setup.sql`) |
| **Vector store** | Qdrant (semantic cache — real embeddings when `OPENAI_API_KEY` set, exact-match otherwise) |
| **Graph DB** | Neo4j 5.24 community |
| **Task queue** | Celery (queues: `asr`, `extraction`, `integrations`) — single orchestrator |
| **Events** | Kafka bus, publish-only (HITL/webhook notifications); Redis pub/sub for WebSocket fanout |
| **Object storage** | MinIO (durable bucket/object refs; presigned URLs generated on demand) |
| **Cost analytics** | ClickHouse append-only usage projection + Grafana datasource |
| **Backend** | FastAPI, Pydantic v2, Prisma (Python client) |
| **Frontend** | Next.js 15, TypeScript, TanStack Query, Zustand, shadcn-style UI |
| **Auth** | Clerk RS256/JWKS (production) or local HS256 dev tokens (`POST /auth/dev-token`, dev-only) |
| **Observability** | OpenTelemetry GenAI spans; Langfuse optional; Grafana/ClickHouse cost projection |

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 18+ and Python 3.12+
- API Keys: Deepgram, Groq, OpenAI, Anthropic (optional)

### 1. Clone & Configure
```bash
git clone https://github.com/shivam060404/PraxisFlow.git
cd PraxisFlow
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start Infrastructure
```bash
docker-compose up -d postgres qdrant neo4j kafka redis minio minio-init
```

### 3. Initialize Database
```bash
cd backend
pip install -r requirements.txt
prisma generate
prisma migrate deploy

# Seed the dev tenant + admin user (required: auth fails closed without it)
python scripts/seed_dev.py
```

### 4. Start Services
```bash
# Terminal 1: Backend API
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: Celery Worker
cd backend
celery -A app.workers.celery_app worker --loglevel=info --concurrency=4

# Terminal 3: Frontend
cd frontend
npm install
npm run dev
```

### 5. Or use Docker Compose (Full Stack)
```bash
docker-compose up -d
```

### 6. Access Services
| Service | URL |
|---------|-----|
| **Frontend Dashboard** | http://localhost:3000 (redirects to `/dashboard`) |
| **API Docs (Swagger)** | http://localhost:8000/docs |
| **MinIO Console** | http://localhost:9001 |
| **Neo4j Browser** | http://localhost:7474 |
| **Qdrant Dashboard** | http://localhost:6333/dashboard |
| **Kafka UI** | http://localhost:8080 |

The production compose profile additionally provisions Grafana and
ClickHouse. It does not create AWS KMS keys, regional databases, OAuth
applications, or external billing connections.

---

## Project Structure

```
PraxisFlow/
├── backend/
│   ├── app/
│   │   ├── api/                    # FastAPI routers
│   │   ├── core/                   # settings, paths, shared runtime concerns
│   │   ├── models/                 # persistence/domain model boundary
│   │   ├── schemas/                # validated API and pipeline schemas
│   │   ├── services/               # ASR, storage, PII, events
│   │   ├── workers/                # Celery and Kafka orchestration
│   │   ├── clients/llm_gateway/    # LLM gateway client and resilience
│   │   ├── ai/
│   │   │   ├── agents/              # LangGraph extraction agents
│   │   │   ├── guardrails/         # input/runtime/output safety controls
│   │   │   ├── llm/                # routing, budgets, cache, circuit breaker
│   │   │   ├── prompts/            # typed, versioned prompt catalog
│   │   │   ├── rag/                # chunking, embeddings, tenant-scoped Qdrant retrieval
│   │   │   └── evaluation/         # extraction and verification pipeline
│   │   └── security/, db/, observability/, integrations/
│   ├── alembic/                    # reserved; Prisma is currently authoritative
│   ├── prisma/schema.prisma        # current database source of truth
│   ├── scripts/                    # backend-local operational scripts
│   └── tests/                      # unit, guardrail, and integration tests
├── frontend/                       # Next.js dashboard
├── llm-gateway/
│   ├── config/                     # LiteLLM and routing configuration
│   ├── scripts/                    # gateway operations
│   └── tests/                      # gateway contract tests
├── infrastructure/                 # Docker assets and future K8s/Terraform
├── tests/{integration,e2e,evaluation,load}/
├── scripts/                        # repository-wide automation
├── docs/                           # compliance and engineering documentation

├── docker-compose*.yml              # development and production stacks
└── .github/workflows/              # CI/CD automation
```
The legacy `agents`, `gateway`, and `guardrails` import paths remain as
compatibility modules while new code uses `app.ai`.

## Key Features (as built)

### 0. Ambient ingestion and enterprise distribution
- Google Calendar and Microsoft Graph OAuth with signed state, encrypted
  token references, refresh handling, delta cursors, and reauthorization
- Recall/Fireflies capture callbacks with per-capture HMAC verification
- Signed meeting-bot audio ingress into bounded Deepgram streaming relays
- Versioned `live_transcript` WebSocket events consumed by the dashboard
- Transactional task outbox with leases, retries, dead letters, and audit trail
- Jira, Asana, and Linear remote reconciliation with external status as source
  of truth
- Slack and Teams installation OAuth boundaries with tenant/workspace identity
- Redis-backed LLM budgets, durable usage ledger, ClickHouse projection, and
  Grafana datasource

### 1. Extraction pipeline
- Deepgram Nova-2 ASR with diarization → **Presidio PII redaction before storage and LLM**
- LangGraph: chunking → extraction (JSON-repair retry loop) → deduplication →
  grounded verification → entity resolution (Neo4j + rapidfuzz, persisted to tasks)
- Durable MinIO references — reprocessing never breaks on URL expiry

### 2. Verification & human-in-the-loop
- Faithfulness scoring against transcript; failures route to review, never auto-approve
- Contradiction + deadline-conflict detection across extraction runs
- HITL interrupts with a **Postgres-persisted** checkpointer: resume survives restarts

### 3. Security & tenancy
- Clerk RS256/JWKS in production · local HS256 dev tokens (endpoint hidden outside dev)
- Every query tenant-scoped from verified identity; client-supplied tenant inputs removed
- RLS policies + restricted role ready (`rls-setup.sql`), `tenant_tx()` binds context per transaction
- Production refuses to boot with default secrets

### 4. Reliability & scale
- Redis token budgets shared across workers · circuit breaker on LLM providers
- WebSocket fanout via Redis pub/sub (works with multiple uvicorn workers)
- Celery is the single orchestrator; Kafka bus is publish-only for notifications

### 5. Honest compliance surfaces
- GDPR and AI governance endpoints expose implemented controls and open gaps
- PII/PHI redaction fails closed when the redaction service is unavailable
- Tenant consent, retention, region, and KMS policy fields are enforced at
  code boundaries where supported
- SOC 2, HIPAA/BAA, residency, and formal GDPR certification are not claimed;
  see [docs/COMPLIANCE.md](docs/COMPLIANCE.md)

## API Endpoints (v1)

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/auth/dev-token` | Dev-only local JWT minting (404s outside development / when Clerk configured) |

### Meetings
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/meetings/upload` | Upload meeting audio + metadata |
| `GET` | `/api/v1/meetings` | List meetings (paginated, filterable) |
| `GET` | `/api/v1/meetings/{id}` | Get meeting with transcript + tasks |
| `POST` | `/api/v1/meetings/{id}/process` | Reprocess meeting |

### Tasks
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/tasks` | List tasks (filter by status, type, assignee, priority) |
| `GET` | `/api/v1/tasks/{id}` | Get task with audit log |
| `PATCH` | `/api/v1/tasks/{id}` | Update task (state machine validated) |
| `POST` | `/api/v1/tasks/{id}/verify` | Human-in-the-loop verification |
| `POST` | `/api/v1/tasks/{id}/assign` | Assign to user |
| `POST` | `/api/v1/tasks/bulk-update` | Bulk update |

### Compliance (New)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/compliance/data-subject-requests` | Create DSR (GDPR Art. 15-22) |
| `GET` | `/api/v1/compliance/data-subject-requests` | List DSRs |
| `POST` | `/api/v1/compliance/export` | Export tenant data (GDPR Art. 20) |
| `POST` | `/api/v1/compliance/erase-tenant` | Erase all tenant data (GDPR Art. 17) |
| `GET` | `/api/v1/compliance/ai-audit-logs` | AI audit logs (EU AI Act Art. 12) |
| `GET` | `/api/v1/compliance/eu-ai-act` | EU AI Act compliance status |
| `GET` | `/api/v1/compliance/gdpr` | GDPR compliance status |
| `GET` | `/api/v1/compliance/model-cards` | Model cards (EU AI Act Art. 11) |

### Ambient capture, calendar, and live transcript
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/meetings/{id}/capture` | Register a provider capture |
| `POST` | `/api/v1/capture-webhooks/{provider}` | Receive signed bot lifecycle callback |
| `POST` | `/api/v1/capture-webhooks/{provider}/audio` | Relay signed bot audio to Deepgram |
| `GET` | `/api/v1/calendar/oauth/{provider}/authorize` | Start Google/Microsoft OAuth |
| `GET` | `/api/v1/calendar/oauth/callback` | Complete calendar OAuth |
| `POST` | `/api/v1/calendar/connections/{id}/sync` | Run delta calendar sync |
| `POST` | `/api/v1/live-transcripts/sessions/{meeting_id}` | Reserve live transcript session |
| `WS` | `/api/v1/live-transcripts/ws/{meeting_id}` | Authenticated audio/events channel |

### Provider installation and operations
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/integrations/oauth/{provider}/authorize` | Start Slack/Teams installation |
| `GET` | `/api/v1/integrations/oauth/{provider}/callback` | Complete provider installation |
| `GET` | `/api/v1/admin/tenant/usage` | Tenant LLM usage and cost |

### Admin (New)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/admin/tenant` | Get tenant configuration |
| `PATCH` | `/api/v1/admin/tenant` | Update tenant settings |
| `GET` | `/api/v1/admin/users` | List users with pagination |
| `POST` | `/api/v1/admin/users/invite` | Invite new user |
| `GET` | `/api/v1/admin/integrations` | List integrations |
| `GET` | `/api/v1/admin/audit-logs` | Audit logs with filters |
| `GET` | `/api/v1/admin/compliance/status` | Full compliance status |
| `GET` | `/api/v1/admin/system/health` | Detailed system health |
| `GET` | `/api/v1/admin/system/metrics` | System performance metrics |

---

## Configuration

### Required Environment Variables
| Variable | Description |
|----------|-------------|
| `DEEPGRAM_API_KEY` | Deepgram Nova-2 ASR |
| `GROQ_API_KEY` | Groq (primary LLM) |
| `OPENAI_API_KEY` | OpenAI (fallback + embeddings) |
| `ANTHROPIC_API_KEY` | Anthropic (fallback) |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis for Celery + cache |

### Optional (Production)
| Variable | Description | Default |
|----------|-------------|---------|
| `CALENDAR_OAUTH_STATE_SECRET` | Signed Google/Microsoft OAuth state secret | — |
| `CALENDAR_TOKEN_ENCRYPTION_KEY` | Fernet-compatible calendar token encryption key | — |
| `GOOGLE_OAUTH_CLIENT_ID/SECRET` | Google Calendar OAuth application | — |
| `MICROSOFT_OAUTH_CLIENT_ID/SECRET` | Microsoft Graph OAuth application | — |
| `SLACK_CLIENT_ID/SECRET` | Slack installation OAuth application | — |
| `TEAMS_CLIENT_ID/SECRET` | Teams installation OAuth application | — |
| `AWS_REGION` | AWS region used by KMS clients | `us-east-1` |
| `KMS_REQUIRED_FOR_TENANT_DATA` | Fail closed when a tenant has no CMK | `false` |
| `CLICKHOUSE_URL` | ClickHouse HTTP endpoint for usage projection | — |
| `LLM_GATEWAY_URL` | LiteLLM proxy; required in production-like environments | — |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | — |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | — |
| `LANGFUSE_HOST` | Langfuse host | `http://langfuse:3000` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTel collector endpoint | `http://otel-collector:4317` |
| `CLERK_PUBLISHABLE_KEY` | Clerk auth | — |
| `CLERK_SECRET_KEY` | Clerk secret | — |
| `LITELLM_MASTER_KEY` | LLM Gateway master key | — |

See [`.env.example`](.env.example) for complete list.

Never commit `.env`, OAuth client secrets, provider tokens, KMS credentials,
or generated local secret-store material. The repository intentionally keeps
only non-secret examples.

---

## Development

### Running Tests
```bash
cd backend
pytest tests/ -v --cov=app --cov-report=term-missing
```

For the same service-backed path used by CI, provide Postgres and Redis and
run:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ci \
REDIS_URL=redis://localhost:6379/0 \
pytest tests/ -q --ignore=tests/test_rls.py
```

Frontend checks:

```bash
cd frontend
npx tsc --noEmit
npm run build
npx playwright install chromium
npm run e2e
```

### End-to-End Testing
To verify the entire pipeline (FastAPI + Celery + LLM Extraction), run the provided E2E test script:
```bash
cd backend
python scripts/e2e_test.py
```
This script uploads a dummy meeting, triggers processing, polls the API for status updates, and fetches the resulting extracted tasks.

### Database Migrations
```bash
cd backend
prisma migrate deploy
# Development-only schema changes:
prisma migrate dev --name descriptive_change
# Validate migration drift against a shadow database:
prisma migrate diff --from-migrations prisma/migrations \
  --to-schema-datamodel prisma/schema.prisma \
  --shadow-database-url "$SHADOW_DATABASE_URL" --exit-code
```

### Adding a New Integration
1. Create adapter implementing `IntegrationPort` in `backend/app/integrations/`
2. Implement: `create_task()`, `update_task()`, `delete_task()`, `normalize_webhook()`, `verify_webhook_signature()`, `health_check()`, `get_rate_limits()`
3. Register in `backend/app/integrations/factory.py`:
   ```python
   IntegrationAdapterFactory.register("my_provider", MyAdapter)
   ```

### Code Quality
```bash
# Lint + type check
make lint
make typecheck

# Run security scans
make security-scan
```

---

## Production Deployment

> **Honest status:** the application layer is production-shaped (real auth,
> tenant scoping, persistent checkpoints, Redis-backed budgets/WS fanout),
> but deployment automation is not built yet.

What exists today:
- `docker-compose.prod.yml` with Postgres, Redis, MinIO, ClickHouse, Grafana,
  observability, worker, and gateway service definitions.
- RLS policies ready to apply (`infrastructure/docker/rls-setup.sql`).
- Production config guards for default secrets, LLM gateway enforcement, and
  fail-closed budget/checkpointer behavior.
- CI release gates for Prisma validation/migrations, Postgres/Redis-backed
  tests, strict lint/security checks, frontend build, and Playwright smoke E2E.

What still requires platform provisioning:
- Kubernetes manifests / Helm charts / Terraform
- Regional AWS/Cloudflare routing, KMS grants, and managed-service topology
- Staging/production deployment workflows and rollback automation
- Provider OAuth applications, vendor webhooks, billing/MRR source, and
  independent compliance evidence

Minimum viable production path:
1. Managed Postgres (run `prisma migrate deploy`, then `rls-setup.sql`; connect as
   restricted `praxisflow_app` role)
2. Set strong `JWT_SECRET` + configure Clerk keys (local auth auto-disables)
3. `CHECKPOINTER_BACKEND=postgres`, Redis for budgets/WS relay
4. Run API + Celery workers behind TLS-terminating proxy of your choice

## Cost Estimates (1,000 meetings/month — rough vendor list pricing)

> Disclaimer: back-of-envelope list prices for planning only. Not measured,
> not negotiated, and excludes observability vendors listed in the roadmap.

| Service | Monthly Cost | Notes |
|---------|-------------|-------|
| Deepgram Nova-2 | ~$1,500 | ASR with diarization |
| LLM Gateway (Groq + OpenAI + Anthropic) | ~$120 | With caching + routing optimization |
| OpenAI Embeddings | ~$20 | text-embedding-3-large |
| PostgreSQL (RDS Multi-AZ) | ~$400 | db.r6g.xlarge + read replica |
| Kafka (MSK) | ~$350 | 3 brokers, 3 AZs |
| Redis (ElastiCache) | ~$150 | Cluster mode |
| Neo4j Aura | ~$300 | Professional tier |
| Qdrant Cloud | ~$200 | Managed vector DB |
| Kubernetes (EKS) | ~$600 | 3 nodes (m6i.xlarge) |
| S3 + CloudFront | ~$100 | Object storage + CDN |
| Langfuse (self-hosted) | ~$50 | On same K8s cluster |
| Monitoring (Grafana Cloud) | ~$100 | Metrics + traces + logs |
| **Total** | **~$3,940/mo** | **~$3.94/meeting** |

---

## License

Proprietary — All rights reserved.

---
