# AI Meeting Intelligence & Action Command Center

An enterprise-grade agentic system that transforms passive meeting recordings into structured, trackable, and accountable execution workflows.

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Ingestion     │────▶│  AI Processing   │────▶│  Data & Memory  │
│   Layer         │     │  Engine          │     │  Layer          │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                        │
┌─────────────────┐     ┌──────────────────┐          │
│  Presentation   │◀────│  Application     │◀─────────┘
│  Layer          │     │  / API Layer     │
└─────────────────┘     └──────────────────┘
```

### Core Components

- **ASR Pipeline**: Deepgram Nova-2 with speaker diarization
- **Extraction Agent**: LangGraph multi-agent pipeline (Llama 3.3 70B via Groq)
- **Verification Agent**: Anti-hallucination guardrail (separate LLM pass)
- **Entity Resolution**: Neo4j graph + fuzzy matching for assignee mapping
- **Context Assembly**: LlamaIndex hybrid RAG (Qdrant + Neo4j + PostgreSQL)
- **Event Bus**: Kafka for async event-driven processing
- **Integrations**: Adapter pattern for Jira, Asana, Linear, Slack
- **Dashboard**: Next.js 15 + shadcn/ui with real-time WebSocket updates

## Quick Start

### Prerequisites

- Docker & Docker Compose
- API Keys: Deepgram, Groq, OpenAI
- (Optional) Clerk for authentication

### 1. Clone and Configure

```bash
cd ai-meeting-intelligence
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start Infrastructure

```bash
docker-compose up -d postgres qdrant neo4j kafka redis minio
```

### 3. Initialize Database

```bash
cd backend
pip install -r requirements.txt
prisma db push
```

### 4. Start Services

```bash
# Terminal 1: Backend API
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: Celery Worker
cd backend
celery -A app.workers.celery_app worker --loglevel=info

# Terminal 3: Frontend
cd frontend
npm install
npm run dev
```

### 5. Access

- **Frontend**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **Kafka UI**: http://localhost:8080
- **MinIO Console**: http://localhost:9001
- **Neo4j Browser**: http://localhost:7474

## Project Structure

```
ai-meeting-intelligence/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routes
│   │   ├── agents/           # LangGraph agents
│   │   ├── db/               # Prisma database
│   │   ├── integrations/     # External tool adapters
│   │   ├── schemas/          # Pydantic models
│   │   ├── services/         # Business logic
│   │   ├── workers/          # Celery tasks & Kafka consumers
│   │   └── main.py           # FastAPI app
│   ├── prisma/
│   │   └── schema.prisma     # Database schema
│   ├── requirements.txt
│   └── Dockerfile.dev
├── frontend/
│   ├── app/
│   │   ├── dashboard/        # Next.js pages
│   │   └── components/       # React components
│   ├── components/ui/        # shadcn/ui components
│   ├── lib/                  # Utilities & API client
│   └── package.json
├── infrastructure/
│   ├── docker/
│   ├── terraform/
│   └── k8s/
├── docker-compose.yml
└── .env.example
```

## Key Features

### 1. Meeting Processing Pipeline
- **Upload** audio/video files (up to 500MB)
- **Automatic transcription** with speaker diarization
- **AI extraction** of action items, decisions, follow-ups, blockers
- **Verification** to prevent hallucinations
- **Entity resolution** to map names to actual users

### 2. Execution Board (Kanban)
- Drag-and-drop task management
- Status workflow: Extracted → Verified → Assigned → Synced → Completed
- Real-time updates via WebSocket
- Bulk actions support

### 3. Meeting Context View
- Side-by-side transcript and extracted tasks
- Bi-directional linking (click task → jump to transcript)
- Speaker identification with color coding
- Search and filter transcript

### 4. Team Accountability Metrics
- Extraction accuracy trends (precision/recall/F1)
- Task completion funnel
- Individual and team performance

### 5. Bi-directional Integrations
- Push tasks to Jira/Asana/Linear
- Sync status updates back from external tools
- Conflict resolution

## API Endpoints

### Meetings
- `POST /api/v1/meetings/upload` - Upload meeting file
- `GET /api/v1/meetings` - List meetings
- `GET /api/v1/meetings/{id}` - Get meeting details
- `POST /api/v1/meetings/{id}/process` - Reprocess meeting

### Tasks
- `GET /api/v1/tasks` - List tasks with filters
- `GET /api/v1/tasks/{id}` - Get task details
- `PATCH /api/v1/tasks/{id}` - Update task
- `POST /api/v1/tasks/{id}/verify` - Verify task
- `POST /api/v1/tasks/{id}/assign` - Assign task
- `POST /api/v1/tasks/bulk-update` - Bulk update tasks

### Transcripts
- `GET /api/v1/transcripts/meeting/{meetingId}` - Get transcript
- `GET /api/v1/transcripts/{id}/utterances` - Get utterances
- `GET /api/v1/transcripts/{id}/span` - Get transcript segment
- `GET /api/v1/transcripts/{id}/search` - Search transcript

### Integrations
- `POST /api/v1/integrations` - Create integration
- `GET /api/v1/integrations` - List integrations
- `POST /api/v1/integrations/{id}/test` - Test connection

### Webhooks
- `POST /api/v1/integrations/webhooks/jira` - Jira webhook
- `POST /api/v1/integrations/webhooks/asana` - Asana webhook
- `POST /api/v1/integrations/webhooks/linear` - Linear webhook
- `POST /api/v1/integrations/webhooks/slack` - Slack webhook

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DEEPGRAM_API_KEY` | Deepgram Nova-2 API key | Yes |
| `GROQ_API_KEY` | Groq API key for Llama 3.3 70B | Yes |
| `OPENAI_API_KEY` | OpenAI API key for embeddings | Yes |
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `NEO4J_URI` | Neo4j Bolt URI | Yes |
| `NEO4J_PASSWORD` | Neo4j password | Yes |
| `QDRANT_URL` | Qdrant HTTP URL | Yes |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka bootstrap servers | Yes |
| `CLERK_PUBLISHABLE_KEY` | Clerk publishable key | No |
| `CLERK_SECRET_KEY` | Clerk secret key | No |

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

### Adding New Integration

1. Create adapter in `backend/app/integrations/{provider}.py`
2. Implement `IntegrationPort` interface
3. Register in `backend/app/integrations/factory.py`

## Production Deployment

### Kubernetes (Helm/Terraform)
See `infrastructure/k8s/` and `infrastructure/terraform/`

### Required Infrastructure
- PostgreSQL 16+ with pgvector
- Qdrant (managed or self-hosted)
- Neo4j Enterprise 5.24+
- Kafka 3.8+ (MSK/Confluent)
- Redis 7+
- Object storage (S3/MinIO)

### Security
- TLS 1.3 for all connections
- Row-level security for multi-tenancy
- PII redaction at ingestion
- Encrypted secrets via HashiCorp Vault
- Audit logging for all AI decisions

## Cost Estimates (1000 meetings/month)

| Service | Monthly Cost |
|---------|-------------|
| Deepgram Nova-2 | ~$1,500 |
| Groq (Llama 3.3 70B) | ~$35 |
| OpenAI (embeddings) | ~$20 |
| Infrastructure (DB, Kafka, etc.) | ~$1,300 |
| **Total** | **~$2,855/mo** |

## License

Proprietary - All rights reserved.

## Support

For issues and feature requests, please contact the engineering team.