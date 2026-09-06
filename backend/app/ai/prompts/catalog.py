"""Versioned, validated prompts used by the meeting-intelligence pipeline."""

import hashlib
from dataclasses import dataclass
from string import Formatter
from typing import Mapping


@dataclass(frozen=True)
class PromptTemplate:
    """Immutable prompt definition with explicit versioning and variables."""

    name: str
    version: str
    template: str
    required_variables: tuple[str, ...] = ()

    def render(self, **variables: object) -> str:
        missing = [key for key in self.required_variables if key not in variables]
        if missing:
            raise ValueError(f"Missing variables for prompt {self.name}@{self.version}: {missing}")
        return self.template.format(**variables)

    def as_record(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "content_hash": self.content_hash,
            "required_variables": list(self.required_variables),
        }

    @property
    def content_hash(self) -> str:
        """Stable hash for tracing, cache invalidation, and audit records."""
        return hashlib.sha256(self.template.encode("utf-8")).hexdigest()


def _variables(template: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(field_name for _, field_name, _, _ in Formatter().parse(template) if field_name))


EXTRACTION_SYSTEM_PROMPT = """You are a precise meeting intelligence extraction agent.
Your job is to read a meeting transcript segment and extract ONLY what is explicitly stated.

RULES:
1. Extract tasks, decisions, follow-ups, and blockers.
2. NEVER invent information not present in the transcript.
3. If a deadline is vague ("next week"), extract it as-is. Do NOT guess dates.
4. If an assignee is unclear ("someone should"), note it in assignee_hint as null.
5. Include the VERBATIM source quote for every extraction.
6. Rate your confidence honestly. Low confidence = flag for human review.

Respond ONLY with valid JSON matching the provided schema."""

CHUNKING_PROMPT = """Split the following transcript into semantic chunks of approximately {chunk_size} words with {overlap} words overlap.
Each chunk should be a coherent segment of conversation.

Return a JSON array of chunks with:
- index: chunk number
- text: the chunk text
- word_start: starting word index
- word_end: ending word index
- speakers: list of speaker labels in this chunk

Transcript:
{transcript_text}

Word indices are 0-based. The full transcript has {total_words} words."""

VERIFICATION_SYSTEM_PROMPT = """You are a strict verification agent with access to the FULL transcript.
Your job is to judge whether an extracted task FAITHFULLY represents what was said in the transcript.

You must evaluate:
1. FAITHFULNESS: Does the task title/description match the source quote? (0-1)
2. HALLUCINATION: Is any information invented that is NOT in the transcript? (0-1)
3. COMPLETENESS: Did the extraction miss critical context? (0-1)

RULES:
- If hallucination_score > 0.1, REJECT the extraction.
- If faithfulness_score < 0.7, REJECT the extraction.
- You MUST quote the EXACT transcript sentence(s) that prove or disprove the task.
- If you cannot find supporting evidence in the transcript, score hallucination high.

Respond ONLY with valid JSON."""

DEDUPLICATION_PROMPT = """You are given a list of extracted tasks. Some may be duplicates (same task mentioned multiple times).
Identify and merge duplicates. Two tasks are duplicates if they refer to the same action item, decision, or follow-up.

For each group of duplicates, keep the one with the highest confidence and merge the transcript spans (earliest start, latest end).

Return the deduplicated list of tasks as valid JSON matching the schema."""

JSON_REPAIR_PROMPT = """The previous LLM output failed Pydantic validation. Here is the error:

ERROR:
{error}

ORIGINAL OUTPUT:
{original_output}

SCHEMA:
{schema}

Please fix the JSON to match the schema exactly. Common issues:
- Missing required fields
- Wrong data types (e.g., string instead of number)
- Extra fields not in schema
- Enum values not matching allowed values
- Confidence must be 0.0-1.0
- transcript_word_start/end must be integers

Return ONLY the corrected valid JSON."""


PROMPTS: dict[str, PromptTemplate] = {
    "extraction.system": PromptTemplate("extraction.system", "1.0.0", EXTRACTION_SYSTEM_PROMPT),
    "chunking": PromptTemplate("chunking", "1.0.0", CHUNKING_PROMPT, _variables(CHUNKING_PROMPT)),
    "verification.system": PromptTemplate("verification.system", "1.0.0", VERIFICATION_SYSTEM_PROMPT),
    "deduplication": PromptTemplate("deduplication", "1.0.0", DEDUPLICATION_PROMPT),
    "json_repair": PromptTemplate("json_repair", "1.0.0", JSON_REPAIR_PROMPT, _variables(JSON_REPAIR_PROMPT)),
}


def get_prompt(name: str, version: str | None = None) -> PromptTemplate:
    """Return a known prompt, optionally requiring an exact version."""
    try:
        prompt = PROMPTS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown prompt: {name}") from exc
    if version is not None and prompt.version != version:
        raise ValueError(f"Prompt {name} has version {prompt.version}, requested {version}")
    return prompt


def render_prompt(name: str, variables: Mapping[str, object], version: str | None = None) -> str:
    """Render a registered prompt with strict variable validation."""
    return get_prompt(name, version).render(**dict(variables))
