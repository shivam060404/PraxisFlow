# PraxisFlow — Architecture Document v2.0

> ⚠️ **Document status:** this describes the *target* architecture. The
> **as-built** reference is README.md ("Architecture — as built"). Components
> marked below that are not in the README as-built diagram (Kong/NGINX edge,
> Elasticsearch, ClickHouse, Jaeger, Sentry, PagerDuty) are roadmap items.

# Enterprise AI Meeting Intelligence Platform
# Last Updated: July 2026 | Classification: Internal

---

## 1. System Overview

PraxisFlow is an enterprise-grade agentic AI platform that transforms meeting recordings into structured, trackable, and accountable execution workflows. The system serves Engineering, Product, Sales, Consulting, HR, and Executive teams with multi-tenant isolation, full AI governance, and bi-directional project management integrations.

### 1.1 Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Zero Trust Security** | Every request authenticated, authorized, and audited regardless of origin |
| **AI Safety by Default** | Guardrails at every LLM interaction point; human-in-the-loop for high-stakes decisions |
| **Tenant Isolation** | Cryptographic + logical separation; no cross-tenant data leakage possible |
| **Observability First** | Every AI decision traced, scored, and explainable via OpenTelemetry GenAI conventions |
| **Provider Agnostic** | LLM Gateway abstracts all model providers; swap without code changes |
| **Compliance Native** | SOC 2, GDPR, EU AI Act, ISO 27001 controls embedded in architecture, not bolted on |
| **Graceful Degradation** | Circuit breakers + fallbacks ensure partial functionality during outages |
| **Cost Governance** | Per-tenant token budgets, semantic caching, model routing optimization |

---

## 2. High-Level Architecture (7 Layers)

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

## 3. LLM Gateway Architecture (NEW — Critical Addition)

The LLM Gateway is the single mandatory path for ALL AI model interactions. No application component calls any LLM provider directly.

### 3.1 Gateway Responsibilities

| Function | Implementation | Purpose |
|----------|---------------|---------|
| **Unified API** | LiteLLM Proxy (self-hosted) | Single OpenAI-compatible endpoint for 100+ providers |
| **Credential Vault** | HashiCorp Vault integration | Zero application-held API keys; automatic rotation |
| **Model Routing** | Policy-based routing rules | Cost-optimize: small models for classification, frontier for extraction |
| **Fallback Chains** | Primary → Secondary → Tertiary | Groq → OpenAI → Anthropic → Azure (per-task configurable) |
| **Semantic Cache** | Qdrant vector similarity | 20-40% cost reduction on repeated/similar prompts |
| **Token Budgets** | Per-tenant, per-user, per-pipeline | Hard limits with graceful degradation |
| **Prompt Inspection** | Pre-flight analysis layer | PII detection, injection detection, topic boundaries |
| **Response Filtering** | Post-response validation | Hallucination flags, PII leaks, format compliance |
| **Cost Attribution** | Real-time metering | Per-tenant, per-meeting, per-pipeline-node billing |
| **Circuit Breakers** | Per-provider health monitoring | Auto-isolate failing providers, prevent cascade |

### 3.2 Model Routing Strategy

```yaml
# llm_gateway/routing_policies.yaml
policies:
  extraction_pipeline:
    primary: groq/llama-3.3-70b-versatile
    fallback:
      - openai/gpt-4o
      - anthropic/claude-sonnet-4-20250514
    max_tokens: 4096
    temperature: 0.1
    timeout_ms: 30000
    retry: 2

  verification_node:
    primary: openai/gpt-4o
    fallback:
      - anthropic/claude-sonnet-4-20250514
    max_tokens: 2048
    temperature: 0.0
    timeout_ms: 20000

  entity_resolution:
    primary: groq/llama-3.3-70b-versatile
    fallback:
      - openai/gpt-4o-mini  # Cost-optimized for simpler task
    max_tokens: 1024
    temperature: 0.0

  embedding:
    primary: openai/text-embedding-3-large
    fallback:
      - cohere/embed-v3
    dimensions: 3072

  summarization:
    primary: groq/llama-3.3-70b-versatile
    fallback:
      - openai/gpt-4o-mini
    max_tokens: 2048
    temperature: 0.3
```

