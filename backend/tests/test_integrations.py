import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Test fixtures
@pytest.fixture
def mock_integration():
    """Mock integration object."""
    return MagicMock(
        id="int_123",
        tenant_id="tenant_123",
        provider="jira",
        display_name="Test Jira",
        config={
            "base_url": "https://test.atlassian.net",
            "email": "test@company.com",
            "api_token": "test_token",
            "project_key": "PROJ",
            "issue_type": "Task",
        },
        status="ACTIVE",
        webhook_secret="test_secret",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@pytest.fixture
def mock_task():
    """Mock task object."""
    return MagicMock(
        id="task_123",
        tenant_id="tenant_123",
        meeting_id="meet_123",
        title="Test Task",
        description="Test task description",
        task_type="ACTION_ITEM",
        status="VERIFIED",
        priority="HIGH",
        assignee_hint="John from engineering",
        assignee_id=None,
        deadline_hint="by Friday",
        deadline_date=None,
        transcript_word_start=100,
        transcript_word_end=150,
        source_quote="John, please test this by Friday",
        extraction_confidence=0.9,
        verification_status="VERIFIED",
        external_id=None,
        external_url=None,
        integration_id=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


class TestJiraAdapter:
    """Test Jira adapter."""
    
    def test_format_description(self):
        from app.integrations.jira import JiraAdapter
        
        adapter = JiraAdapter()
        task = MagicMock(
            meeting_id="meet_123",
            task_type="ACTION_ITEM",
            extraction_confidence=0.9,
            source_quote="Test quote",
            description="Test description",
            assignee_hint="John from engineering",
            deadline_hint="by Friday",
        )
        
        description = adapter._format_description(task)
        
        assert "Meeting Intelligence AI" in description
        assert "meet_123" in description
        assert "ACTION_ITEM" in description
        assert "90%" in description
        assert "Test quote" in description
        assert "Test description" in description
        assert "John from engineering" in description
        assert "by Friday" in description
    
    def test_normalize_webhook(self):
        from app.integrations.jira import JiraAdapter
        
        adapter = JiraAdapter()
        adapter.base_url = "https://test.atlassian.net"
        
        payload = {
            "issue": {
                "key": "PROJ-123",
                "fields": {
                    "status": {"name": "Done"}
                }
            },
            "changelog": {
                "items": [
                    {"field": "status", "toString": "Done"}
                ]
            },
            "timestamp": "2024-01-15T10:00:00Z"
        }
        
        normalized = adapter.normalize_webhook(payload)
        
        assert normalized.external_id == "PROJ-123"
        assert normalized.status == "done"
        assert "https://test.atlassian.net/browse/PROJ-123" in normalized.external_url
    
    def test_normalize_webhook_in_progress(self):
        from app.integrations.jira import JiraAdapter
        
        adapter = JiraAdapter()
        
        payload = {
            "issue": {
                "key": "PROJ-456",
                "fields": {
                    "status": {"name": "In Progress"}
                }
            },
            "changelog": {"items": []},
            "timestamp": "2024-01-15T10:00:00Z"
        }
        
        normalized = adapter.normalize_webhook(payload)
        
        assert normalized.external_id == "PROJ-456"
        assert normalized.status == "in_progress"


class TestAsanaAdapter:
    """Test Asana adapter."""
    
    def test_format_description(self):
        from app.integrations.jira import AsanaAdapter
        
        adapter = AsanaAdapter()
        task = MagicMock(
            meeting_id="meet_123",
            task_type="ACTION_ITEM",
            extraction_confidence=0.9,
            source_quote="Test quote",
            description="Test description",
            assignee_hint="John from engineering",
            deadline_hint="by Friday",
        )
        
        description = adapter._format_description(task)
        
        assert "Meeting Intelligence AI" in description
        assert "meet_123" in description
        assert "ACTION_ITEM" in description
        assert "90%" in description
        assert "Test quote" in description
        assert "Test description" in description
    
    def test_normalize_webhook(self):
        from app.integrations.jira import AsanaAdapter
        
        adapter = AsanaAdapter()
        
        payload = {
            "events": [
                {
                    "resource": {"gid": "123456"},
                    "action": "changed"
                }
            ]
        }
        
        normalized = adapter.normalize_webhook(payload)
        
        assert normalized.external_id == "123456"
        assert "asana.com" in normalized.external_url


class TestLinearAdapter:
    """Test Linear adapter."""
    
    def test_format_description(self):
        from app.integrations.jira import LinearAdapter
        
        adapter = LinearAdapter()
        task = MagicMock(
            meeting_id="meet_123",
            task_type="ACTION_ITEM",
            extraction_confidence=0.9,
            source_quote="Test quote",
            description="Test description",
            assignee_hint="John from engineering",
            deadline_hint="by Friday",
        )
        
        description = adapter._format_description(task)
        
        assert "Meeting Intelligence AI" in description
        assert "meet_123" in description
        assert "ACTION_ITEM" in description
        assert "90%" in description
        assert "> Test quote" in description
        assert "Test description" in description
    
    def test_normalize_webhook(self):
        from app.integrations.jira import LinearAdapter
        
        adapter = LinearAdapter()
        
        payload = {
            "action": "update",
            "data": {
                "identifier": "ENG-123",
                "url": "https://linear.app/issue/ENG-123",
                "state": {"name": "Completed"}
            },
            "createdAt": "2024-01-15T10:00:00Z"
        }
        
        normalized = adapter.normalize_webhook(payload)
        
        assert normalized.external_id == "ENG-123"
        assert normalized.status == "done"
        assert normalized.external_url == "https://linear.app/issue/ENG-123"


class TestSlackAdapter:
    """Test Slack adapter."""
    
    def test_format_slack_message(self):
        from app.integrations.jira import SlackAdapter
        
        adapter = SlackAdapter()
        task = MagicMock(
            task_type="ACTION_ITEM",
            title="Test Task",
            meeting_id="meet_123",
            description="Test description",
            assignee_hint="John from engineering",
            deadline_hint="by Friday",
            extraction_confidence=0.9,
            source_quote="Test quote",
        )
        
        blocks = adapter._format_slack_message(task)
        
        assert len(blocks) > 0
        # Check header block
        assert blocks[0]["type"] == "header"
        assert "ACTION_ITEM" in blocks[0]["text"]["text"]
        # Check section with title
        section_blocks = [b for b in blocks if b["type"] == "section"]
        assert len(section_blocks) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])