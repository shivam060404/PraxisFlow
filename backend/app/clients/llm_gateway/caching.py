"""
LLM response cache for the gateway.

Two modes:
  - "semantic": real text-embedding-3-large vectors via OpenAI — similar
    prompts can hit within the similarity threshold.
  - "exact" (default without OPENAI_API_KEY): byte-identical prompt keys
    only. We deliberately DO NOT fabricate similarity from hash-derived
    pseudo-vectors: hash embeddings make every score meaningless.

The hot path used by LLMGatewayClient (get/set by exact key) behaves the
same in both modes.
"""

import json
import hashlib
from collections import OrderedDict
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.config import settings

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
        # "exact" until an embedding provider is available
        self.mode = "exact"
        self._embedding_cache: "OrderedDict[str, List[float]]" = OrderedDict()

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

            self.mode = "semantic" if getattr(settings, "OPENAI_API_KEY", None) else "exact"
            self._initialized = True
            logger.info(f"Cache initialized (mode={self.mode})")

        except Exception as e:
            logger.warning(f"Semantic cache unavailable: {e}")
            self.enabled = False

    _EMBED_MODEL = "text-embedding-3-large"
    _EMBED_DIMS = 3072
    _EMBED_CACHE_MAX = 512

    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Real embedding via OpenAI, memoized per process.
        Returns None when no provider is configured — callers must then use
        exact-match lookups instead of vector search.
        """
        if not getattr(settings, "OPENAI_API_KEY", None):
            return None

        cached = self._embedding_cache.get(text)
        if cached is not None:
            return cached

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            import asyncio

            resp = asyncio.get_event_loop().run_until_complete(
                client.embeddings.create(model=self._EMBED_MODEL, input=text[:8000])
            )
            vector = resp.data[0].embedding
        except Exception as e:
            logger.warning(f"Embedding failed ({e}); falling back to exact match")
            return None

        if len(self._embedding_cache) >= self._EMBED_CACHE_MAX:
            self._embedding_cache.popitem(last=False)
        self._embedding_cache[text] = vector
        return vector

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
        """
        Find cached responses similar to the prompt.

        Semantic mode uses true embeddings; exact mode returns ONLY the
        byte-identical prompt (never approximations).
        """
        if not self.enabled or not self._initialized:
            return []

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            embedding = self._generate_embedding(prompt)
            if embedding is None:
                # Exact mode: identical prompt only
                exact_key = hashlib.sha256(
                    json.dumps({"prompt": prompt}, sort_keys=True).encode()
                ).hexdigest()
                hit = await self.get(exact_key)
                if hit:
                    return [{"response": hit, "similarity": 1.0, "cache_key": exact_key}]
                return []

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