from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel


class NormalizedWebhookEvent(BaseModel):
    """Normalized webhook event from any integration."""
    external_id: str
    external_url: str
    status: str
    changed_at: datetime
    raw_payload: Dict[str, Any]


class IntegrationPort(ABC):
    """Abstract base class for integration adapters."""
    
    @abstractmethod
    async def create_task(self, integration: Any, task: Any) -> str:
        """Create task in external system. Return external ID."""
        pass
    
    @abstractmethod
    async def update_task(self, integration: Any, task: Any) -> None:
        """Update task in external system."""
        pass
    
    @abstractmethod
    async def delete_task(self, integration: Any, external_id: str) -> None:
        """Delete task in external system."""
        pass
    
    @abstractmethod
    def normalize_webhook(self, payload: Dict[str, Any]) -> NormalizedWebhookEvent:
        """Convert provider-specific webhook to canonical event."""
        pass
    
    @abstractmethod
    async def verify_webhook_signature(
        self,
        integration: Any,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify webhook authenticity."""
        pass
    
    async def test_connection(self, integration: Any) -> Dict[str, Any]:
        """Test integration connection."""
        return {"connected": False, "error": "Not implemented"}


class IntegrationAdapterFactory:
    """Factory for creating integration adapters."""
    
    _adapters: Dict[str, type] = {}
    
    @classmethod
    def register(cls, provider: str, adapter_class: type):
        """Register an adapter class for a provider."""
        cls._adapters[provider] = adapter_class
    
    @classmethod
    def get_adapter(cls, provider: str) -> IntegrationPort:
        """Get adapter instance for a provider."""
        if provider not in cls._adapters:
            raise ValueError(f"Unknown integration provider: {provider}")
        return cls._adapters[provider]()
    
    @classmethod
    def list_providers(cls) -> list:
        """List registered providers."""
        return list(cls._adapters.keys())


# Import and register adapters
from app.integrations.jira import JiraAdapter, AsanaAdapter, LinearAdapter, SlackAdapter

IntegrationAdapterFactory.register("jira", JiraAdapter)
IntegrationAdapterFactory.register("asana", AsanaAdapter)
IntegrationAdapterFactory.register("linear", LinearAdapter)
IntegrationAdapterFactory.register("slack", SlackAdapter)