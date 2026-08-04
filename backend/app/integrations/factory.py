"""
Integration Adapter Factory for PraxisFlow.
Registers and provides integration adapters.
"""

from typing import Dict, Any, Optional
from app.integrations.base import IntegrationPort, IntegrationConfig


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

    @classmethod
    async def create_task(cls, provider: str, config: IntegrationConfig, task: Any) -> str:
        """Create task using provider adapter."""
        adapter = cls.get_adapter(provider)
        return await adapter.create_task(config, task)

    @classmethod
    async def update_task(cls, provider: str, config: IntegrationConfig, task: Any) -> None:
        """Update task using provider adapter."""
        adapter = cls.get_adapter(provider)
        return await adapter.update_task(config, task)

    @classmethod
    async def delete_task(cls, provider: str, config: IntegrationConfig, external_id: str) -> None:
        """Delete task using provider adapter."""
        adapter = cls.get_adapter(provider)
        return await adapter.delete_task(config, external_id)

    @classmethod
    def normalize_webhook(cls, provider: str, payload: Dict[str, Any]) -> Any:
        """Normalize webhook using provider adapter."""
        adapter = cls.get_adapter(provider)
        return adapter.normalize_webhook(payload)

    @classmethod
    async def verify_webhook(cls, provider: str, config: IntegrationConfig, payload: bytes, signature: str) -> bool:
        """Verify webhook using provider adapter."""
        adapter = cls.get_adapter(provider)
        return await adapter.verify_webhook_signature(config, payload, signature)

    @classmethod
    async def test_connection(cls, provider: str, config: IntegrationConfig) -> Dict[str, Any]:
        """Test connection using provider adapter."""
        adapter = cls.get_adapter(provider)
        return await adapter.test_connection(config)


# Import and register adapters
from app.integrations.jira import JiraAdapter
from app.integrations.asana import AsanaAdapter
from app.integrations.linear import LinearAdapter
from app.integrations.slack import SlackAdapter
from app.integrations.teams import TeamsAdapter
from app.integrations.github import GitHubAdapter
from app.integrations.salesforce import SalesforceAdapter
from app.integrations.notion import NotionAdapter

IntegrationAdapterFactory.register("jira", JiraAdapter)
IntegrationAdapterFactory.register("asana", AsanaAdapter)
IntegrationAdapterFactory.register("linear", LinearAdapter)
IntegrationAdapterFactory.register("slack", SlackAdapter)
IntegrationAdapterFactory.register("teams", TeamsAdapter)
IntegrationAdapterFactory.register("github", GitHubAdapter)
IntegrationAdapterFactory.register("salesforce", SalesforceAdapter)
IntegrationAdapterFactory.register("notion", NotionAdapter)