"""
Notion Integration Adapter for PraxisFlow.
"""

import hmac
import hashlib
import logging
from typing import Dict, Any

from app.integrations.base import IntegrationPort, IntegrationConfig, NormalizedWebhookEvent
from app.schemas import Task

logger = logging.getLogger(__name__)


class NotionAdapter(IntegrationPort):
    """Notion integration adapter."""

    BASE_URL = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"

    def __init__(self):
        super().__init__()

    def _get_headers(self, config: IntegrationConfig) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {config.config.get('access_token')}",
            "Content-Type": "application/json",
            "Notion-Version": self.NOTION_VERSION,
        }

    async def create_task(self, config: IntegrationConfig, task: Task) -> str:
        """Create a Notion page in a database."""
        database_id = config.config.get("database_id")

        # Build properties based on database schema
        properties = {
            "Title": {
                "title": [
                    {
                        "text": {
                            "content": task.title
                        }
                    }
                ]
            },
            "Meeting ID": {
                "rich_text": [
                    {
                        "text": {
                            "content": task.meeting_id
                        }
                    }
                ]
            },
            "Type": {
                "select": {
                    "name": task.task_type.replace("_", " ").title()
                }
            },
            "Confidence": {
                "number": task.extraction_confidence
            },
        }

        if task.priority:
            properties["Priority"] = {
                "select": {
                    "name": task.priority
                }
            }

        if task.deadline_date:
            properties["Deadline"] = {
                "date": {
                    "start": task.deadline_date.strftime("%Y-%m-%d")
                }
            }

        if task.assignee_hint:
            properties["Suggested Assignee"] = {
                "rich_text": [
                    {
                        "text": {
                            "content": task.assignee_hint
                        }
                    }
                ]
            }

        # Build page content
        children = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Source Quote"}}]
                }
            },
            {
                "object": "block",
                "type": "quote",
                "quote": {
                    "rich_text": [{"type": "text", "text": {"content": task.source_quote}}]
                }
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Description"}}]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": task.description}}]
                }
            },
        ]

        payload = {
            "parent": {"database_id": database_id},
            "properties": properties,
            "children": children,
        }

        response = await self._make_request(
            method="POST",
            url=f"{self.BASE_URL}/pages",
            headers=self._get_headers(config),
            json=payload,
        )

        data = response.json()
        page_id = data["id"]
        logger.info(f"Created Notion page {page_id} for task {task.id}")
        return page_id

    async def update_task(self, config: IntegrationConfig, task: Task) -> None:
        """Update a Notion page."""
        if not task.external_id:
            return

        properties = {}

        if task.title:
            properties["Title"] = {
                "title": [{"text": {"content": task.title}}]
            }

        if task.deadline_date:
            properties["Deadline"] = {
                "date": {"start": task.deadline_date.strftime("%Y-%m-%d")}
            }

        if task.priority:
            properties["Priority"] = {
                "select": {"name": task.priority}
            }

        if properties:
            response = await self._make_request(
                method="PATCH",
                url=f"{self.BASE_URL}/pages/{task.external_id}",
                headers=self._get_headers(config),
                json={"properties": properties},
            )
            logger.info(f"Updated Notion page {task.external_id}")

    async def delete_task(self, config: IntegrationConfig, external_id: str) -> None:
        """Archive a Notion page (Notion doesn't allow deletion)."""
        response = await self._make_request(
            method="PATCH",
            url=f"{self.BASE_URL}/pages/{external_id}",
            headers=self._get_headers(config),
            json={"archived": True},
        )
        logger.info(f"Archived Notion page {external_id}")

    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert Notion webhook to normalized event."""
        # Notion webhook format (via Make/Zapier or custom webhook)
        event = payload.get("event", {})
        data = event.get("data", {})

        status_map = {
            "Not started": "todo",
            "In progress": "in_progress",
            "Done": "done",
        }

        # Extract properties
        properties = data.get("properties", {})
        status_prop = properties.get("Status", {})
        status = "unknown"
        if status_prop.get("select"):
            status = status_map.get(status_prop["select"].get("name", ""), "unknown")

        return NormalizedWebhookEvent(
            external_id=data.get("id"),
            external_url=data.get("url"),
            status=status,
            changed_at=datetime.fromisoformat(data.get("last_edited_time", "").replace("Z", "+00:00")),
            raw_payload=payload,
        )

    async def verify_webhook_signature(
        self,
        config: IntegrationConfig,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify Notion webhook signature."""
        secret = config.webhook_secret
        if not secret:
            return True

        expected = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    async def test_connection(self, config: IntegrationConfig) -> Dict[str, Any]:
        """Test Notion connection."""
        response = await self._make_request(
            method="GET",
            url=f"{self.BASE_URL}/users/me",
            headers=self._get_headers(config),
        )
        user = response.json()
        return {"connected": True, "user": user.get("name")}