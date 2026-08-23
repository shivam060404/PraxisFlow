from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "DEBUG"

    # Database
    DATABASE_URL: str = "postgresql://ami:ami_dev_password@localhost:5432/ami"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "ami_dev_password"

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # MinIO
    MINIO_ENDPOINT: str = "http://localhost:9000"
    MINIO_ACCESS_KEY: str = "ami"
    MINIO_SECRET_KEY: str = "ami_dev_password"
    MINIO_BUCKET_AUDIO: str = "meeting-audio"
    MINIO_BUCKET_TRANSCRIPTS: str = "meeting-transcripts"

    # Deepgram ASR
    DEEPGRAM_API_KEY: str = ""

    # Groq (Llama 3.3 70B)
    GROQ_API_KEY: str = ""

    # OpenAI (Embeddings + Judge)
    OPENAI_API_KEY: str = ""

    # JWT / Auth
    JWT_SECRET: str = "dev_secret_change_in_production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24

    # Clerk
    CLERK_PUBLISHABLE_KEY: Optional[str] = None
    CLERK_SECRET_KEY: Optional[str] = None
    CLERK_ISSUER: Optional[str] = None      # e.g. https://your-app.clerk.accounts.dev
    CLERK_JWKS_URL: Optional[str] = None    # override when JWKS lives elsewhere

    def validate_security_settings(self) -> None:
        """Fail fast on insecure production configuration."""
        import os as _os
        if self.ENVIRONMENT.lower() in {'production', 'prod'}:
            if not self.JWT_SECRET or self.JWT_SECRET == 'dev_secret_change_in_production':
                raise ValueError('JWT_SECRET must be a strong unique value in production')
            if not self.CLERK_SECRET_KEY:
                import logging
                logging.getLogger(__name__).warning(
                    'Production without Clerk configured: falling back to local HS256 auth'
                )

    # Langfuse
    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None
    LANGFUSE_HOST: str = "http://localhost:3000"
    LLM_GATEWAY_URL: Optional[str] = None  # LiteLLM proxy; unset = not deployed

    # Deepgram Options
    DEEPGRAM_MODEL: str = "nova-2"
    DEEPGRAM_LANGUAGE: str = "en"
    DEEPGRAM_DIARIZE: bool = True
    DEEPGRAM_UTTERANCES: bool = True
    DEEPGRAM_PUNCTUATE: bool = True
    DEEPGRAM_PARAGRAPHS: bool = True

    # GDPR: redact PII from transcripts before persistence and LLM calls
    PII_REDACTION_ENABLED: bool = True

    # Retention window for audit logs (EU AI Act Art. 19 / GDPR)
    AUDIT_RETENTION_DAYS: int = 2555  # 7 years

    # LLM Settings
    EXTRACTION_MODEL: str = "groq/llama-3.3-70b-versatile"
    EXTRACTION_TEMPERATURE: float = 0.1
    VERIFICATION_MODEL: str = "groq/llama-3.3-70b-versatile"
    VERIFICATION_TEMPERATURE: float = 0.0
    EMBEDDING_MODEL: str = "text-embedding-3-large"
    EMBEDDING_DIMENSIONS: int = 3072

    # Chunking
    CHUNK_SIZE: int = 2000
    CHUNK_OVERLAP: int = 200

    # Verification Thresholds
    VERIFICATION_FAITHFULNESS_THRESHOLD: float = 0.7
    VERIFICATION_HALLUCINATION_THRESHOLD: float = 0.1
    VERIFICATION_COMPLETENESS_THRESHOLD: float = 0.6

    # Entity Resolution
    ENTITY_RESOLUTION_MIN_CONFIDENCE: float = 0.6
    NAME_MATCH_THRESHOLD: int = 80

    # Deduplication
    DEDUP_SIMILARITY_THRESHOLD: float = 0.92

    # RAG
    RAG_TOP_K: int = 10
    RAG_RECENCY_BOOST_DAYS: int = 30

    # File Upload
    MAX_FILE_SIZE_MB: int = 500
    ALLOWED_AUDIO_TYPES: list[str] = ["audio/mpeg", "audio/wav", "audio/mp4", "audio/webm", "audio/x-m4a"]

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # API
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]


settings = Settings()