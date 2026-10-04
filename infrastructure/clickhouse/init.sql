CREATE DATABASE IF NOT EXISTS praxisflow;

CREATE TABLE IF NOT EXISTS praxisflow.llm_usage
(
    id String,
    tenant_id String,
    user_id Nullable(String),
    meeting_id Nullable(String),
    pipeline_node LowCardinality(String),
    provider LowCardinality(String),
    model LowCardinality(String),
    prompt_tokens UInt64,
    completion_tokens UInt64,
    total_tokens UInt64,
    cost_usd Decimal(18, 8),
    cached Bool,
    created_at DateTime64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (tenant_id, created_at, id);
