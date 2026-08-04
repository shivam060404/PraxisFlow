"""
Slack Integration Adapter for PraxisFlow.
"""

import hmac
import hashlib
import logging
from typing import Dict, Any

from app.integrations.base import IntegrationPort, IntegrationConfig, NormalizedWebhookEvent
from app.schemas import Task

logger = logging.getLogger(__name__)


class SlackAdapter(IntegrationPort):
    """Slack integration adapter for notifications."""

    BASE_URL = "https://slack.com/api"

    def __init__(self):
        super().__init__()

    def _get_headers(self, config: IntegrationConfig) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {config.config.get('bot_token')}",
            "Content-Type": "application/json",
        }

    async def create_task(self, config: IntegrationConfig, task: Task) -> str:
        """Post task as message to Slack channel."""
        blocks = self._format_slack_message(task)

        payload = {
            "channel": config.config.get("default_channel"),
            "blocks": blocks,
            "text": f"New task: {task.title}",
        }

        response = await self._make_request(
            method="POST",
            url=f"{self.BASE_URL}/chat.postMessage",
            headers=self._get_headers(config),
            json=payload,
        )

        data = response.json()
        if data.get("ok"):
            ts = data["ts"]
            logger.info(f"Posted task to Slack: {ts}")
            return ts

        raise Exception(f"Failed to post to Slack: {data}")

    async def update_task(self, config: IntegrationConfig, task: Task) -> None:
        """Update Slack message (post follow-up)."""
        # Slack doesn't support updating messages the same way
        # Could post a follow-up in thread
        pass

    async def delete_task(self, config: IntegrationConfig, external_id: str) -> None:
        """Delete Slack message."""
        # Would need channel_id and timestamp
        pass

    def _format_slack_message(self, task: Task) -> list:
        """Format task as Slack blocks."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📋 New {task.task_type.replace('_', ' ').title()}",
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Title:*\n{task.title}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Meeting:*\n{task.meeting_id[:8]}..."
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Description:*\n{task.description}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Confidence: {task.extraction_confidence:.0%} | Source: \"{task.source_quote[:100]}...\""
                    }
                ]
            }
        ]

        if task.assignee_hint:
            blocks.insert(2, {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Suggested Assignee:*\n{task.assignee_hint}"
                    }
                ]
            })

        if task.deadline_hint:
            blocks.insert(3, {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Suggested Deadline:*\n{task.deadline_hint}"
                    }
                ]
            })

        return blocks

    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert Slack event to normalized event."""
        event = payload.get("event", {})
        return NormalizedWebhookEvent(
            external_id=event.get("ts"),
            external_url="",
            status="received",
            changed_at=datetime.fromtimestamp(float(event.get("ts", 0))),
            raw_payload=payload,
        )

    async def verify_webhook_signature(
        self,
        config: IntegrationConfig,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify Slack webhook signature (X-Slack-Signature)."""
        secret = config.webhook_secret
        if not secret:
            return True

        # Slack signature format: v0=...
        try:
            timestamp = signature.split(",")[0].split("=")[1]
            sig_hash = signature.split("v0=")[1]

            basestring = f"v0:{timestamp}:{payload.decode()}"
            expected = hmac.new(
                secret.encode(),
                basestring.encode(),
                hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(f"v0={expected}", signature)
        except Exception:
            return False

    async def test_connection(self, config: IntegrationConfig) -> Dict[str, Any]:
        """Test Slack connection."""
        response = await self._make_request(
            method="POST",
            url=f"{self.BASE_URL}/auth.test",
            headers=self._get_headers(config),
        )
        data = response.json()
        return {"connected": data.get("ok"), "team": data.get("team")}