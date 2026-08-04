"""
Base Integration Module for PraxisFlow.
Defines the integration adapter interface and common utilities.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass
from pydantic import BaseModel

import httpx


class NormalizedWebhookEvent(BaseModel):
    """Normalized webhook event from any integration."""
    external_id: str
    external_url: str
    status: str
    changed_at: datetime
    raw_payload: Dict[str, Any]


@dataclass
class IntegrationConfig:
    """Integration configuration."""
    provider: str
    display_name: str
    config: Dict[str, Any]
    webhook_secret: Optional[str] = None


class IntegrationPort(ABC):
    """Abstract base class for integration adapters."""

    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None

    @abstractmethod
    async def create_task(self, config: IntegrationConfig, task: Any) -> str:
        """Create task in external system. Return external ID."""
        pass

    @abstractmethod
    async def update_task(self, config: IntegrationConfig, task: Any) -> None:
        """Update task in external system."""
        pass

    @abstractmethod
    async def delete_task(self, config: IntegrationConfig, external_id: str) -> None:
        """Delete task in external system."""
        pass

    @abstractmethod
    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert provider-specific webhook to canonical event."""
        pass

    @abstractmethod
    async def verify_webhook_signature(
        self,
        config: IntegrationConfig,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify webhook authenticity."""
        pass

    async def test_connection(self, config: IntegrationConfig) -> Dict[str, Any]:
        """Test integration connection."""
        return {"connected": False, "error": "Not implemented"}

    async def get_rate_limits(self) -> Dict[str, Any]:
        """Get rate limit configuration."""
        return {
            "requests_per_minute": 60,
            "requests_per_hour": 1000,
        }

    def _format_description(self, task: Any) -> str:
        """Format task description for external system."""
        parts = [
            f"Source: Meeting Intelligence AI",
            f"Meeting: {task.meeting_id}",
            f"Type: {task.task_type}",
            f"Confidence: {task.extraction_confidence:.0%}",
            "",
            f"Original Quote:",
            f"{task.source_quote}",
            "",
            f"Description:",
            task.description,
        ]

        if task.assignee_hint:
            parts.insert(3, f"Suggested Assignee: {task.assignee_hint}")

        if task.deadline_hint:
            parts.insert(4, f"Suggested Deadline: {task.deadline_hint}")

        return "\n".join(parts)

    async def _make_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str] = None,
        json: Dict[str, Any] = None,
        params: Dict[str, Any] = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        """Make HTTP request with error handling."""
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=timeout)

        response = await self.client.request(
            method=method,
            url=url,
            headers=headers,
            json=json,
            params=params,
        )
        response.raise_for_status()
        return response

    async def close(self):
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None