### 3.3 Token Budget Enforcement

```
┌─────────────────────────────────────────────────────────┐
│              TOKEN BUDGET HIERARCHY                       │
├─────────────────────────────────────────────────────────┤
│  Organization Level:  10M tokens/month (hard cap)       │
│    ├── Tenant A:     2M tokens/month                    │
│    │     ├── User 1:  500K tokens/month                 │
│    │     ├── User 2:  500K tokens/month                 │
│    │     └── Pipeline: 1M tokens/month (shared)         │
│    ├── Tenant B:     3M tokens/month                    │
│    └── Tenant C:     5M tokens/month (enterprise tier)  │
│                                                         │
│  Enforcement: Soft limit (80%) → Warning                │
│               Hard limit (100%) → Queue + Notify Admin  │
│               Emergency (120%) → Reject + Alert         │
└─────────────────────────────────────────────────────────┘
```

---

## 4. AI Safety & Guardrails Architecture (NEW — Critical Addition)

### 4.1 Three-Layer Guardrail System

```
REQUEST FLOW:
User Input → [INPUT GUARDRAILS] → LLM Gateway → [RUNTIME GUARDRAILS] → LLM → [OUTPUT GUARDRAILS] → User

Layer 1: INPUT GUARDRAILS (Pre-LLM)
├── Prompt Injection Detection (Lakera Guard / custom classifier)
├── PII Detection & Redaction (Microsoft Presidio)
├── Topic Boundary Enforcement (meeting-context-only policy)
├── Jailbreak Pattern Detection (regex + ML classifier)
├── Input Length Validation (prevent context overflow attacks)
└── Tenant Data Isolation Check (no cross-tenant context leakage)

Layer 2: RUNTIME GUARDRAILS (During LLM Call)
├── NVIDIA NeMo Guardrails (Colang policies)
│   ├── Extraction scope enforcement
│   ├── Refuse out-of-scope generation
│   └── Force structured output format
├── Token Limit Enforcement (per-request hard cap)
├── Latency Budget (timeout + circuit breaker)
├── Temperature Lock (0.0-0.1 for extraction; prevent creative drift)
└── Max Retry with Exponential Backoff

Layer 3: OUTPUT GUARDRAILS (Post-LLM)
├── Anti-Hallucination Verification
│   ├── Faithfulness Score (≥ 0.7 threshold)
│   ├── Completeness Score (all required fields present)
│   ├── Grounding Check (every claim traceable to transcript)
│   └── Contradiction Detection (vs. prior extractions)
├── PII Leak Detection (output scanning)
├── Format Validation (Pydantic schema enforcement)
├── Confidence Threshold (below threshold → human review queue)
└── Content Policy Check (no harmful/biased content)
```

### 4.2 NeMo Guardrails Configuration (Colang)

```colang
# guardrails/extraction_policies.co

define flow extraction_scope
  user said something
  if not meeting_context
    bot refuse "I can only extract action items from meeting transcripts."
    stop

define flow prevent_hallucination
  bot said something
  if not grounded_in_transcript
    bot inform "This extraction could not be verified against the source transcript."
    flag for human review

define flow pii_protection
  user said something
  if contains_pii
    $redacted = redact_pii($user_message)
    bot continue with $redacted

define flow output_format_enforcement
  bot said something
  if not valid_json_schema
    bot retry with format correction
    max_retries 2
```

### 4.3 Human-in-the-Loop Verification Matrix

| Confidence Score | Action | SLA |
|-----------------|--------|-----|
| ≥ 0.90 | Auto-approve → ASSIGNED | Immediate |
| 0.70 – 0.89 | Queue for review → PENDING_REVIEW | < 4 hours |
| 0.50 – 0.69 | Flag + highlight concerns → PENDING_REVIEW | < 2 hours |
| < 0.50 | Reject + re-extract with different model | Immediate retry |
| Contradiction detected | Block + notify meeting owner | < 1 hour |
| PII detected in output | Block + redact + alert compliance | Immediate |

