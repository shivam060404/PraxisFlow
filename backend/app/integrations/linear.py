"""
Linear Integration Adapter for PraxisFlow.
"""

import hmac
import hashlib
import logging
from typing import Dict, Any

from app.integrations.base import IntegrationPort, IntegrationConfig, NormalizedWebhookEvent
from app.schemas import Task

logger = logging.getLogger(__name__)


class LinearAdapter(IntegrationPort):
    """Linear integration adapter."""

    BASE_URL = "https://api.linear.app/graphql"

    def __init__(self):
        super().__init__()

    def _get_headers(self, config: IntegrationConfig) -> Dict[str, str]:
        return {
            "Authorization": config.config.get("api_key"),
            "Content-Type": "application/json",
        }

    async def _execute_query(
        self,
        config: IntegrationConfig,
        query: str,
        variables: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Execute GraphQL query."""
        response = await self._make_request(
            method="POST",
            url=self.BASE_URL,
            headers=self._get_headers(config),
            json={"query": query, "variables": variables or {}},
        )
        return response.json()

    async def create_task(self, config: IntegrationConfig, task: Task) -> str:
        """Create a Linear issue."""
        team_id = config.config.get("team_id")
        label_ids = config.config.get("label_ids", [])

        query = """
        mutation IssueCreate($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id
                    identifier
                }
            }
        }
        """

        variables = {
            "input": {
                "title": task.title,
                "description": self._format_description(task),
                "teamId": team_id,
                "labelIds": label_ids,
            }
        }

        if task.deadline_date:
            variables["input"]["dueDate"] = task.deadline_date.strftime("%Y-%m-%d")

        result = await self._execute_query(config, query, variables)

        if result.get("data", {}).get("issueCreate", {}).get("success"):
            issue = result["data"]["issueCreate"]["issue"]
            issue_id = issue["identifier"]  # e.g., "ENG-123"
            logger.info(f"Created Linear issue {issue_id} for task {task.id}")
            return issue_id

        raise Exception(f"Failed to create Linear issue: {result}")

    async def update_task(self, config: IntegrationConfig, task: Task) -> None:
        """Update a Linear issue."""
        if not task.external_id:
            return

        query = """
        mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
                issue {
                    id
                }
            }
        }
        """

        variables = {
            "id": task.external_id,
            "input": {}
        }

        if task.title:
            variables["input"]["title"] = task.title
        if task.description:
            variables["input"]["description"] = self._format_description(task)

        await self._execute_query(config, query, variables)
        logger.info(f"Updated Linear issue {task.external_id}")

    async def delete_task(self, config: IntegrationConfig, external_id: str) -> None:
        """Delete a Linear issue."""
        query = """
        mutation IssueDelete($id: String!) {
            issueDelete(id: $id) {
                success
            }
        }
        """
        await self._execute_query(config, query, {"id": external_id})
        logger.info(f"Deleted Linear issue {external_id}")

    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert Linear webhook to normalized event."""
        action = payload.get("action")
        data = payload.get("data", {})

        status_map = {
            "unstarted": "todo",
            "started": "in_progress",
            "completed": "done",
            "canceled": "cancelled",
        }

        return NormalizedWebhookEvent(
            external_id=data.get("identifier"),
            external_url=data.get("url"),
            status=status_map.get(data.get("state", {}).get("name", ""), "unknown"),
            changed_at=datetime.fromisoformat(payload.get("createdAt", "").replace("Z", "+00:00")),
            raw_payload=payload,
        )

    async def verify_webhook_signature(
        self,
        config: IntegrationConfig,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify Linear webhook signature."""
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
        """Test Linear connection."""
        query = "{ viewer { id name email } }"
        result = await self._execute_query(config, query)
        user = result.get("data", {}).get("viewer", {})
        return {"connected": True, "user": user.get("name")}