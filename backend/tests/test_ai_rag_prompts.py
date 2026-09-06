import pytest

from app.ai.prompts import get_prompt, render_prompt
from app.ai.rag.chunking import chunk_transcript
from app.ai.rag.models import RetrievedDocument
from app.ai.rag.service import RAGService


def test_prompt_registry_requires_all_variables():
    with pytest.raises(ValueError, match="Missing variables"):
        render_prompt("chunking", {"chunk_size": 100})


def test_prompt_registry_exposes_stable_version():
    prompt = get_prompt("extraction.system", "1.0.0")
    assert prompt.name == "extraction.system"
    assert prompt.version == "1.0.0"


def test_transcript_chunking_is_overlapping_and_auditable():
    documents = chunk_transcript(
        " ".join(f"word{i}" for i in range(10)),
        tenant_id="tenant-a",
        meeting_id="meeting-a",
        chunk_size=6,
        overlap=2,
    )
    assert [document.chunk_index for document in documents] == [0, 1]
    assert documents[0].metadata["word_end"] == 6
    assert documents[1].metadata["word_start"] == 4
    assert documents[0].tenant_id == "tenant-a"


def test_context_format_preserves_provenance_and_bounds_output():
    document = RetrievedDocument(
        document_id="id",
        text="evidence",
        score=0.91,
        metadata={"meeting_id": "meeting-a"},
        source_type="transcript",
        source_id="meeting-a",
        chunk_index=2,
    )
    context = RAGService.format_context([document])
    assert "transcript:meeting-a#2" in context
    assert "score=0.910" in context
