"""
Asana Integration Adapter for PraxisFlow.
"""

import hmac
import hashlib
import logging
from typing import Dict, Any, Optional

from app.integrations.base import IntegrationPort, IntegrationConfig, NormalizedWebhookEvent
from app.schemas import Task

logger = logging.getLogger(__name__)


class AsanaAdapter(IntegrationPort):
    """Asana integration adapter."""

    BASE_URL = "https://app.asana.com/api/1.0"

    def __init__(self):
        super().__init__()

    def _get_headers(self, config: IntegrationConfig) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {config.config.get('access_token')}",
            "Accept": "application/json",
        }

    async def create_task(self, config: IntegrationConfig, task: Task) -> str:
        """Create an Asana task."""
        project_gid = config.config.get("project_gid")
        workspace_gid = config.config.get("workspace_gid")

        payload = {
            "data": {
                "name": task.title,
                "notes": self._format_description(task),
                "projects": [project_gid] if project_gid else [],
                "workspace": workspace_gid,
                "tags": ["meeting-intelligence", task.task_type.lower()],
            }
        }

        if task.deadline_date:
            payload["data"]["due_on"] = task.deadline_date.strftime("%Y-%m-%d")

        response = await self._make_request(
            method="POST",
            url=f"{self.BASE_URL}/tasks",
            headers=self._get_headers(config),
            json=payload,
        )

        data = response.json()
        task_gid = data["data"]["gid"]
        logger.info(f"Created Asana task {task_gid} for task {task.id}")
        return task_gid

    async def update_task(self, config: IntegrationConfig, task: Task) -> None:
        """Update an Asana task."""
        if not task.external_id:
            return

        payload = {"data": {}}

        if task.title:
            payload["data"]["name"] = task.title
        if task.description:
            payload["data"]["notes"] = self._format_description(task)
        if task.deadline_date:
            payload["data"]["due_on"] = task.deadline_date.strftime("%Y-%m-%d")

        if payload["data"]:
            response = await self._make_request(
                method="PUT",
                url=f"{self.BASE_URL}/tasks/{task.external_id}",
                headers=self._get_headers(config),
                json=payload,
            )
            logger.info(f"Updated Asana task {task.external_id}")

    async def delete_task(self, config: IntegrationConfig, external_id: str) -> None:
        """Delete an Asana task."""
        response = await self._make_request(
            method="DELETE",
            url=f"{self.BASE_URL}/tasks/{external_id}",
            headers=self._get_headers(config),
        )
        logger.info(f"Deleted Asana task {external_id}")

    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert Asana webhook to normalized event."""
        events = payload.get("events", [])
        event = events[0] if events else {}
        resource = event.get("resource", {})

        status_map = {
            "incomplete": "todo",
            "complete": "done",
        }

        return NormalizedWebhookEvent(
            external_id=resource.get("gid"),
            external_url=f"https://app.asana.com/0/{resource.get('gid')}",
            status=status_map.get("incomplete", "unknown"),
            changed_at=datetime.utcnow(),
            raw_payload=payload,
        )

    async def verify_webhook_signature(
        self,
        config: IntegrationConfig,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify Asana webhook signature (X-Hook-Signature)."""
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
        """Test Asana connection."""
        response = await self._make_request(
            method="GET",
            url=f"{self.BASE_URL}/users/me",
            headers=self._get_headers(config),
        )
        user = response.json()
        return {"connected": True, "user": user["data"]["name"]}