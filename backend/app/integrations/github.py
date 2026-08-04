"""
GitHub Integration Adapter for PraxisFlow.
"""

import hmac
import hashlib
import logging
from typing import Dict, Any

from app.integrations.base import IntegrationPort, IntegrationConfig, NormalizedWebhookEvent
from app.schemas import Task

logger = logging.getLogger(__name__)


class GitHubAdapter(IntegrationPort):
    """GitHub Issues integration adapter."""

    BASE_URL = "https://api.github.com"

    def __init__(self):
        super().__init__()

    def _get_headers(self, config: IntegrationConfig) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {config.config.get('access_token')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def create_task(self, config: IntegrationConfig, task: Task) -> str:
        """Create a GitHub issue."""
        owner = config.config.get("owner")
        repo = config.config.get("repo")

        labels = config.config.get("labels", ["meeting-intelligence", task.task_type.lower()])

        payload = {
            "title": task.title,
            "body": self._format_description(task),
            "labels": labels,
        }

        response = await self._make_request(
            method="POST",
            url=f"{self.BASE_URL}/repos/{owner}/{repo}/issues",
            headers=self._get_headers(config),
            json=payload,
        )

        data = response.json()
        issue_number = data["number"]
        logger.info(f"Created GitHub issue #{issue_number} for task {task.id}")
        return str(issue_number)

    async def update_task(self, config: IntegrationConfig, task: Task) -> None:
        """Update a GitHub issue."""
        if not task.external_id:
            return

        owner = config.config.get("owner")
        repo = config.config.get("repo")

        payload = {}

        if task.title:
            payload["title"] = task.title
        if task.description:
            payload["body"] = self._format_description(task)

        if payload:
            response = await self._make_request(
                method="PATCH",
                url=f"{self.BASE_URL}/repos/{owner}/{repo}/issues/{task.external_id}",
                headers=self._get_headers(config),
                json=payload,
            )
            logger.info(f"Updated GitHub issue #{task.external_id}")

    async def delete_task(self, config: IntegrationConfig, external_id: str) -> None:
        """Close a GitHub issue (GitHub doesn't allow deletion)."""
        owner = config.config.get("owner")
        repo = config.config.get("repo")

        payload = {"state": "closed"}

        response = await self._make_request(
            method="PATCH",
            url=f"{self.BASE_URL}/repos/{owner}/{repo}/issues/{external_id}",
            headers=self._get_headers(config),
            json=payload,
        )
        logger.info(f"Closed GitHub issue #{external_id}")

    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert GitHub webhook to normalized event."""
        issue = payload.get("issue", {})
        action = payload.get("action")

        status_map = {
            "opened": "todo",
            "reopened": "todo",
            "closed": "done",
        }

        return NormalizedWebhookEvent(
            external_id=str(issue.get("number")),
            external_url=issue.get("html_url"),
            status=status_map.get(action, "unknown"),
            changed_at=datetime.fromisoformat(issue.get("updated_at", "").replace("Z", "+00:00")),
            raw_payload=payload,
        )

    async def verify_webhook_signature(
        self,
        config: IntegrationConfig,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify GitHub webhook signature (X-Hub-Signature-256)."""
        secret = config.webhook_secret
        if not secret:
            return True

        # GitHub signature format: sha256=...
        try:
            sig_hash = signature.split("sha256=")[1]
            expected = hmac.new(
                secret.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(expected, sig_hash)
        except Exception:
            return False

    async def test_connection(self, config: IntegrationConfig) -> Dict[str, Any]:
        """Test GitHub connection."""
        response = await self._make_request(
            method="GET",
            url=f"{self.BASE_URL}/user",
            headers=self._get_headers(config),
        )
        user = response.json()
        return {"connected": True, "user": user.get("login")}