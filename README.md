# PraxisFlow — Enterprise AI Meeting Intelligence & Action Command Center

An enterprise-grade agentic AI platform that transforms passive meeting recordings into structured, trackable, and accountable execution workflows. Built for regulated industries with full AI governance, compliance, and observability.

[![GitHub](https://img.shields.io/badge/GitHub-PraxisFlow-181717?logo=github)](https://github.com/shivam060404/PraxisFlow)
[![CI/CD](https://img.shields.io/github/actions/workflow/status/shivam060404/PraxisFlow/ci.yml?branch=main)](https://github.com/shivam060404/PraxisFlow/actions)
[![Security](https://img.shields.io/badge/Security-SOC2%20%7C%20GDPR%20%7C%20EU%20AI%20Act-blue)](docs/COMPLIANCE.md)

---

## Current Status (Verified)
The backend architecture has been recently audited and is fully functionally verified. All database schemas, telemetry metrics, integrations, guardrails, and agentic workflows load seamlessly and are resilient against local dependency startup failures.

---

## Architecture (v2.0 — Enterprise)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PRESENTATION LAYER                                    │
│  Next.js 15 │ shadcn/ui │ Kanban │ Real-time WS │ Role-based Dashboards     │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │ HTTPS / WSS (TLS 1.3)
┌──────────────────────────────────▼──────────────────────────────────────────┐
│                        API GATEWAY / EDGE LAYER                              │
│  Kong/NGINX │ Rate Limiting │ WAF │ Request Validation │ Tenant Resolution   │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────────────┐
│                     APPLICATION / API LAYER                                   │
│  FastAPI │ WebSocket │ Celery Workers │ Kafka Producers/Consumers            │
│  RBAC/ABAC Engine │ Tenant Middleware │ Request Scoping                      │
└────────┬─────────────────────────────────────────────────┬──────────────────┘
         │                                                 │
┌────────▼────────────────────┐              ┌─────────────▼──────────────────┐
│     AI ORCHESTRATION        │              │     LLM GATEWAY LAYER          │
│     LAYER                   │              │                                │
│  LangGraph Multi-Agent      │◀────────────▶│  LiteLLM Proxy                 │
│  Pipeline (7 nodes)         │              │  • Unified API (100+ providers)│
│  • Chunking                 │              │  • Semantic Caching            │
│  • Extraction               │              │  • Model Routing & Fallbacks   │
│  • Deduplication            │              │  • Token Budget Enforcement    │
│  • Verification             │              │  • Credential Management       │
│  • Entity Resolution        │              │  • Prompt Inspection           │
│  • Conflict Resolution      │              │  • Response Filtering          │
│  • Persistence              │              │  • Cost Attribution            │
└────────┬────────────────────┘              └────────────────────────────────┘
         │
┌────────▼────────────────────────────────────────────────────────────────────┐
│                     AI SAFETY & GUARDRAILS LAYER                             │
│                                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │   INPUT     │  │   RUNTIME    │  │   OUTPUT    │  │   GOVERNANCE    │  │
│  │ GUARDRAILS  │  │ GUARDRAILS   │  │ GUARDRAILS  │  │   & COMPLIANCE  │  │
│  │             │  │              │  │             │  │                 │  │
│  │• Prompt     │  │• NeMo        │  │• Halluc.    │  │• EU AI Act     │  │
│  │  Injection  │  │  Guardrails  │  │  Detection  │  │  Audit Trail   │  │
│  │• PII Scan   │  │• Token       │  │• PII Leak   │  │• GDPR DPA      │  │
│  │• Topic      │  │  Limits      │  │  Detection  │  │• SOC 2 Controls│  │
│  │  Boundary   │  │• Latency     │  │• Factuality │  │• Model Cards   │  │
│  │• Jailbreak  │  │  Budgets     │  │  Scoring    │  │• Risk Register │  │
│  │  Detection  │  │• Circuit     │  │• Format     │  │• Consent Mgmt  │  │
│  │             │  │  Breakers    │  │  Validation │  │• Data Lineage  │  │
│  └─────────────┘  └──────────────┘  └─────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
         │
┌────────▼────────────────────────────────────────────────────────────────────┐
│                     DATA & MEMORY LAYER                                      │
│                                                                             │
│  PostgreSQL 16    │ Qdrant v1.12  │ Neo4j 5.24    │ Redis 7               │
│  + pgvector       │ (Vectors)     │ (Graph)       │ (Cache + Broker)      │
│  + RLS            │               │ + APOC + GDS  │                       │
│                   │               │               │                       │
│  MinIO (S3)       │ Kafka (KRaft) │ Elasticsearch │ ClickHouse            │
│  (Object Store)   │ (Events)      │ (Search)      │ (Analytics/OLAP)     │
└─────────────────────────────────────────────────────────────────────────────┘
         │
┌────────▼────────────────────────────────────────────────────────────────────┐
│                     OBSERVABILITY & AI MONITORING LAYER                      │
│                                                                             │
│  OpenTelemetry (GenAI Semantic Conventions)                                 │
│  Langfuse (LLM Tracing + Evals) │ Grafana (Dashboards) │ PagerDuty        │
│  Prometheus (Metrics)           │ Jaeger (Traces)       │ Sentry (Errors)  │
│  AI Audit Log (Immutable)       │ Cost Analytics        │ Drift Detection  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack (Enterprise)

| Layer | Technology |
|-------|-----------|
| **ASR** | Deepgram Nova-2 (speaker diarization, word-level timestamps) |
| **LLM Gateway** | LiteLLM Proxy (Groq, OpenAI, Anthropic, Cohere — 100+ providers) |
| **LLM Extraction** | Llama 3.3 70B / GPT-4o / Claude Sonnet 4 via Gateway |
| **Verification** | Anti-hallucination guardrail (faithfulness/hallucination/completeness) |
| **Guardrails** | NVIDIA NeMo Guardrails (Colang policies) + custom 3-layer |
| **Entity Resolution** | Neo4j graph traversal + rapidfuzz fuzzy matching |
| **PII Redaction** | Microsoft Presidio (analyzer + anonymizer) |
| **Database** | PostgreSQL 16 + pgvector, Row-Level Security |
| **Vector Store** | Qdrant v1.12 (semantic caching, embeddings) |
| **Graph DB** | Neo4j 5.24 Enterprise (APOC + GDS) |
| **Message Queue** | Apache Kafka (KRaft mode) |
| **Task Queue** | Celery + Redis |
| **Object Storage** | MinIO (S3-compatible) |
| **Backend** | FastAPI, Prisma ORM, Pydantic v2 |
| **Frontend** | Next.js 15, TypeScript, shadcn/ui, TanStack Query, Zustand |
| **Auth** | Clerk (JWT) + RBAC/ABAC middleware |
| **Secrets** | HashiCorp Vault / AWS Secrets Manager |
| **Observability** | OpenTelemetry GenAI, Langfuse, Prometheus, Grafana, Jaeger |
| **Integrations** | Jira, Asana, Linear, Slack, GitHub, Salesforce, Notion, Teams (adapter pattern) |

---

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
prisma db push
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
| **Frontend Dashboard** | http://localhost:3000 |
| **API Docs (Swagger)** | http://localhost:8000/docs |
| **LLM Gateway** | http://localhost:4000 |
| **Kafka UI** | http://localhost:8080 |
| **MinIO Console** | http://localhost:9001 |
| **Neo4j Browser** | http://localhost:7474 |
| **Qdrant Dashboard** | http://localhost:6333/dashboard |
| **Langfuse** | http://localhost:3000 |
| **Grafana** | http://localhost:3001 |

---

## Project Structure

```
PraxisFlow/
├── backend/
│   ├── app/
│   │   ├── api/                      # FastAPI route handlers
│   │   │   ├── v1/
│   │   │   │   ├── meetings.py
│   │   │   │   ├── tasks.py
│   │   │   │   ├── transcripts.py
│   │   │   │   ├── integrations.py
│   │   │   │   ├── websocket.py
│   │   │   │   ├── users.py
│   │   │   │   ├── metrics.py
│   │   │   │   ├── admin.py          # Tenant admin endpoints
│   │   │   │   ├── compliance.py     # DSRs, exports, audit logs
│   │   │   │   └── webhooks.py       # Inbound webhook handlers
│   │   │   └── deps.py
│   │   ├── agents/                   # LangGraph AI pipeline
│   │   │   ├── extraction_graph.py   # 7-node pipeline
│   │   │   ├── graph_runner.py
│   │   │   ├── entity_resolution.py
│   │   │   ├── schemas.py
│   │   │   └── conflict_resolution.py
│   │   ├── gateway/                  # LLM Gateway client
│   │   │   ├── client.py
│   │   │   ├── routing.py
│   │   │   ├── budgets.py
│   │   │   ├── caching.py
│   │   │   └── circuit_breaker.py
│   │   ├── guardrails/               # AI Safety (3-layer)
│   │   │   ├── input_guardrails.py
│   │   │   ├── runtime_guardrails.py
│   │   │   ├── output_guardrails.py
│   │   │   ├── manager.py
│   │   │   ├── base.py
│   │   │   └── config/
│   │   ├── observability/            # OTel GenAI + Langfuse
│   │   │   ├── otel.py
│   │   │   ├── langfuse.py
│   │   │   ├── audit_log.py
│   │   │   └── main.py
│   │   ├── security/                 # RBAC/ABAC + Secrets
│   │   │   ├── rbac.py
│   │   │   ├── abac.py
│   │   │   ├── opa_client.py
│   │   │   ├── secrets.py
│   │   │   ├── encryption.py
│   │   │   └── middleware.py
│   │   ├── compliance/               # GDPR, EU AI Act
│   │   │   ├── gdpr.py
│   │   │   ├── eu_ai_act.py
│   │   │   └── model_cards.py
│   │   ├── integrations/             # External tool adapters
│   │   │   ├── factory.py
│   │   │   ├── base.py
│   │   │   ├── jira.py
│   │   │   ├── asana.py
│   │   │   ├── linear.py
│   │   │   ├── slack.py
│   │   │   ├── github.py
│   │   │   ├── salesforce.py
│   │   │   └── teams.py
│   │   ├── services/
│   │   ├── workers/
│   │   └── core/
│   ├── prisma/schema.prisma          # 18+ models, 10+ enums
│   └── tests/
├── frontend/
│   ├── app/dashboard/
│   │   ├── compliance/               # Compliance dashboard
│   │   ├── admin/                    # Tenant admin panel
│   │   └── ...other pages
├── llm-gateway/                      # LiteLLM Proxy service
│   ├── litellm_config.yaml
│   ├── routing_policies.yaml
│   └── Dockerfile
├── guardrails/                       # NeMo Colang policies
│   ├── colang/
│   └── config/
├── infrastructure/
│   ├── docker/
│   ├── k8s/                          # Kubernetes manifests
│   ├── terraform/                    # IaC
│   └── helm/
├── .github/workflows/                # CI/CD pipelines
│   ├── ci.yml
│   ├── deploy-staging.yml
│   └── deploy-production.yml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── COMPLIANCE.md
│   └── SECURITY.md
├── docker-compose.yml                # Dev stack (12 services)
├── docker-compose.prod.yml           # Production stack (18 services)
├── Makefile                          # Developer commands
└── .env.example
```

---

## Key Enterprise Features

### 1. LLM Gateway (Critical)
- **Unified API** — Single OpenAI-compatible endpoint for 100+ providers
- **Model Routing** — Cost-optimized: small models for classification, frontier for extraction
- **Fallback Chains** — Groq → OpenAI → Anthropic → Azure (per-task configurable)
- **Semantic Caching** — Qdrant-backed, 20-40% cost reduction on repeated prompts
- **Token Budgets** — Org → Tenant → User hierarchy with soft/hard/emergency limits
- **Circuit Breakers** — Per-provider health monitoring, auto-isolation
- **Cost Attribution** — Per-tenant, per-meeting, per-pipeline-node billing

### 2. AI Safety & Guardrails (3-Layer)
| Layer | Components |
|-------|------------|
| **Input** | Prompt injection detection (Lakera/custom), PII redaction (Presidio), topic boundaries, jailbreak patterns, length limits, tenant isolation |
| **Runtime** | NeMo Guardrails (Colang), token limits, temperature locks, latency budgets, circuit breakers, structured output enforcement |
| **Output** | Hallucination detection (faithfulness ≥0.7), PII leak scanning, format validation (Pydantic), confidence thresholds → human review, contradiction detection, content policy |

### 3. Human-in-the-Loop (HITL)
| Confidence | Action | SLA |
|------------|--------|-----|
| ≥ 0.90 | Auto-approve → ASSIGNED | Immediate |
| 0.70–0.89 | Queue for review | < 4 hours |
| 0.50–0.69 | Flag + highlight | < 2 hours |
| < 0.50 | Reject + re-extract | Immediate |
| Contradiction | Block + notify owner | < 1 hour |
| PII in output | Block + redact + alert | Immediate |

### 4. Multi-Tenant Security (Zero Trust)
- **Network**: Per-tenant API keys, X-Tenant-ID headers, mTLS
- **Application**: Middleware extracts tenant from JWT, enforces scoping
- **Data**: PostgreSQL RLS + per-tenant encryption keys, Neo4j partitions, MinIO IAM
- **AI**: Per-tenant token budgets, model access policies, no cross-tenant context
- **Audit**: Per-tenant immutable audit logs, self-service compliance export

### 5. Full Observability
- **OpenTelemetry GenAI** — Every LLM call traced with semantic conventions
- **Langfuse** — Prompt/response tracing, evals, cost attribution, prompt versioning
- **Prometheus + Grafana** — Latency, throughput, error rates, token usage
- **AI Audit Log** — Immutable, cryptographically signed, 7-year retention

### 6. Compliance & Governance (Native)
| Regulation | Implementation |
|------------|----------------|
| **EU AI Act (Aug 2, 2026)** | Risk register, model cards, technical docs, immutable audit log, HITL, continuous evals, pen testing |
| **GDPR** | PII redaction pre-LLM, purpose limitation, cascade delete, portability export, DPAs, 72h breach notification, EU data residency |
| **SOC 2 Type II** | RBAC/ABAC, automated access reviews, real-time monitoring, change management, multi-AZ, processing integrity |
| **ISO 27001** | Aligned controls across all domains |

---

## API Endpoints (v1)

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
| `VAULT_ADDR` | HashiCorp Vault address | — |
| `VAULT_TOKEN` | Vault authentication token | — |
| `AWS_REGION` | AWS region for Secrets Manager | `us-east-1` |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | — |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | — |
| `LANGFUSE_HOST` | Langfuse host | `http://langfuse:3000` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTel collector endpoint | `http://otel-collector:4317` |
| `CLERK_PUBLISHABLE_KEY` | Clerk auth | — |
| `CLERK_SECRET_KEY` | Clerk secret | — |
| `LITELLM_MASTER_KEY` | LLM Gateway master key | — |

See [`.env.example`](.env.example) for complete list.

---

## Development

### Running Tests
```bash
cd backend
pytest tests/ -v --cov=app --cov-report=term-missing
```

### Database Migrations
```bash
cd backend
prisma migrate dev --name migration_name
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

### Required Infrastructure
- PostgreSQL 16+ with pgvector (RDS / Cloud SQL)
- Qdrant (managed or self-hosted)
- Neo4j Enterprise 5.24+ (Aura / self-hosted)
- Kafka 3.8+ (MSK / Confluent Cloud)
- Redis 7+ (ElastiCache / self-hosted)
- S3-compatible object storage
- Kubernetes (EKS / GKE / AKS) for orchestration

### Security Features
- TLS 1.3 for all connections
- Row-Level Security for multi-tenant isolation
- PII redaction at ingestion (Presidio)
- JWT authentication via Clerk + RBAC/ABAC middleware
- Webhook signature verification (HMAC-SHA256)
- AI audit logging for every LLM decision
- HashiCorp Vault / AWS Secrets Manager for secrets

### Deployment
```bash
# Build images
docker compose -f docker-compose.prod.yml build

# Deploy to Kubernetes
kubectl apply -k infrastructure/k8s/production

# Or use Terraform
cd infrastructure/terraform/production && terraform apply
```

---

## Cost Estimates (1,000 meetings/month, Production)

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

