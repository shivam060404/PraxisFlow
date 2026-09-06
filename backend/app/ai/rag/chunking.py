"""Deterministic transcript chunking used before embedding and indexing."""

from app.ai.rag.models import RAGDocument


def chunk_transcript(
    transcript: str,
    *,
    tenant_id: str,
    meeting_id: str,
    chunk_size: int = 2000,
    overlap: int = 200,
) -> list[RAGDocument]:
    """Create stable, overlapping word chunks with auditable source metadata."""
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be in [0, chunk_size)")
    words = transcript.split()
    if not words:
        return []

    documents: list[RAGDocument] = []
    step = chunk_size - overlap
    for index, start in enumerate(range(0, len(words), step)):
        end = min(start + chunk_size, len(words))
        documents.append(
            RAGDocument(
                document_id=f"{meeting_id}:chunk:{index}",
                tenant_id=tenant_id,
                text=" ".join(words[start:end]),
                source_type="transcript",
                source_id=meeting_id,
                chunk_index=index,
                metadata={
                    "meeting_id": meeting_id,
                    "word_start": start,
                    "word_end": end,
                },
            )
        )
        if end == len(words):
            break
    return documents
