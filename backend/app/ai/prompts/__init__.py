"""Versioned prompt entry points for AI workflows."""

from app.ai.prompts.catalog import (
    CHUNKING_PROMPT,
    DEDUPLICATION_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    JSON_REPAIR_PROMPT,
    PROMPTS,
    VERIFICATION_SYSTEM_PROMPT,
    PromptTemplate,
    get_prompt,
    render_prompt,
)

__all__ = [
    "CHUNKING_PROMPT",
    "DEDUPLICATION_PROMPT",
    "EXTRACTION_SYSTEM_PROMPT",
    "JSON_REPAIR_PROMPT",
    "PROMPTS",
    "PromptTemplate",
    "VERIFICATION_SYSTEM_PROMPT",
    "get_prompt",
    "render_prompt",
]
