"""
Model Routing for LLM Gateway.
Handles primary/fallback model selection per pipeline node.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import yaml
from pathlib import Path

from app.core.config import settings


@dataclass
class RoutingPolicy:
    """Routing policy for a pipeline node."""
    primary: str
    fallback: List[str] = field(default_factory=list)
    max_tokens: int = 4096
    temperature: float = 0.1
    timeout_ms: int = 30000
    retry: int = 2


class ModelRouter:
    """
    Manages model routing policies for different pipeline nodes.
    Supports configuration via YAML and environment overrides.
    """

    DEFAULT_POLICIES = {
        "extraction": RoutingPolicy(
            primary="groq/llama-3.3-70b-versatile",
            fallback=["openai/gpt-4o", "anthropic/claude-sonnet-4-20250514"],
            max_tokens=4096,
            temperature=0.1,
            timeout_ms=30000,
        ),
        "verification": RoutingPolicy(
            primary="openai/gpt-4o",
            fallback=["anthropic/claude-sonnet-4-20250514"],
            max_tokens=2048,
            temperature=0.0,
            timeout_ms=20000,
        ),
        "entity_resolution": RoutingPolicy(
            primary="groq/llama-3.3-70b-versatile",
            fallback=["openai/gpt-4o-mini"],
            max_tokens=1024,
            temperature=0.0,
            timeout_ms=15000,
        ),
        "deduplication": RoutingPolicy(
            primary="groq/llama-3.3-70b-versatile",
            fallback=["openai/gpt-4o"],
            max_tokens=4096,
            temperature=0.0,
            timeout_ms=20000,
        ),
        "conflict_resolution": RoutingPolicy(
            primary="groq/llama-3.3-70b-versatile",
            fallback=["openai/gpt-4o"],
            max_tokens=2048,
            temperature=0.0,
            timeout_ms=20000,
        ),
        "summarization": RoutingPolicy(
            primary="groq/llama-3.3-70b-versatile",
            fallback=["openai/gpt-4o-mini"],
            max_tokens=2048,
            temperature=0.3,
            timeout_ms=20000,
        ),
        "embedding": RoutingPolicy(
            primary="openai/text-embedding-3-large",
            fallback=["cohere/embed-v3"],
            max_tokens=8192,
            temperature=0.0,
            timeout_ms=10000,
        ),
    }

    def __init__(self, config_path: Optional[str] = None):
        self.policies: Dict[str, RoutingPolicy] = {}
        self.config_path = config_path or "llm-gateway/routing_policies.yaml"
        self._initialized = False

    async def initialize(self):
        """Load routing policies from config."""
        if self._initialized:
            return

        # Load from YAML if exists
        await self._load_from_yaml()

        # Apply defaults for missing policies
        for node, policy in self.DEFAULT_POLICIES.items():
            if node not in self.policies:
                self.policies[node] = policy

        # Override from settings if provided
        self._apply_settings_overrides()

        self._initialized = True

    async def _load_from_yaml(self):
        """Load policies from YAML configuration."""
        try:
            config_file = Path(self.config_path)
            if config_file.exists():
                with open(config_file) as f:
                    config = yaml.safe_load(f)

                for node, policy_data in config.get("policies", {}).items():
                    self.policies[node] = RoutingPolicy(
                        primary=policy_data.get("primary", self.DEFAULT_POLICIES[node].primary),
                        fallback=policy_data.get("fallback", []),
                        max_tokens=policy_data.get("max_tokens", self.DEFAULT_POLICIES[node].max_tokens),
                        temperature=policy_data.get("temperature", self.DEFAULT_POLICIES[node].temperature),
                        timeout_ms=policy_data.get("timeout_ms", self.DEFAULT_POLICIES[node].timeout_ms),
                        retry=policy_data.get("retry", self.DEFAULT_POLICIES[node].retry),
                    )
        except Exception as e:
            # Config file optional, use defaults
            pass

    def _apply_settings_overrides(self):
        """Apply environment-specific overrides."""
        if settings.EXTRACTION_MODEL:
            self.policies["extraction"].primary = settings.EXTRACTION_MODEL
            self.policies["extraction"].temperature = settings.EXTRACTION_TEMPERATURE

        if settings.VERIFICATION_MODEL:
            self.policies["verification"].primary = settings.VERIFICATION_MODEL
            self.policies["verification"].temperature = settings.VERIFICATION_TEMPERATURE

    def get_route(self, pipeline_node: str) -> RoutingPolicy:
        """Get routing policy for a pipeline node."""
        return self.policies.get(pipeline_node, self.DEFAULT_POLICIES.get("extraction", RoutingPolicy(
            primary="groq/llama-3.3-70b-versatile",
            fallback=["openai/gpt-4o"],
        )))

    def list_policies(self) -> Dict[str, RoutingPolicy]:
        """List all routing policies."""
        return self.policies.copy()

    def update_policy(self, node: str, policy: RoutingPolicy):
        """Update a routing policy at runtime."""
        self.policies[node] = policy