"""
Microsoft Teams Integration Adapter for PraxisFlow.
"""

import hmac
import hashlib
import logging
from typing import Dict, Any

from app.integrations.base import IntegrationPort, IntegrationConfig, NormalizedWebhookEvent
from app.schemas import Task

logger = logging.getLogger(__name__)


class TeamsAdapter(IntegrationPort):
    """Microsoft Teams integration adapter."""

    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        super().__init__()
        self._access_token: Optional[str] = None

    def _get_headers(self, config: IntegrationConfig) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token or config.config.get('access_token')}",
            "Content-Type": "application/json",
        }

    async def _get_access_token(self, config: IntegrationConfig) -> str:
        """Get Microsoft Graph access token."""
        tenant_id = config.config.get("tenant_id")
        client_id = config.config.get("client_id")
        client_secret = config.config.get("client_secret")

        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }

        response = await self._make_request(
            method="POST",
            url=token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            json=None,
        )
        # Use form data instead
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=data) as resp:
                token_data = await resp.json()
                return token_data.get("access_token")

    async def create_task(self, config: IntegrationConfig, task: Task) -> str:
        """Create a Teams task (Planner task)."""
        if not self._access_token:
            self._access_token = await self._get_access_token(config)

        plan_id = config.config.get("plan_id")
        bucket_id = config.config.get("bucket_id")

        payload = {
            "planId": plan_id,
            "bucketId": bucket_id,
            "title": task.title,
            "details": self._format_description(task),
        }

        if task.deadline_date:
            payload["dueDateTime"] = task.deadline_date.isoformat() + "Z"

        response = await self._make_request(
            method="POST",
            url=f"{self.BASE_URL}/planner/tasks",
            headers=self._get_headers(config),
            json=payload,
        )

        data = response.json()
        task_id = data["id"]
        logger.info(f"Created Teams Planner task {task_id} for task {task.id}")
        return task_id

    async def update_task(self, config: IntegrationConfig, task: Task) -> None:
        """Update a Teams Planner task."""
        if not task.external_id:
            return

        if not self._access_token:
            self._access_token = await self._get_access_token(config)

        # Get current task to get etag
        get_response = await self._make_request(
            method="GET",
            url=f"{self.BASE_URL}/planner/tasks/{task.external_id}",
            headers=self._get_headers(config),
        )
        current = get_response.json()
        etag = current.get("@odata.etag")

        payload = {
            "title": task.title,
            "details": self._format_description(task),
        }

        if task.deadline_date:
            payload["dueDateTime"] = task.deadline_date.isoformat() + "Z"

        headers = self._get_headers(config)
        headers["If-Match"] = etag

        response = await self._make_request(
            method="PATCH",
            url=f"{self.BASE_URL}/planner/tasks/{task.external_id}",
            headers=headers,
            json=payload,
        )
        logger.info(f"Updated Teams task {task.external_id}")

    async def delete_task(self, config: IntegrationConfig, external_id: str) -> None:
        """Delete a Teams Planner task."""
        if not self._access_token:
            self._access_token = await self._get_access_token(config)

        get_response = await self._make_request(
            method="GET",
            url=f"{self.BASE_URL}/planner/tasks/{external_id}",
            headers=self._get_headers(config),
        )
        current = get_response.json()
        etag = current.get("@odata.etag")

        headers = self._get_headers(config)
        headers["If-Match"] = etag

        await self._make_request(
            method="DELETE",
            url=f"{self.BASE_URL}/planner/tasks/{external_id}",
            headers=headers,
        )
        logger.info(f"Deleted Teams task {external_id}")

    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert Teams webhook to normalized event."""
        # Teams/Planner webhook format
        resource_data = payload.get("resourceData", {})
        return NormalizedWebhookEvent(
            external_id=resource_data.get("id"),
            external_url="",
            status="received",
            changed_at=datetime.utcnow(),
            raw_payload=payload,
        )

    async def verify_webhook_signature(
        self,
        config: IntegrationConfig,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify Teams webhook signature."""
        # Teams uses validation token for subscription verification
        # For actual webhooks, check the signature
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
        """Test Teams connection."""
        if not self._access_token:
            self._access_token = await self._get_access_token(config)

        response = await self._make_request(
            method="GET",
            url=f"{self.BASE_URL}/me",
            headers=self._get_headers(config),
        )
        user = response.json()
        return {"connected": True, "user": user.get("displayName")}