---

## 5. Multi-Tenant Security Architecture (Enhanced)

### 5.1 Isolation Model

```
┌─────────────────────────────────────────────────────────────┐
│                    TENANT ISOLATION LAYERS                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: Network Isolation                                 │
│  ├── Per-tenant API key (scoped to gateway)                 │
│  ├── Tenant ID in every request header (X-Tenant-ID)        │
│  └── mTLS between internal services                         │
│                                                             │
│  Layer 2: Application Isolation                             │
│  ├── Middleware extracts tenant from JWT claims             │
│  ├── All queries scoped by tenant_id (enforced, not opt-in) │
│  ├── Per-tenant Kafka topic partitioning                    │
│  └── Per-tenant Qdrant collection namespace                 │
│                                                             │
│  Layer 3: Data Isolation                                    │
│  ├── PostgreSQL Row-Level Security (RLS) policies           │
│  ├── Per-tenant encryption keys (envelope encryption)       │
│  ├── Neo4j tenant-scoped graph partitions                   │
│  └── MinIO per-tenant bucket with IAM policies              │
│                                                             │
│  Layer 4: AI Isolation                                      │
│  ├── Per-tenant LLM token budgets                           │
│  ├── Per-tenant model access policies                       │
│  ├── No cross-tenant context in prompts                     │
│  └── Per-tenant embedding namespace (no vector leakage)     │
│                                                             │
│  Layer 5: Audit Isolation                                   │
│  ├── Per-tenant immutable audit log                         │
│  ├── Per-tenant AI decision trail                           │
│  └── Tenant admin self-service compliance export            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 RBAC + ABAC Model

```
ROLES (per tenant):
├── tenant_admin        → Full tenant management, billing, compliance export
├── team_lead           → View all team meetings, assign tasks, configure integrations
├── member              → View own meetings, verify/complete assigned tasks
├── viewer              → Read-only access to shared dashboards
└── api_service         → Machine-to-machine (integration webhooks)

ATTRIBUTES (ABAC conditions):
├── department          → Engineering, Product, Sales, HR, Consulting, Executive
├── clearance_level     → Standard, Confidential, Restricted
├── data_residency      → US, EU, APAC (affects processing region)
├── meeting_sensitivity → Public, Internal, Confidential, Board-Level
└── ip_allowlist        → Per-tenant network restrictions

