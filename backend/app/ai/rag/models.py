"""Typed contracts for retrieval-augmented generation."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class RAGDocument:
    """A tenant-owned document chunk indexed for retrieval."""

    document_id: str
    tenant_id: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_type: str = "transcript"
    source_id: str | None = None
    chunk_index: int = 0
    created_at: datetime | None = None


@dataclass(frozen=True)
class RetrievedDocument:
    """A retrieved chunk with its relevance score and provenance."""

    document_id: str
    text: str
    score: float
    metadata: Mapping[str, Any]
    source_type: str
    source_id: str | None
    chunk_index: int

    def as_context(self) -> str:
        source = self.source_id or self.document_id
        return f"[{self.source_type}:{source}#{self.chunk_index} score={self.score:.3f}]\n{self.text}"
