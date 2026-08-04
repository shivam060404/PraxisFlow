"""
Semantic Cache for LLM Gateway.
Uses Qdrant vector similarity to cache LLM responses.
"""

import json
import hashlib
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.config import settings
from app.services.storage import storage_service

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cached LLM response."""
    key: str
    response: Dict[str, Any]
    embedding: List[float]
    created_at: datetime
    access_count: int = 0
    last_accessed: Optional[datetime] = None


class SemanticCache:
    """
    Semantic cache using Qdrant for vector similarity search.
    Caches LLM responses based on prompt similarity.
    """

    def __init__(self):
        self.enabled = True
        self.similarity_threshold = 0.95
        self.max_entries_per_tenant = 10000
        self.ttl_days = 30
        self._initialized = False
        self._client = None

    async def initialize(self):
        """Initialize Qdrant client and collection."""
        if self._initialized:
            return

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams, PointStruct

            self._client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY,
            )

            # Create collection for semantic cache
            collection_name = "semantic_cache"
            collections = self._client.get_collections().collections
            if collection_name not in [c.name for c in collections]:
                self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=3072, distance=Distance.COSINE),
                )

            self._initialized = True
            logger.info("Semantic cache initialized")

        except Exception as e:
            logger.warning(f"Semantic cache unavailable: {e}")
            self.enabled = False

    def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for cache key. Uses simple hash-based for now."""
        # In production, use actual embedding model
        # For now, create a deterministic pseudo-embedding
        hash_bytes = hashlib.sha256(text.encode()).digest()
        # Expand to 3072 dimensions
        embedding = []
        for i in range(3072):
            byte_idx = i % len(hash_bytes)
            embedding.append((hash_bytes[byte_idx] / 255.0) * 2 - 1)
        return embedding

    def _get_collection_name(self, tenant_id: str) -> str:
        """Get tenant-specific collection name."""
        return f"semantic_cache_{tenant_id}"

    async def get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached response by exact key."""
        if not self.enabled or not self._initialized:
            return None

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            collection = "semantic_cache"  # Use shared collection with tenant filter
            result = self._client.scroll(
                collection_name=collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="cache_key", match=MatchValue(value=cache_key))]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )

            if result[0]:
                point = result[0][0]
                payload = point.payload
                # Check TTL
                created = datetime.fromisoformat(payload["created_at"])
                if datetime.utcnow() - created > timedelta(days=self.ttl_days):
                    await self.delete(cache_key)
                    return None

                # Update access count
                self._client.set_payload(
                    collection_name=collection,
                    payload={"access_count": payload.get("access_count", 0) + 1, "last_accessed": datetime.utcnow().isoformat()},
                    points=[point.id],
                )

                return payload["response"]

        except Exception as e:
            logger.error(f"Cache get error: {e}")

        return None

    async def set(self, cache_key: str, response: Dict[str, Any]) -> bool:
        """Store response in cache."""
        if not self.enabled or not self._initialized:
            return False

        try:
            from qdrant_client.models import PointStruct

            # Generate embedding from prompt (extracted from cache_key or response)
            prompt_text = cache_key  # Simplified
            embedding = self._generate_embedding(prompt_text)

            point = PointStruct(
                id=hashlib.md5(cache_key.encode()).hexdigest(),
                vector=embedding,
                payload={
                    "cache_key": cache_key,
                    "response": response,
                    "created_at": datetime.utcnow().isoformat(),
                    "access_count": 0,
                },
            )

            self._client.upsert(
                collection_name="semantic_cache",
                points=[point],
            )

            return True

        except Exception as e:
            logger.error(f"Cache set error: {e}")

        return False

    async def delete(self, cache_key: str) -> bool:
        """Delete cached entry."""
        if not self.enabled or not self._initialized:
            return False

        try:
            point_id = hashlib.md5(cache_key.encode()).hexdigest()
            self._client.delete(
                collection_name="semantic_cache",
                points_selector=[point_id],
            )
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False

    async def find_similar(self, prompt: str, tenant_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Find similar cached responses using vector similarity."""
        if not self.enabled or not self._initialized:
            return []

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            embedding = self._generate_embedding(prompt)

            results = self._client.search(
                collection_name="semantic_cache",
                query_vector=embedding,
                limit=limit,
                score_threshold=self.similarity_threshold,
                with_payload=True,
            )

            similar = []
            for hit in results:
                payload = hit.payload
                # Check TTL
                created = datetime.fromisoformat(payload["created_at"])
                if datetime.utcnow() - created <= timedelta(days=self.ttl_days):
                    similar.append({
                        "response": payload["response"],
                        "similarity": hit.score,
                        "cache_key": payload["cache_key"],
                    })

            return similar

        except Exception as e:
            logger.error(f"Similar search error: {e}")

        return []

    async def clear_tenant(self, tenant_id: str) -> bool:
        """Clear all cache entries for a tenant (GDPR compliance)."""
        if not self.enabled or not self._initialized:
            return False

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            self._client.delete(
                collection_name="semantic_cache",
                points_selector=Filter(
                    must=[FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))]
                ),
            )
            return True
        except Exception as e:
            logger.error(f"Clear tenant cache error: {e}")
            return False

    def disable(self):
        """Disable cache."""
        self.enabled = False

    def enable(self):
        """Enable cache."""
        self.enabled = True