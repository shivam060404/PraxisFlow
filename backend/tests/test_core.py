import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime

# Test fixtures
@pytest.fixture
def mock_db():
    """Mock Prisma database."""
    db = AsyncMock()
    return db


@pytest.fixture
def mock_settings():
    """Mock settings."""
    with patch("app.core.config.settings") as settings:
        settings.DEEPGRAM_API_KEY = "test_key"
        settings.GROQ_API_KEY = "test_key"
        settings.OPENAI_API_KEY = "test_key"
        settings.CHUNK_SIZE = 2000
        settings.CHUNK_OVERLAP = 200
        settings.EXTRACTION_MODEL = "llama-3.3-70b-versatile"
        settings.EXTRACTION_TEMPERATURE = 0.1
        settings.VERIFICATION_MODEL = "llama-3.3-70b-versatile"
        settings.VERIFICATION_TEMPERATURE = 0.0
        yield settings


class TestPIIRedaction:
    """Test PII redaction service."""
    
    def test_redact_email(self):
        from app.services.pii_redaction import redact_text
        
        text = "Contact John at john.doe@company.com for details."
        result = redact_text(text)
        
        assert result["has_redactions"] is True
        assert "[EMAIL]" in result["text"]
        assert "john.doe@company.com" not in result["text"]
    
    def test_redact_phone(self):
        from app.services.pii_redaction import redact_text
        
        text = "Call me at 555-123-4567 tomorrow."
        result = redact_text(text)
        
        assert result["has_redactions"] is True
        assert "[PHONE]" in result["text"]
    
    def test_redact_ssn(self):
        from app.services.pii_redaction import redact_text
        
        text = "My SSN is 123-45-6789."
        result = redact_text(text)
        
        assert result["has_redactions"] is True
        assert "[SSN]" in result["text"]
    
    def test_no_pii(self):
        from app.services.pii_redaction import redact_text
        
        text = "The meeting is scheduled for next Tuesday."
        result = redact_text(text)
        
        assert result["has_redactions"] is False
        assert result["text"] == text
    
    def test_redact_utterances(self):
        from app.services.pii_redaction import redact_utterances
        
        utterances = [
            {"speaker_label": "Speaker 0", "text": "Email me at test@example.com"},
            {"speaker_label": "Speaker 1", "text": "Will do!"},
        ]
        
        result = redact_utterances(utterances)
        
        assert result[0]["has_redactions"] is True
        assert "[EMAIL]" in result[0]["text"]
        assert result[1]["has_redactions"] is False


class TestExtractionSchemas:
    """Test extraction Pydantic schemas."""
    
    def test_extracted_task_schema(self):
        from app.agents.schemas import ExtractedTask
        
        task = ExtractedTask(
            task_type="ACTION_ITEM",
            title="Review budget",
            description="Review Q1 budget allocation",
            assignee_hint="Sarah from finance",
            deadline_hint="by Friday",
            priority_hint="HIGH",
            confidence=0.9,
            transcript_word_start=100,
            transcript_word_end=150,
            source_quote="Sarah, please review the Q1 budget by Friday",
        )
        
        assert task.task_type == "ACTION_ITEM"
        assert task.confidence == 0.9
        assert task.assignee_hint == "Sarah from finance"
    
    def test_extraction_result_schema(self):
        from app.agents.schemas import ExtractionResult, ExtractedTask
        
        tasks = [
            ExtractedTask(
                task_type="ACTION_ITEM",
                title="Task 1",
                description="Desc 1",
                confidence=0.8,
                transcript_word_start=0,
                transcript_word_end=10,
                source_quote="Quote 1",
            ),
            ExtractedTask(
                task_type="DECISION",
                title="Decision 1",
                description="Desc 2",
                confidence=0.9,
                transcript_word_start=20,
                transcript_word_end=30,
                source_quote="Quote 2",
            ),
        ]
        
        result = ExtractionResult(
            tasks=tasks,
            meeting_summary="Meeting about budget",
            key_topics=["budget", "finance"],
        )
        
        assert len(result.tasks) == 2
        assert result.meeting_summary == "Meeting about budget"
        assert "budget" in result.key_topics


class TestTaskStateMachine:
    """Test task state machine transitions."""
    
    def test_valid_transitions(self):
        from app.api.tasks import _is_valid_transition, TaskStatus
        
        # EXTRACTED -> VERIFIED
        assert _is_valid_transition(TaskStatus.EXTRACTED, TaskStatus.VERIFIED) is True
        
        # EXTRACTED -> PENDING_REVIEW
        assert _is_valid_transition(TaskStatus.EXTRACTED, TaskStatus.PENDING_REVIEW) is True
        
        # VERIFIED -> ASSIGNED
        assert _is_valid_transition(TaskStatus.VERIFIED, TaskStatus.ASSIGNED) is True
        
        # ASSIGNED -> SYNCED
        assert _is_valid_transition(TaskStatus.ASSIGNED, TaskStatus.SYNCED) is True
        
        # SYNCED -> COMPLETED
        assert _is_valid_transition(TaskStatus.SYNCED, TaskStatus.COMPLETED) is True
    
    def test_invalid_transitions(self):
        from app.api.tasks import _is_valid_transition, TaskStatus
        
        # Can't go backwards
        assert _is_valid_transition(TaskStatus.VERIFIED, TaskStatus.EXTRACTED) is False
        
        # Can't skip states
        assert _is_valid_transition(TaskStatus.EXTRACTED, TaskStatus.SYNCED) is False
        
        # COMPLETED is terminal
        assert _is_valid_transition(TaskStatus.COMPLETED, TaskStatus.VERIFIED) is False
        
        # DISMISSED is terminal
        assert _is_valid_transition(TaskStatus.DISMISSED, TaskStatus.VERIFIED) is False


