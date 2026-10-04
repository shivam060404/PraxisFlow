"""Durable cost analytics sink for ClickHouse.

The application ledger remains the source of truth. ClickHouse is an
append-only analytics projection and may be rebuilt from LLMUsageRecord.
"""

from typing import Any
import logging
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def publish_usage(record: dict[str, Any]) -> None:
    if not settings.CLICKHOUSE_URL:
        return
    columns = [
        "id", "tenant_id", "user_id", "meeting_id", "pipeline_node",
        "provider", "model", "prompt_tokens", "completion_tokens",
        "total_tokens", "cost_usd", "cached", "created_at",
    ]
    values = [[record.get(column) for column in columns]]
    query = (
        f"INSERT INTO {settings.CLICKHOUSE_DATABASE}.{settings.CLICKHOUSE_USAGE_TABLE} "
        f"({', '.join(columns)}) FORMAT JSONEachRow"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                settings.CLICKHOUSE_URL,
                params={"query": query},
                json=values,
            )
            response.raise_for_status()
    except Exception:
        logger.exception("ClickHouse usage projection failed")
        if settings.ENVIRONMENT.lower() in {"production", "prod", "staging"}:
            raise
