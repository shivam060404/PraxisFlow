"""Repository paths shared by runtime configuration and services."""

from pathlib import Path


def project_path(*parts: str) -> Path:
    """Resolve a path independently of the process working directory."""
    return PROJECT_ROOT.joinpath(*parts)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
LLM_GATEWAY_CONFIG = project_path("llm-gateway", "config", "routing_policies.yaml")
GUARDRAILS_CONFIG = (
    BACKEND_ROOT
    / "app"
    / "ai"
    / "guardrails"
    / "colang"
    / "extraction_policies.co"
)
