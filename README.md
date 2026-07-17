# PraxisFlow — AI Meeting Intelligence & Action Command Center

An enterprise-grade agentic system that transforms passive meeting recordings into structured, trackable, and accountable execution workflows. Powered by LangGraph multi-agent extraction, Deepgram ASR, and bi-directional project management integrations.

[![GitHub](https://img.shields.io/badge/GitHub-PraxisFlow-181717?logo=github)](https://github.com/shivam060404/PraxisFlow)

---

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Ingestion     │────▶│  AI Processing   │────▶│  Data & Memory  │
│   Layer         │     │  Engine          │     │  Layer          │
│                 │     │                  │     │                 │
│ • Audio Upload  │     │ • LangGraph      │     │ • PostgreSQL    │
│ • Deepgram ASR  │     │ • Extraction     │     │ • Qdrant        │
│ • PII Redaction │     │ • Verification   │     │ • Neo4j         │
│ • MinIO Storage │     │ • Deduplication  │     │ • Redis         │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                        │
┌─────────────────┐     ┌──────────────────┐            │
│  Presentation   │◀────│  Application     │◀───────────┘
│  Layer          │     │  / API Layer     │
│                 │     │                  │
│ • Next.js 15    │     │ • FastAPI        │
│ • shadcn/ui     │     │ • WebSocket      │
│ • Kanban Board  │     │ • Celery Workers │
│ • Real-time WS  │     │ • Kafka Events   │
└─────────────────┘     └──────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **ASR** | Deepgram Nova-2 (speaker diarization, word-level timestamps) |
| **LLM Extraction** | Llama 3.3 70B via Groq (LangGraph multi-node pipeline) |
| **Verification** | Anti-hallucination guardrail (faithfulness/hallucination/completeness scoring) |
| **Entity Resolution** | Neo4j graph traversal + rapidfuzz fuzzy matching |
| **PII Redaction** | Microsoft Presidio (analyzer + anonymizer) |
| **Database** | PostgreSQL 16 + pgvector, Row-Level Security |
| **Vector Store** | Qdrant v1.12 |
| **Graph DB** | Neo4j 5.24 Enterprise (APOC + GDS) |
| **Message Queue** | Apache Kafka (KRaft mode) |
| **Task Queue** | Celery + Redis |
| **Object Storage** | MinIO (S3-compatible) |
| **Backend** | FastAPI, Prisma ORM, Pydantic v2 |
| **Frontend** | Next.js 15, TypeScript, shadcn/ui, TanStack Query, Zustand |
| **Auth** | Clerk (JWT) |
| **Integrations** | Jira, Asana, Linear, Slack (adapter pattern) |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Node.js 18+ and Python 3.11+
- API Keys: Deepgram, Groq, OpenAI

### 1. Clone & Configure

```bash
git clone https://github.com/shivam060404/PraxisFlow.git
cd PraxisFlow
cp .env.example .env
# Edit .env with your API keys (DEEPGRAM_API_KEY, GROQ_API_KEY, OPENAI_API_KEY)
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

### 5. Or use Docker Compose for everything

```bash
docker-compose up -d
```

### 6. Access

| Service | URL |
|---------|-----|
| **Frontend Dashboard** | http://localhost:3000 |
| **API Docs (Swagger)** | http://localhost:8000/docs |
| **Kafka UI** | http://localhost:8080 |
| **MinIO Console** | http://localhost:9001 (ami / ami_dev_password) |
| **Neo4j Browser** | http://localhost:7474 (neo4j / ami_dev_password) |
| **Qdrant Dashboard** | http://localhost:6333/dashboard |

## Project Structure

```
PraxisFlow/
├── backend/
│   ├── app/
│   │   ├── api/                  # FastAPI route handlers
│   │   │   ├── meetings.py       # Meeting CRUD + upload + reprocess
│   │   │   ├── tasks.py          # Task CRUD + state machine + bulk ops
│   │   │   ├── transcripts.py    # Transcript retrieval + search
│   │   │   ├── integrations.py   # Integration CRUD + webhooks
│   │   │   ├── websocket.py      # Real-time WebSocket (tenant-isolated)
│   │   │   ├── users.py          # User management
│   │   │   └── metrics.py        # Analytics endpoints
│   │   ├── agents/               # LangGraph AI pipeline
│   │   │   ├── extraction_graph.py   # 6-node pipeline (chunk→extract→dedup→verify→resolve→persist)
│   │   │   ├── graph_runner.py       # Pipeline orchestrator with streaming support
│   │   │   ├── entity_resolution.py  # Neo4j + fuzzy matching assignee resolver
│   │   │   └── schemas.py            # Pydantic models for pipeline state
│   │   ├── db/prisma.py          # Prisma client + RLS helpers
│   │   ├── integrations/         # External tool adapters
│   │   │   ├── factory.py        # IntegrationPort ABC + adapter factory
│   │   │   └── jira.py           # Jira, Asana, Linear, Slack adapters
│   │   ├── schemas/              # Pydantic request/response models
│   │   ├── services/             # Business logic
│   │   │   ├── asr.py            # Deepgram transcription service
│   │   │   ├── kafka_events.py   # Event bus (producer + consumer)
│   │   │   ├── pii_redaction.py  # Microsoft Presidio PII redaction
│   │   │   └── storage.py        # MinIO object storage
│   │   ├── workers/              # Async task processing
│   │   │   ├── celery_app.py     # Celery config + task routing
│   │   │   ├── tasks.py          # Meeting processing pipeline tasks
│   │   │   └── kafka_consumers.py # Event-driven consumer handlers
│   │   ├── core/config.py        # Settings via pydantic-settings
│   │   └── main.py               # FastAPI app + middleware + lifecycle
│   ├── prisma/schema.prisma      # Database schema (11 models, 6 enums)
│   ├── tests/                    # pytest test suite
│   └── requirements.txt
├── frontend/
│   ├── app/dashboard/            # Next.js pages
│   │   ├── meetings/             # Meeting list + detail + upload
│   │   ├── board/                # Execution board (Kanban)
│   │   ├── metrics/              # Analytics dashboard
│   │   ├── team/                 # Team management
│   │   └── settings/             # Integration settings
│   ├── components/
│   │   ├── dashboard/            # Feature components
│   │   │   ├── execution-board.tsx   # Drag-and-drop Kanban
│   │   │   ├── task-card.tsx         # Task card with status badges
│   │   │   ├── task-detail-panel.tsx # Slide-over detail panel
│   │   │   └── filter-sidebar.tsx    # Multi-criteria filter
│   │   ├── layout/               # App shell + sidebar
│   │   └── ui/                   # 17 shadcn/ui primitives
│   ├── lib/
│   │   ├── api.ts                # Axios API client (Clerk auth)
│   │   ├── store.ts              # Zustand state management
│   │   └── utils.ts              # Helpers
│   └── package.json
├── infrastructure/
│   ├── docker/
│   │   └── init-postgres.sql     # RLS policies + seed data
│   ├── k8s/                      # Kubernetes manifests (planned)
│   └── terraform/                # IaC (planned)
├── docker-compose.yml            # Full dev stack (12 services)
├── .env.example
└── .gitignore
```

## Key Features

### 1. AI-Powered Meeting Processing Pipeline
- **Upload** audio/video files (up to 500MB, supports mp3/wav/mp4/webm/m4a)
- **Automatic transcription** via Deepgram Nova-2 with speaker diarization
- **LangGraph extraction** pipeline: Chunking → LLM Extraction → Deduplication → Verification → Entity Resolution → Persistence
- **Anti-hallucination verification** — faithfulness, hallucination, and completeness scoring per task
- **Entity resolution** — maps "Sarah from engineering" → actual User via Neo4j graph + fuzzy matching
- **Deadline resolution** — parses "by Friday", "end of quarter", "in 2 weeks" into ISO dates
- **PII redaction** via Microsoft Presidio before storage

### 2. Execution Board (Kanban)
- Drag-and-drop task management with state machine validation
- Full lifecycle: `EXTRACTED → PENDING_REVIEW → VERIFIED → ASSIGNED → SYNCED → COMPLETED`
- Handles edge states: `SYNC_FAILED`, `CONFLICT`, `DISMISSED`
- Optimistic UI updates via TanStack Query
- Real-time sync via WebSocket

### 3. Meeting Context View
- Side-by-side transcript and extracted tasks
- Bi-directional linking — click task to jump to source quote in transcript
- Speaker identification with color coding
- Full-text search across transcripts

### 4. Bi-Directional Integrations
- **Outbound**: Push verified tasks to Jira, Asana, Linear, or post to Slack
- **Inbound**: Receive webhook status updates from external tools
- Adapter pattern — add new integrations by implementing `IntegrationPort`
- Webhook signature verification (HMAC-SHA256)

### 5. Multi-Tenant Architecture
- PostgreSQL Row-Level Security (RLS) for tenant isolation
- Tenant context set via middleware on every request
- Per-tenant Kafka event partitioning

### 6. Team Accountability Metrics
- Extraction accuracy trends (precision/recall/F1)
- Task completion funnel visualization
- AI audit log — every LLM decision is logged with token counts, latency, and raw output

## API Reference

### Meetings
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/meetings/upload` | Upload meeting audio + metadata |
| `GET` | `/api/v1/meetings` | List meetings (paginated, filterable) |
| `GET` | `/api/v1/meetings/{id}` | Get meeting with transcript + tasks |
| `PATCH` | `/api/v1/meetings/{id}` | Update meeting |
| `DELETE` | `/api/v1/meetings/{id}` | Delete meeting + audio |
| `POST` | `/api/v1/meetings/{id}/process` | Reprocess meeting |

### Tasks
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/tasks` | List tasks (filter by status, type, assignee, priority) |
| `GET` | `/api/v1/tasks/{id}` | Get task with audit log |
| `PATCH` | `/api/v1/tasks/{id}` | Update task (state machine validated) |
| `POST` | `/api/v1/tasks/{id}/verify` | Human-in-the-loop verification |
| `POST` | `/api/v1/tasks/{id}/assign` | Assign to user |
| `POST` | `/api/v1/tasks/{id}/dismiss` | Dismiss task |
| `POST` | `/api/v1/tasks/bulk-update` | Bulk update |
| `GET` | `/api/v1/tasks/{id}/audit-log` | Get state machine audit trail |

### Transcripts
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/transcripts/meeting/{id}` | Get transcript by meeting |
| `GET` | `/api/v1/transcripts/{id}/utterances` | Get diarized utterances |
| `GET` | `/api/v1/transcripts/{id}/span` | Get word-range segment |
| `GET` | `/api/v1/transcripts/{id}/search` | Full-text search |

### Integrations
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/integrations` | Create integration |
| `GET` | `/api/v1/integrations` | List integrations |
| `POST` | `/api/v1/integrations/{id}/test` | Test connection |
| `POST` | `/api/v1/integrations/webhooks/{provider}` | Receive webhook |

## Configuration

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `DEEPGRAM_API_KEY` | Deepgram Nova-2 ASR |
| `GROQ_API_KEY` | Groq API (Llama 3.3 70B) |
| `OPENAI_API_KEY` | OpenAI embeddings (text-embedding-3-large) |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis for Celery broker + cache |

### Optional Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NEO4J_URI` | Neo4j Bolt URI | `bolt://localhost:7687` |
| `QDRANT_URL` | Qdrant HTTP URL | `http://localhost:6333` |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka servers | `localhost:9092` |
| `CLERK_PUBLISHABLE_KEY` | Clerk auth | — |
| `EXTRACTION_MODEL` | LLM model for extraction | `llama-3.3-70b-versatile` |
| `CHUNK_SIZE` | Transcript chunk size (words) | `2000` |
| `VERIFICATION_FAITHFULNESS_THRESHOLD` | Min faithfulness score | `0.7` |
| `NAME_MATCH_THRESHOLD` | Fuzzy match threshold | `80` |

See [.env.example](.env.example) for the full list.

## Development

### Running Tests

```bash
cd backend
pytest tests/ -v
```

### Database Migrations

```bash
cd backend
prisma migrate dev --name migration_name
```

### Adding a New Integration

1. Create adapter class implementing `IntegrationPort` in `backend/app/integrations/`
2. Implement: `create_task()`, `update_task()`, `delete_task()`, `normalize_webhook()`, `verify_webhook_signature()`
3. Register in `backend/app/integrations/factory.py`:
   ```python
   IntegrationAdapterFactory.register("my_provider", MyAdapter)
   ```

## Production Deployment

### Required Infrastructure
- PostgreSQL 16+ with pgvector extension
- Qdrant (managed or self-hosted)
- Neo4j Enterprise 5.24+
- Kafka 3.8+ (MSK / Confluent Cloud)
- Redis 7+
- S3-compatible object storage

### Security Features
- TLS 1.3 for all connections
- Row-Level Security for multi-tenant isolation
- PII redaction at ingestion (Microsoft Presidio)
- JWT authentication via Clerk
- Webhook signature verification (HMAC-SHA256)
- AI audit logging for every LLM decision

## Cost Estimates (1,000 meetings/month)

| Service | Monthly Cost |
|---------|-------------|
| Deepgram Nova-2 | ~$1,500 |
| Groq (Llama 3.3 70B) | ~$35 |
| OpenAI (embeddings) | ~$20 |
| Infrastructure (DB, Kafka, etc.) | ~$1,300 |
| **Total** | **~$2,855/mo** |

## License

Proprietary — All rights reserved.

## Author

Built by [Shivam Kumar](https://github.com/shivam060404)