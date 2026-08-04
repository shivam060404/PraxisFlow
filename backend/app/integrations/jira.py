"""
Jira Integration Adapter for PraxisFlow.
"""

import logging
from typing import Dict, Any, Optional

import httpx

from app.integrations.base import IntegrationPort, IntegrationConfig, NormalizedWebhookEvent
from app.schemas import Task

logger = logging.getLogger(__name__)


class JiraAdapter(IntegrationPort):
    """Jira Cloud integration adapter."""

    def __init__(self):
        super().__init__()
        self.base_url: Optional[str] = None
        self.project_key: Optional[str] = None
        self.issue_type: str = "Task"

    def _get_client(self, config: IntegrationConfig) -> httpx.AsyncClient:
        """Create authenticated HTTP client."""
        self.base_url = config.config.get("base_url", "").rstrip("/")
        self.project_key = config.config.get("project_key")
        self.issue_type = config.config.get("issue_type", "Task")

        email = config.config.get("email")
        api_token = config.config.get("api_token")

        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=(email, api_token),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def create_task(self, config: IntegrationConfig, task: Task) -> str:
        """Create a Jira issue."""
        async with self._get_client(config) as client:
            description = self._format_description(task)

            payload = {
                "fields": {
                    "project": {"key": self.project_key},
                    "summary": task.title,
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": description}
                                ]
                            }
                        ]
                    },
                    "issuetype": {"name": self.issue_type},
                    "labels": [
                        "meeting-intelligence",
                        f"meeting-{task.meeting_id[:8]}",
                        task.task_type.lower(),
                    ],
                }
            }

            if task.deadline_date:
                payload["fields"]["duedate"] = task.deadline_date.strftime("%Y-%m-%d")

            response = await client.post("/rest/api/3/issue", json=payload)
            response.raise_for_status()

            data = response.json()
            issue_key = data["key"]

            logger.info(f"Created Jira issue {issue_key} for task {task.id}")
            return issue_key

    async def update_task(self, config: IntegrationConfig, task: Task) -> None:
        """Update a Jira issue."""
        if not task.external_id:
            return

        async with self._get_client(config) as client:
            payload = {"fields": {}}

            if task.title:
                payload["fields"]["summary"] = task.title

            if task.description:
                payload["fields"]["description"] = {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": self._format_description(task)}
                            ]
                        }
                    ]
                }

            if task.deadline_date:
                payload["fields"]["duedate"] = task.deadline_date.strftime("%Y-%m-%d")

            if payload["fields"]:
                response = await client.put(
                    f"/rest/api/3/issue/{task.external_id}",
                    json=payload
                )
                response.raise_for_status()
                logger.info(f"Updated Jira issue {task.external_id}")

    async def delete_task(self, config: IntegrationConfig, external_id: str) -> None:
        """Delete a Jira issue (move to trash)."""
        async with self._get_client(config) as client:
            response = await client.delete(f"/rest/api/3/issue/{external_id}")
            response.raise_for_status()
            logger.info(f"Deleted Jira issue {external_id}")

    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert Jira webhook to normalized event."""
        issue = payload.get("issue", {})
        changelog = payload.get("changelog", {})
        items = changelog.get("items", [])

        status_change = next(
            (item for item in items if item.get("field") == "status"),
            None
        )

        status_map = {
            "To Do": "todo",
            "In Progress": "in_progress",
            "In Review": "in_review",
            "Done": "done",
            "Closed": "done",
            "Resolved": "done",
        }

        new_status = "unknown"
        if status_change:
            new_status = status_map.get(status_change.get("toString", ""), "unknown")
        elif issue.get("fields", {}).get("status", {}).get("name"):
            new_status = status_map.get(issue["fields"]["status"]["name"], "unknown")

        return NormalizedWebhookEvent(
            external_id=issue.get("key"),
            external_url=f"{self.base_url}/browse/{issue.get('key')}" if self.base_url else "",
            status=new_status,
            changed_at=datetime.fromisoformat(payload.get("timestamp", "").replace("Z", "+00:00")),
            raw_payload=payload,
        )

    async def verify_webhook_signature(
        self,
        config: IntegrationConfig,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify Jira webhook signature."""
        # Jira webhooks can be configured with a secret
        # For now, return True (implement HMAC verification if secret configured)
        return True

    async def test_connection(self, config: IntegrationConfig) -> Dict[str, Any]:
        """Test Jira connection."""
        async with self._get_client(config) as client:
            response = await client.get("/rest/api/3/myself")
            response.raise_for_status()
            user = response.json()
            return {
                "connected": True,
                "user": user.get("displayName"),
                "email": user.get("emailAddress"),
            }