class TestEntityResolution:
    """Test entity resolution."""
    
    @pytest.mark.asyncio
    async def test_extract_role_hint(self):
        from app.agents.entity_resolution import EntityResolutionAgent
        
        agent = EntityResolutionAgent()
        
        # Test various patterns
        assert agent._extract_role_hint("John from marketing") == "marketing"
        assert agent._extract_role_hint("Sarah in engineering") == "engineering"
        assert agent._extract_role_hint("Mike of sales") == "sales"
        assert agent._extract_role_hint("Team lead") is None
        assert agent._extract_role_hint("") is None


class TestChunking:
    """Test transcript chunking."""
    
    def test_chunk_transcript(self):
        from app.agents.extraction_graph import chunking_node
        from app.agents.schemas import ExtractionState, TranscriptChunk
        
        # Create state with transcript chunks
        state = ExtractionState(
            meeting_id="test_meeting",
            tenant_id="test_tenant",
            meeting_context="Test meeting",
            transcript_chunks=[
                TranscriptChunk(
                    index=0,
                    text=" ".join([f"word{i}" for i in range(100)]),
                    word_start=0,
                    word_end=99,
                    speakers=["Speaker 0"],
                ),
            ],
        )
        
        # Run chunking node
        new_state = asyncio.run(chunking_node(state))
        
        # Should create multiple chunks from 100 words
        assert len(new_state.transcript_chunks) > 0


class TestDeduplication:
    """Test task deduplication."""
    
    def test_duplicate_detection(self):
        from app.agents.extraction_graph import _tasks_similar
        from app.agents.schemas import ExtractedTask
        
        task1 = ExtractedTask(
            task_type="ACTION_ITEM",
            title="Review budget",
            description="Review Q1 budget",
            confidence=0.8,
            transcript_word_start=0,
            transcript_word_end=10,
            source_quote="Review the budget",
        )
        
        task2 = ExtractedTask(
            task_type="ACTION_ITEM",
            title="Review the budget",
            description="Review Q1 budget allocation",
            confidence=0.9,
            transcript_word_start=20,
            transcript_word_end=30,
            source_quote="Review the budget please",
        )
        
        # These should be detected as similar
        assert _tasks_similar(task1, task2) is True
        
        # Different tasks
        task3 = ExtractedTask(
            task_type="DECISION",
            title="Approve budget",
            description="Approve Q1 budget",
            confidence=0.8,
            transcript_word_start=0,
            transcript_word_end=10,
            source_quote="Approve the budget",
        )
        
        assert _tasks_similar(task1, task3) is False


class TestIntegrationAdapters:
    """Test integration adapter factory."""
    
    def test_factory_registration(self):
        from app.integrations.factory import IntegrationAdapterFactory
        
        providers = IntegrationAdapterFactory.list_providers()
        assert "jira" in providers
        assert "asana" in providers
        assert "linear" in providers
        assert "slack" in providers
    
    def test_get_adapter(self):
        from app.integrations.factory import IntegrationAdapterFactory
        
        jira_adapter = IntegrationAdapterFactory.get_adapter("jira")
        assert jira_adapter is not None
        
        asana_adapter = IntegrationAdapterFactory.get_adapter("asana")
        assert asana_adapter is not None
        
        linear_adapter = IntegrationAdapterFactory.get_adapter("linear")
        assert linear_adapter is not None
        
        slack_adapter = IntegrationAdapterFactory.get_adapter("slack")
        assert slack_adapter is not None
    
    def test_unknown_provider(self):
        from app.integrations.factory import IntegrationAdapterFactory
        
        with pytest.raises(ValueError):
            IntegrationAdapterFactory.get_adapter("unknown")


class TestKafkaEvents:
    """Test Kafka event builders."""
    
    def test_meeting_uploaded_event(self):
        from app.services.kafka_events import EventBuilder
        
        event = EventBuilder.meeting_uploaded(
            meeting_id="meet_123",
            tenant_id="tenant_456",
            audio_url="s3://bucket/audio.mp3"
        )
        
        assert event["event_type"] == "meeting.uploaded"
        assert event["meeting_id"] == "meet_123"
        assert event["tenant_id"] == "tenant_456"
        assert event["audio_url"] == "s3://bucket/audio.mp3"
        assert "timestamp" in event
    
    def test_transcript_completed_event(self):
        from app.services.kafka_events import EventBuilder
        
        event = EventBuilder.transcript_completed(
            meeting_id="meet_123",
            transcript_id="trans_456",
            tenant_id="tenant_789",
            word_count=1500
        )
        
        assert event["event_type"] == "transcript.completed"
        assert event["word_count"] == 1500
    
    def test_task_verified_event(self):
        from app.services.kafka_events import EventBuilder
        
        event = EventBuilder.task_verified(
            task_id="task_123",
            tenant_id="tenant_456",
            status="VERIFIED",
            reasoning="High confidence extraction"
        )
        
        assert event["event_type"] == "task.verified"
        assert event["verification_status"] == "VERIFIED"
        assert event["reasoning"] == "High confidence extraction"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])