POLICY ENGINE: OPA (Open Policy Agent) / Cedar
├── Evaluated on every API request
├── Cached per-session for performance
└── Audit-logged for compliance
```

---

## 6. AI Observability & Explainability (NEW — Critical Addition)

### 6.1 OpenTelemetry GenAI Semantic Conventions

Every LLM interaction emits structured traces following the OTel GenAI spec:

```python
# Trace attributes per LLM call:
{
    "gen_ai.system": "groq",
    "gen_ai.request.model": "llama-3.3-70b-versatile",
    "gen_ai.request.max_tokens": 4096,
    "gen_ai.request.temperature": 0.1,
    "gen_ai.response.model": "llama-3.3-70b-versatile",
    "gen_ai.response.finish_reasons": ["stop"],
    "gen_ai.usage.input_tokens": 2847,
    "gen_ai.usage.output_tokens": 1203,
    "gen_ai.usage.total_tokens": 4050,
    "praxisflow.tenant_id": "tenant_abc123",
    "praxisflow.meeting_id": "mtg_xyz789",
    "praxisflow.pipeline_node": "extraction",
    "praxisflow.pipeline_run_id": "run_def456",
    "praxisflow.guardrail_actions": ["pii_redaction:2_entities"],
    "praxisflow.confidence_score": 0.87,
    "praxisflow.latency_ms": 3420,
    "praxisflow.cost_usd": 0.0034
}
```

### 6.2 Observability Stack

| Component | Tool | Purpose |
|-----------|------|---------|
| **LLM Tracing** | Langfuse (self-hosted) | Per-prompt/response tracing, evals, cost attribution |
| **Distributed Traces** | Jaeger + OTel Collector | End-to-end request tracing across services |
| **Metrics** | Prometheus + Grafana | Latency, throughput, error rates, token usage |
| **Logging** | Structured JSON → ClickHouse | Queryable audit logs, AI decision trails |
| **Alerting** | Grafana Alerting + PagerDuty | SLO breaches, cost anomalies, guardrail triggers |
| **AI Evals** | Langfuse Evals + custom | Extraction accuracy, hallucination rate, drift detection |
| **Cost Analytics** | Custom dashboard (ClickHouse) | Per-tenant, per-pipeline, per-model cost breakdown |
| **Drift Detection** | Custom (embedding similarity) | Detect model degradation, prompt distribution shift |

### 6.3 AI Explainability Requirements

Every extracted task MUST include:
- **Source Quote**: Exact transcript segment (with timestamp + speaker)
- **Confidence Score**: 0.0-1.0 with breakdown (faithfulness, completeness, grounding)
- **Model Attribution**: Which model, version, and parameters produced the extraction
- **Guardrail Actions**: What was filtered, redacted, or flagged
- **Human Override History**: Every human edit with reason code
- **Token Economics**: Input/output tokens, cost, latency for this extraction

---

## 7. Compliance & Governance Framework (NEW — Critical Addition)

### 7.1 EU AI Act Compliance (Mandatory: August 2, 2026)

The EU AI Act's high-risk AI system requirements become mandatory August 2, 2026,
with fines reaching up to €35 million or 7% of global revenue.

| EU AI Act Requirement | PraxisFlow Implementation |
|----------------------|--------------------------|
| **Risk Management System** (Art. 9) | AI Risk Register + quarterly review process |
| **Data Governance** (Art. 10) | Data lineage tracking, consent management, DPA |
| **Technical Documentation** (Art. 11) | Model cards, system documentation, architecture docs |
| **Record-Keeping** (Art. 12) | Immutable AI audit log (every LLM decision) |
| **Transparency** (Art. 13) | User-facing AI disclosure, extraction confidence display |
| **Human Oversight** (Art. 14) | Human-in-the-loop verification, override capability |
| **Accuracy & Robustness** (Art. 15) | Continuous evals, adversarial testing, drift detection |
| **Cybersecurity** (Art. 15) | Penetration testing, vulnerability scanning, incident response |

### 7.2 SOC 2 Type II Controls

| Trust Service Criteria | Implementation |
|----------------------|----------------|
| **CC6.1** (Logical Access) | RBAC/ABAC, MFA, session management, IP allowlists |
| **CC6.2** (Access Provisioning) | Automated deprovisioning, access reviews (quarterly) |
| **CC7.2** (Monitoring) | Real-time alerting, anomaly detection, SIEM integration |
| **CC7.3** (Change Detection) | Immutable audit log, change management workflow |
| **CC8.1** (Change Management) | CI/CD with approval gates, rollback capability |
| **A1.2** (Availability) | Multi-AZ, 99.9% SLA, disaster recovery runbook |
| **PI1.3** (Processing Integrity) | Input/output validation, reconciliation checks |

### 7.3 GDPR Compliance

| Requirement | Implementation |
|-------------|----------------|
| **Data Minimization** (Art. 5(1)(c)) | PII redaction before LLM processing; only necessary data sent |
| **Purpose Limitation** (Art. 5(1)(b)) | Meeting data used ONLY for task extraction; no training |
| **Right to Erasure** (Art. 17) | Cascade delete: audio → transcript → embeddings → tasks → audit |
| **Data Portability** (Art. 20) | Export API: JSON/CSV export of all tenant data |
| **DPA** (Art. 28) | Data Processing Agreement with all sub-processors (Deepgram, Groq, OpenAI) |
| **Breach Notification** (Art. 33) | 72-hour notification workflow, automated detection |
| **Data Residency** (Art. 44) | Region-locked processing (EU data stays in EU) |

---

## 8. Enhanced LangGraph Pipeline (7 Nodes)

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  1.INGEST│───▶│  2.CHUNK │───▶│ 3.EXTRACT│───▶│ 4.DEDUP  │
│  & ASR   │    │  & PREP  │    │  (LLM)   │    │  & MERGE │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                      │
┌──────────┐    ┌──────────┐    ┌──────────┐         │
│ 7.PERSIST│◀───│ 6.RESOLVE│◀───│ 5.VERIFY │◀────────┘
│  & SYNC  │    │  & SCORE │    │  (HITL)  │
└──────────┘    └──────────┘    └──────────┘

Node Details:
1. INGEST & ASR: Audio upload → Deepgram Nova-2 → Diarized transcript → PII Redaction
2. CHUNK & PREP: Split by speaker turns (2000 words) → Context window → Metadata enrichment
3. EXTRACT (LLM): LangGraph → LLM Gateway → Structured task extraction → Schema validation
4. DEDUP & MERGE: Cross-chunk deduplication → Conflict resolution → Priority assignment
5. VERIFY (HITL): Anti-hallucination scoring → Confidence threshold → Human review queue
6. RESOLVE & SCORE: Entity resolution (Neo4j) → Deadline parsing → Assignee matching → Risk scoring
7. PERSIST & SYNC: Database write → Kafka event → Integration push → WebSocket notify
```

