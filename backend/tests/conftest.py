"""
Pytest configuration and fixtures for PraxisFlow tests.
"""

import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from uuid import uuid4

import fakeredis.aioredis
from prisma import Prisma

# ─── Test Configuration ───

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ─── Database Fixtures ───

@pytest.fixture(scope="session")
async def prisma_client() -> AsyncGenerator[Prisma, None]:
    """Create test database client."""
    client = Prisma()
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
async def clean_db(prisma_client: Prisma):
    """Clean database before each test."""
    # Delete in order to respect foreign keys
    await prisma_client.taskauditlog.delete_many()
    await prisma_client.task.delete_many()
    await prisma_client.meetingflag.delete_many()
    await prisma_client.aiauditlog.delete_many()
    await prisma_client.transcript.delete_many()
    await prisma_client.utterance.delete_many()
    await prisma_client.meeting.delete_many()
    await prisma_client.attendee.delete_many()
    await prisma_client.integration.delete_many()
    await prisma_client.user.delete_many()
    await prisma_client.tenant.delete_many()
    yield


# ─── Redis Fixtures ───

@pytest.fixture
async def fake_redis():
    """Create fake Redis for testing."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.close()


# ─── Mock Fixtures ───

@pytest.fixture
def mock_prisma():
    """Mock Prisma client."""
    mock = AsyncMock(spec=Prisma)
    return mock


@pytest.fixture
def mock_llm_gateway():
    """Mock LLM Gateway client."""
    mock = AsyncMock()
    mock.chat_completion = AsyncMock(return_value={
        "choices": [{"message": {"content": '{"tasks": []}', "role": "assistant"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        "model": "test-model",
    })
    mock.embeddings = AsyncMock(return_value={"data": [{"embedding": [0.1] * 3072}]})
    return mock


@pytest.fixture
def mock_deepgram():
    """Mock Deepgram ASR client."""
    mock = AsyncMock()
    mock.transcription.prerecorded = AsyncMock(return_value={
        "results": {
            "channels": [{
                "alternatives": [{
                    "transcript": "Test transcript",
                    "confidence": 0.95,
                    "words": [],
                }]
            }]
        }
    })
    return mock


@pytest.fixture
def mock_neo4j():
    """Mock Neo4j driver."""
    mock = AsyncMock()
    mock.session = AsyncMock()
    mock.session.__aenter__ = AsyncMock(return_value=mock.session)
    mock.session.__aexit__ = AsyncMock(return_value=None)
    mock.session.run = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_qdrant():
    """Mock Qdrant client."""
    mock = MagicMock()
    mock.search = MagicMock(return_value=[])
    mock.upsert = MagicMock(return_value=True)
    mock.delete = MagicMock(return_value=True)
    return mock


# ─── Test Data Fixtures ───

@pytest.fixture
def sample_tenant():
    return {
        "id": str(uuid4()),
        "name": "Test Tenant",
        "slug": "test-tenant",
        "plan": "starter",
        "status": "active",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }


@pytest.fixture
def sample_user(sample_tenant):
    return {
        "id": str(uuid4()),
        "tenantId": sample_tenant["id"],
        "email": "test@test.com",
        "fullName": "Test User",
        "role": "member",
        "clerkUserId": None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }


@pytest.fixture
def sample_meeting(sample_tenant, sample_user):
    return {
        "id": str(uuid4()),
        "tenantId": sample_tenant["id"],
        "title": "Test Meeting",
        "description": "A test meeting",
        "scheduledAt": datetime.utcnow(),
        "durationMinutes": 30,
        "status": "TRANSCRIBED",
        "audioUrl": None,
        "recordingSource": "upload",
        "calendarEventId": None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }


@pytest.fixture
def sample_task(sample_meeting, sample_user):
    return {
        "id": str(uuid4()),
        "tenantId": sample_meeting["tenantId"],
        "meetingId": sample_meeting["id"],
        "title": "Test Task",
        "description": "A test task",
        "taskType": "ACTION_ITEM",
        "status": "EXTRACTED",
        "priority": "MEDIUM",
        "assigneeHint": sample_user["fullName"],
        "assigneeId": sample_user["id"],
        "deadlineHint": "by Friday",
        "deadlineDate": None,
        "transcriptWordStart": 100,
        "transcriptWordEnd": 200,
        "sourceQuote": "We need to finish this by Friday",
        "verificationStatus": "VERIFIED",
        "verificationReasoning": "Confirmed",
        "extractionConfidence": 0.95,
        "externalId": None,
        "externalUrl": None,
        "integrationId": None,
        "lastSyncedAt": None,
        "syncStatus": None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
        "createdBy": "ai_agent",
    }


# ─── Mock LLM Responses ───

@pytest.fixture
def mock_extraction_response():
    return {
        "tasks": [
            {
                "task_type": "ACTION_ITEM",
                "title": "Finish report",
                "description": "Complete the quarterly report",
                "assignee_hint": "John",
                "deadline_hint": "by Friday",
                "priority_hint": "HIGH",
                "confidence": 0.92,
                "transcript_word_start": 100,
                "transcript_word_end": 120,
                "source_quote": "John, please finish the report by Friday",
            }
        ],
        "meeting_summary": "Team discussed quarterly report",
        "key_topics": ["reporting", "deadlines"],
    }


@pytest.fixture
def mock_verification_response():
    return {
        "faithfulness_score": 0.9,
        "hallucination_score": 0.05,
        "completeness_score": 0.85,
        "verdict": "PASS",
        "reasoning": "Task accurately reflects transcript",
    }


@pytest.fixture
def mock_entity_resolution_response():
    return {
        "assignee_id": "user-123",
        "assignee_name": "John Doe",
        "assignee_email": "john@company.com",
        "confidence": 0.9,
        "method": "participant_match",
        "candidates": [],
    }


# ─── Async Test Utilities ───

class AsyncContextManager:
    """Helper for mocking async context managers."""
    
    def __init__(self, return_value):
        self.return_value = return_value
    
    async def __aenter__(self):
        return self.return_value
    
    async def __aexit__(self, *args):
        pass


def async_mock_context(return_value):
    """Create async context manager mock."""
    return AsyncContextManager(return_value)


# ─── Patch Fixtures ───

@pytest.fixture(autouse=True)
def mock_settings():
    """Mock settings for tests."""
    with patch("app.core.config.settings") as mock:
        mock.ENVIRONMENT = "test"
        mock.DATABASE_URL = "postgresql://test:test@localhost:5432/test"
        mock.GROQ_API_KEY = "test-groq-key"
        mock.OPENAI_API_KEY = "test-openai-key"
        mock.DEEPGRAM_API_KEY = "test-deepgram-key"
        mock.JWT_SECRET = "test-secret"
        mock.NEO4J_URI = "bolt://localhost:7687"
        mock.NEO4J_USER = "neo4j"
        mock.NEO4J_PASSWORD = "test"
        mock.QDRANT_URL = "http://localhost:6333"
        mock.REDIS_URL = "redis://localhost:6379"
        mock.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
        mock.EXTRACTION_MODEL = "llama-3.3-70b-versatile"
        mock.VERIFICATION_MODEL = "llama-3.3-70b-versatile"
        mock.EMBEDDING_MODEL = "text-embedding-3-large"
        mock.CHUNK_SIZE = 2000
        mock.CHUNK_OVERLAP = 200
        yield mock


# ─── Test Markers ───

def pytest_configure(config):
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests")
    config.addinivalue_line("markers", "slow: Slow tests")
    config.addinivalue_line("markers", "security: Security tests")


# ─── Cleanup ───

@pytest.fixture(autouse=True)
async def cleanup_mocks():
    yield
    # Cleanup any global state
    pass