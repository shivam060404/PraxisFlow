"""
Salesforce Integration Adapter for PraxisFlow.
"""

import hmac
import hashlib
import logging
from typing import Dict, Any, Optional

from app.integrations.base import IntegrationPort, IntegrationConfig, NormalizedWebhookEvent
from app.schemas import Task

logger = logging.getLogger(__name__)


class SalesforceAdapter(IntegrationPort):
    """Salesforce integration adapter."""

    def __init__(self):
        super().__init__()
        self._instance_url: Optional[str] = None
        self._access_token: Optional[str] = None

    def _get_headers(self, config: IntegrationConfig) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token or config.config.get('access_token')}",
            "Content-Type": "application/json",
        }

    async def _authenticate(self, config: IntegrationConfig):
        """Authenticate with Salesforce using OAuth2."""
        if self._access_token and self._instance_url:
            return

        client_id = config.config.get("client_id")
        client_secret = config.config.get("client_secret")
        username = config.config.get("username")
        password = config.config.get("password")
        security_token = config.config.get("security_token")

        auth_url = "https://login.salesforce.com/services/oauth2/token"
        data = {
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password + security_token,
        }

        response = await self._make_request(
            method="POST",
            url=auth_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            json=None,
        )

        auth_data = response.json()
        self._access_token = auth_data.get("access_token")
        self._instance_url = auth_data.get("instance_url")

    async def create_task(self, config: IntegrationConfig, task: Task) -> str:
        """Create a Salesforce Task."""
        await self._authenticate(config)

        payload = {
            "Subject": task.title,
            "Description": self._format_description(task),
            "Type": "Meeting Action Item",
            "Status": "Not Started",
            "Priority": task.priority or "Normal",
        }

        if task.deadline_date:
            payload["ActivityDate"] = task.deadline_date.strftime("%Y-%m-%d")

        response = await self._make_request(
            method="POST",
            url=f"{self._instance_url}/services/data/v58.0/sobjects/Task",
            headers=self._get_headers(config),
            json=payload,
        )

        data = response.json()
        task_id = data["id"]
        logger.info(f"Created Salesforce Task {task_id} for task {task.id}")
        return task_id

    async def update_task(self, config: IntegrationConfig, task: Task) -> None:
        """Update a Salesforce Task."""
        if not task.external_id:
            return

        await self._authenticate(config)

        payload = {}

        if task.title:
            payload["Subject"] = task.title
        if task.description:
            payload["Description"] = self._format_description(task)
        if task.deadline_date:
            payload["ActivityDate"] = task.deadline_date.strftime("%Y-%m-%d")

        if payload:
            response = await self._make_request(
                method="PATCH",
                url=f"{self._instance_url}/services/data/v58.0/sobjects/Task/{task.external_id}",
                headers=self._get_headers(config),
                json=payload,
            )
            logger.info(f"Updated Salesforce Task {task.external_id}")

    async def delete_task(self, config: IntegrationConfig, external_id: str) -> None:
        """Delete a Salesforce Task."""
        await self._authenticate(config)

        await self._make_request(
            method="DELETE",
            url=f"{self._instance_url}/services/data/v58.0/sobjects/Task/{external_id}",
            headers=self._get_headers(config),
        )
        logger.info(f"Deleted Salesforce Task {external_id}")

    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert Salesforce webhook to normalized event."""
        # Salesforce Change Data Capture format
        event = payload.get("payload", {})

        status_map = {
            "Not Started": "todo",
            "In Progress": "in_progress",
            "Completed": "done",
            "Waiting on someone else": "blocked",
            "Deferred": "deferred",
        }

        return NormalizedWebhookEvent(
            external_id=event.get("Id"),
            external_url=f"{self._instance_url}/{event.get('Id')}",
            status=status_map.get(event.get("Status"), "unknown"),
            changed_at=datetime.fromisoformat(event.get("LastModifiedDate", "").replace("Z", "+00:00")),
            raw_payload=payload,
        )

    async def verify_webhook_signature(
        self,
        config: IntegrationConfig,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify Salesforce webhook signature."""
        # Salesforce uses certificate-based verification
        # For simplicity, check shared secret if configured
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
        """Test Salesforce connection."""
        await self._authenticate(config)

        response = await self._make_request(
            method="GET",
            url=f"{self._instance_url}/services/data/v58.0/sobjects/Task/describe",
            headers=self._get_headers(config),
        )
        return {"connected": True, "instance": self._instance_url}