---

## 9. Integration Architecture (Enhanced)

### 9.1 Adapter Pattern v2

```python
class IntegrationPort(ABC):
    """Base interface for all work management integrations."""

    # Core CRUD
    async def create_task(self, task: ExtractedTask) -> ExternalTaskRef: ...
    async def update_task(self, ref: ExternalTaskRef, updates: TaskUpdate) -> None: ...
    async def delete_task(self, ref: ExternalTaskRef) -> None: ...

    # Webhook handling
    async def normalize_webhook(self, payload: dict) -> NormalizedEvent: ...
    async def verify_webhook_signature(self, headers: dict, body: bytes) -> bool: ...

    # Sync & reconciliation
    async def reconcile_status(self, ref: ExternalTaskRef) -> SyncStatus: ...
    async def bulk_sync(self, tasks: list[ExtractedTask]) -> BulkSyncResult: ...

    # Health & observability
    async def health_check(self) -> IntegrationHealth: ...
    def get_rate_limits(self) -> RateLimitConfig: ...

# Supported integrations (Phase 1-3):
# Phase 1: Jira, Asana, Linear, Slack
# Phase 2: Monday.com, Notion, Microsoft Teams, GitHub Issues
# Phase 3: Salesforce, ServiceNow, SAP, Custom (REST/gRPC)
```

---

## 10. Deployment Architecture

### 10.1 Development (Docker Compose — 14 services)
### 10.2 Staging (Kubernetes — single region)
### 10.3 Production (Kubernetes — multi-region)

```
Production Topology:
├── Region: us-east-1 (primary)
│   ├── EKS Cluster (3 AZs)
│   │   ├── API Pods (auto-scale 3-20)
│   │   ├── Worker Pods (auto-scale 2-10)
│   │   ├── LLM Gateway Pods (auto-scale 2-8)
│   │   └── WebSocket Pods (auto-scale 2-6)
│   ├── RDS PostgreSQL (Multi-AZ, read replicas)
│   ├── MSK Kafka (3 brokers, 3 AZs)
│   ├── ElastiCache Redis (cluster mode)
│   ├── Neo4j Aura (managed)
│   ├── Qdrant Cloud (managed)
│   └── S3 (object storage)
│
├── Region: eu-west-1 (EU data residency)
│   └── [Mirror topology for EU tenants]
│
├── CDN: CloudFront (frontend assets)
├── WAF: AWS WAF + Shield Advanced
├── Secrets: AWS Secrets Manager + Vault
└── Monitoring: CloudWatch + Grafana Cloud
```