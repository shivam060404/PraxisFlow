"""Tenant-isolated retrieval service backed by Qdrant and gateway embeddings."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable, Sequence

from app.ai.rag.models import RAGDocument, RetrievedDocument
from app.core.config import settings

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.clients.llm_gateway.client import LLMGatewayClient

logger = logging.getLogger(__name__)


class RAGServiceError(RuntimeError):
    """Raised when retrieval cannot safely complete."""


class RAGService:
    """Indexes and retrieves document chunks with mandatory tenant isolation."""

    def __init__(
        self,
        gateway: LLMGatewayClient,
        collection_name: str | None = None,
    ):
        self.gateway = gateway
        self.collection_name = collection_name or settings.RAG_COLLECTION_NAME
        self._client = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
            await asyncio.to_thread(self._ensure_collection, VectorParams, Distance)
            self._initialized = True
        except Exception as exc:
            raise RAGServiceError(f"Unable to initialize Qdrant retrieval: {exc}") from exc

    def _ensure_collection(self, vector_params, distance) -> None:
        assert self._client is not None
        collections = self._client.get_collections().collections
        if self.collection_name not in {item.name for item in collections}:
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=vector_params(
                    size=settings.EMBEDDING_DIMENSIONS,
                    distance=distance.COSINE,
                ),
            )

    async def index(self, documents: Sequence[RAGDocument]) -> int:
        """Embed and upsert documents, rejecting mixed-tenant batches."""
        if not documents:
            return 0
        tenant_ids = {document.tenant_id for document in documents}
        if len(tenant_ids) != 1:
            raise ValueError("RAG index batches must contain exactly one tenant")
        await self.initialize()

        texts = [document.text.strip() for document in documents]
        if any(not text for text in texts):
            raise ValueError("RAG documents must contain non-empty text")
        embedding_response = await self.gateway.embeddings(
            texts=texts,
            tenant_id=documents[0].tenant_id,
            user_id="rag-indexer",
        )
        if len(embedding_response.embeddings) != len(documents):
            raise RAGServiceError("Embedding provider returned an unexpected vector count")

        from qdrant_client.models import PointStruct

        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, document.document_id)),
                vector=embedding,
                payload={
                    "document_id": document.document_id,
                    "tenant_id": document.tenant_id,
                    "text": document.text,
                    "metadata": dict(document.metadata),
                    "source_type": document.source_type,
                    "source_id": document.source_id,
                    "chunk_index": document.chunk_index,
                    "created_at": (document.created_at or datetime.now(timezone.utc)).isoformat(),
                },
            )
            for document, embedding in zip(documents, embedding_response.embeddings)
        ]
        await asyncio.to_thread(self._upsert, points)
        return len(points)

    async def index_transcript(self, transcript: str, tenant_id: str, meeting_id: str) -> int:
        """Chunk and index one transcript using the configured chunk policy."""
        from app.ai.rag.chunking import chunk_transcript

        return await self.index(
            chunk_transcript(
                transcript,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                chunk_size=settings.CHUNK_SIZE,
                overlap=settings.CHUNK_OVERLAP,
            )
        )

    def _upsert(self, points) -> None:
        assert self._client is not None
        self._client.upsert(collection_name=self.collection_name, points=points, wait=True)

    async def retrieve(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
        meeting_id: str | None = None,
        limit: int | None = None,
        score_threshold: float | None = None,
    ) -> list[RetrievedDocument]:
        """Retrieve only chunks belonging to ``tenant_id``."""
        if not query.strip():
            return []
        await self.initialize()
        embedding_response = await self.gateway.embeddings(
            texts=[query],
            tenant_id=tenant_id,
            user_id=user_id,
        )
        vector = embedding_response.embeddings[0]
        results = await asyncio.to_thread(
            self._search,
            vector,
            tenant_id,
            meeting_id,
            limit or settings.RAG_TOP_K,
            score_threshold,
        )
        return [
            RetrievedDocument(
                document_id=point.payload.get("document_id", str(point.id)),
                text=point.payload["text"],
                score=float(point.score),
                metadata=point.payload.get("metadata", {}),
                source_type=point.payload.get("source_type", "unknown"),
                source_id=point.payload.get("source_id"),
                chunk_index=int(point.payload.get("chunk_index", 0)),
            )
            for point in results
        ]

    def _search(
        self,
        vector,
        tenant_id: str,
        meeting_id: str | None,
        limit: int,
        score_threshold: float | None,
    ):
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        assert self._client is not None
        conditions = [
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))
        ]
        if meeting_id is not None:
            conditions.append(FieldCondition(key="metadata.meeting_id", match=MatchValue(value=meeting_id)))
        return self._client.search(
            collection_name=self.collection_name,
            query_vector=vector,
            query_filter=Filter(
                must=conditions
            ),
            limit=max(1, min(limit, 100)),
            score_threshold=score_threshold,
            with_payload=True,
        )

    @staticmethod
    def format_context(documents: Iterable[RetrievedDocument], max_chars: int = 12000) -> str:
        """Format bounded, provenance-preserving context for a model prompt."""
        context = "\n\n".join(document.as_context() for document in documents)
        return context[:max_chars] if len(context) > max_chars else context
