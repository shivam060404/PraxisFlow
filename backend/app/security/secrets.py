"""
Secrets Management for PraxisFlow
HashiCorp Vault integration with AWS Secrets Manager fallback.
"""

import os
import logging
import hvac
import boto3
import json
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
from dataclasses import dataclass
from contextlib import contextmanager
from functools import lru_cache

from app.core.config import settings

logger = logging.getLogger(__name__)


# ─── Configuration ───

@dataclass
class VaultConfig:
    url: str = "http://vault:8200"
    token: Optional[str] = None
    namespace: Optional[str] = None
    mount_point: str = "secret"
    kv_version: int = 2


@dataclass
class AWSSecretsConfig:
    region: str = "us-east-1"
    secret_prefix: str = "praxisflow/"


# ─── Exceptions ───

class SecretNotFoundError(Exception):
    pass


class SecretsBackendError(Exception):
    pass


# ─── Abstract Backend ───

class SecretsBackend(ABC):
    """Abstract secrets backend."""

    @abstractmethod
    def get_secret(self, path: str, key: Optional[str] = None) -> Any:
        pass

    @abstractmethod
    def set_secret(self, path: str, data: Dict[str, Any]) -> bool:
        pass

    @abstractmethod
    def delete_secret(self, path: str) -> bool:
        pass

    @abstractmethod
    def list_secrets(self, path: str) -> List[str]:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass


# ─── Vault Backend ───

class VaultBackend(SecretsBackend):
    """HashiCorp Vault backend."""

    def __init__(self, config: VaultConfig):
        self.config = config
        self._client: Optional[hvac.Client] = None

    def _get_client(self) -> hvac.Client:
        if self._client is None:
            self._client = hvac.Client(
                url=self.config.url,
                token=self.config.token,
                namespace=self.config.namespace,
            )
            if not self._client.is_authenticated():
                raise SecretsBackendError("Vault authentication failed")
        return self._client

    def get_secret(self, path: str, key: Optional[str] = None) -> Any:
        try:
            client = self._get_client()
            full_path = f"{self.config.mount_point}/data/{path}" if self.config.kv_version == 2 else f"{self.config.mount_point}/{path}"

            if self.config.kv_version == 2:
                response = client.secrets.kv.v2.read_secret_version(path=path, mount_point=self.config.mount_point)
                data = response.get('data', {}).get('data', {})
            else:
                response = client.secrets.kv.v1.read_secret(path=path, mount_point=self.config.mount_point)
                data = response.get('data', {})

            if not data:
                raise SecretNotFoundError(f"Secret not found: {path}")

            if key:
                if key not in data:
                    raise SecretNotFoundError(f"Key not found in secret: {key}")
                return data[key]

            return data

        except hvac.exceptions.InvalidPath:
            raise SecretNotFoundError(f"Secret not found: {path}")
        except hvac.exceptions.Forbidden:
            raise SecretsBackendError(f"Access denied to secret: {path}")
        except Exception as e:
            logger.error(f"Vault error getting secret {path}: {e}")
            raise SecretsBackendError(f"Failed to get secret: {e}")

    def set_secret(self, path: str, data: Dict[str, Any]) -> bool:
        try:
            client = self._get_client()

            if self.config.kv_version == 2:
                client.secrets.kv.v2.create_or_update_secret(
                    path=path,
                    secret=data,
                    mount_point=self.config.mount_point,
                )
            else:
                client.secrets.kv.v1.create_or_update_secret(
                    path=path,
                    secret=data,
                    mount_point=self.config.mount_point,
                )

            logger.info(f"Secret written to Vault: {path}")
            return True

        except Exception as e:
            logger.error(f"Vault error setting secret {path}: {e}")
            raise SecretsBackendError(f"Failed to set secret: {e}")

    def delete_secret(self, path: str) -> bool:
        try:
            client = self._get_client()

            if self.config.kv_version == 2:
                client.secrets.kv.v2.delete_metadata_and_all_versions(path=path, mount_point=self.config.mount_point)
            else:
                client.secrets.kv.v1.delete_secret(path=path, mount_point=self.config.mount_point)

            logger.info(f"Secret deleted from Vault: {path}")
            return True

        except Exception as e:
            logger.error(f"Vault error deleting secret {path}: {e}")
            raise SecretsBackendError(f"Failed to delete secret: {e}")

    def list_secrets(self, path: str) -> List[str]:
        try:
            client = self._get_client()

            if self.config.kv_version == 2:
                response = client.secrets.kv.v2.list_secrets(path=path, mount_point=self.config.mount_point)
                return response.get('data', {}).get('keys', [])
            else:
                response = client.secrets.kv.v1.list_secrets(path=path, mount_point=self.config.mount_point)
                return response.get('data', {}).get('keys', [])

        except Exception as e:
            logger.error(f"Vault error listing secrets {path}: {e}")
            raise SecretsBackendError(f"Failed to list secrets: {e}")

    def health_check(self) -> bool:
        try:
            client = self._get_client()
            return client.sys.is_sealed() is False
        except Exception:
            return False


# ─── AWS Secrets Manager Backend ───

class AWSSecretsBackend(SecretsBackend):
    """AWS Secrets Manager backend."""

    def __init__(self, config: AWSSecretsConfig):
        self.config = config
        self._client: Optional[boto3.client] = None

    def _get_client(self) -> boto3.client:
        if self._client is None:
            self._client = boto3.client('secretsmanager', region_name=self.config.region)
        return self._client

    def _full_name(self, path: str) -> str:
        return f"{self.config.secret_prefix}{path}"

    def get_secret(self, path: str, key: Optional[str] = None) -> Any:
        try:
            client = self._get_client()
            response = client.get_secret_value(SecretId=self._full_name(path))

            secret_string = response.get('SecretString', '{}')
            import json
            data = json.loads(secret_string)

            if key:
                if key not in data:
                    raise SecretNotFoundError(f"Key not found in secret: {key}")
                return data[key]

            return data

        except client.exceptions.ResourceNotFoundException:
            raise SecretNotFoundError(f"Secret not found: {path}")
        except Exception as e:
            logger.error(f"AWS Secrets Manager error getting secret {path}: {e}")
            raise SecretsBackendError(f"Failed to get secret: {e}")

    def set_secret(self, path: str, data: Dict[str, Any]) -> bool:
        try:
            client = self._get_client()
            import json

            try:
                client.create_secret(
                    Name=self._full_name(path),
                    SecretString=json.dumps(data),
                )
            except client.exceptions.ResourceExistsException:
                client.put_secret_value(
                    SecretId=self._full_name(path),
                    SecretString=json.dumps(data),
                )

            logger.info(f"Secret written to AWS Secrets Manager: {path}")
            return True

        except Exception as e:
            logger.error(f"AWS Secrets Manager error setting secret {path}: {e}")
            raise SecretsBackendError(f"Failed to set secret: {e}")

    def delete_secret(self, path: str) -> bool:
        try:
            client = self._get_client()
            client.delete_secret(SecretId=self._full_name(path), ForceDeleteWithoutRecovery=True)
            logger.info(f"Secret deleted from AWS Secrets Manager: {path}")
            return True

        except Exception as e:
            logger.error(f"AWS Secrets Manager error deleting secret {path}: {e}")
            raise SecretsBackendError(f"Failed to delete secret: {e}")

    def list_secrets(self, path: str) -> List[str]:
        try:
            client = self._get_client()
            paginator = client.get_paginator('list_secrets')
            secrets = []

            for page in paginator.paginate(
                Filters=[{'Key': 'name', 'Values': [f"{self.config.secret_prefix}{path}"]}]
            ):
                for secret in page.get('SecretList', []):
                    # Extract relative path
                    rel_path = secret['Name'].replace(self.config.secret_prefix, '', 1)
                    secrets.append(rel_path)

            return secrets

        except Exception as e:
            logger.error(f"AWS Secrets Manager error listing secrets {path}: {e}")
            raise SecretsBackendError(f"Failed to list secrets: {e}")

    def health_check(self) -> bool:
        try:
            client = self._get_client()
            client.list_secrets(MaxResults=1)
            return True
        except Exception:
            return False


# ─── Environment Variable Backend (Development) ───

class EnvBackend(SecretsBackend):
    """Environment variable backend for development."""

    def get_secret(self, path: str, key: Optional[str] = None) -> Any:
        # Convert path to env var: praxisflow/database/password -> PRAXISFLOW_DATABASE_PASSWORD
        env_var = path.upper().replace('/', '_').replace('-', '_')

        if key:
            env_var = f"{env_var}_{key.upper()}"

        value = os.getenv(env_var)
        if value is None:
            raise SecretNotFoundError(f"Environment variable not found: {env_var}")

        # Try to parse as JSON
        try:
            import json
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value

    def set_secret(self, path: str, data: Dict[str, Any]) -> bool:
        # Not supported in env backend
        raise NotImplementedError("Cannot set secrets in environment variable backend")

    def delete_secret(self, path: str) -> bool:
        raise NotImplementedError("Cannot delete secrets in environment variable backend")

    def list_secrets(self, path: str) -> List[str]:
        return []

    def health_check(self) -> bool:
        return True


# ─── Secrets Manager ───

class SecretsManager:
    """Unified secrets manager with backend fallback."""

    def __init__(self):
        self._primary: Optional[SecretsBackend] = None
        self._fallback: Optional[SecretsBackend] = None
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = 300  # 5 minutes

    def configure_vault(self, config: VaultConfig):
        self._primary = VaultBackend(config)

    def configure_aws(self, config: AWSSecretsConfig):
        self._primary = AWSSecretsBackend(config)

    def configure_env(self):
        self._fallback = EnvBackend()

    def _get_backend(self, use_fallback: bool = False) -> SecretsBackend:
        if use_fallback and self._fallback:
            return self._fallback
        if self._primary:
            return self._primary
        if self._fallback:
            return self._fallback
        raise SecretsBackendError("No secrets backend configured")

    def get_secret(self, path: str, key: Optional[str] = None, use_cache: bool = True) -> Any:
        cache_key = f"{path}:{key}" if key else path

        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        # Try primary
        try:
            backend = self._get_backend()
            value = backend.get_secret(path, key)

            if use_cache:
                self._cache[cache_key] = value

            return value

        except (SecretNotFoundError, SecretsBackendError) as e:
            # Try fallback
            if self._fallback:
                try:
                    logger.warning(f"Primary backend failed, trying fallback: {e}")
                    backend = self._get_backend(use_fallback=True)
                    value = backend.get_secret(path, key)

                    if use_cache:
                        self._cache[cache_key] = value

                    return value
                except Exception as fallback_error:
                    logger.error(f"Fallback backend also failed: {fallback_error}")

            raise

    def set_secret(self, path: str, data: Dict[str, Any]) -> bool:
        # Invalidate cache
        self._invalidate_cache(path)

        try:
            backend = self._get_backend()
            return backend.set_secret(path, data)
        except SecretsBackendError as e:
            if self._fallback:
                logger.warning(f"Primary backend failed, trying fallback for write: {e}")
                fallback_backend = self._get_backend(use_fallback=True)
                return fallback_backend.set_secret(path, data)
            raise

    def delete_secret(self, path: str) -> bool:
        self._invalidate_cache(path)

        try:
            backend = self._get_backend()
            return backend.delete_secret(path)
        except SecretsBackendError as e:
            if self._fallback:
                fallback_backend = self._get_backend(use_fallback=True)
                return fallback_backend.delete_secret(path)
            raise

    def list_secrets(self, path: str) -> List[str]:
        try:
            backend = self._get_backend()
            return backend.list_secrets(path)
        except SecretsBackendError:
            if self._fallback:
                fallback_backend = self._get_backend(use_fallback=True)
                return fallback_backend.list_secrets(path)
            raise

    def _invalidate_cache(self, path: str):
        keys_to_remove = [k for k in self._cache if k.startswith(path)]
        for k in keys_to_remove:
            del self._cache[k]

    def health_check(self) -> Dict[str, bool]:
        return {
            "primary": self._primary.health_check() if self._primary else False,
            "fallback": self._fallback.health_check() if self._fallback else False,
        }


# ─── Global Instance & Helpers ───

_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
        _configure_defaults()
    return _secrets_manager


def _configure_defaults():
    """Configure defaults based on environment."""
    manager = get_secrets_manager()

    if settings.ENVIRONMENT == "production":
        # Production: Vault primary, AWS fallback
        vault_url = os.getenv("VAULT_ADDR", "https://vault.praxisflow.internal")
        vault_token = os.getenv("VAULT_TOKEN")

        if vault_token:
            manager.configure_vault(VaultConfig(url=vault_url, token=vault_token))

        aws_region = os.getenv("AWS_REGION", "us-east-1")
        manager.configure_aws(AWSSecretsConfig(region=aws_region))

    elif settings.ENVIRONMENT == "staging":
        # Staging: Vault
        vault_url = os.getenv("VAULT_ADDR", "http://vault:8200")
        vault_token = os.getenv("VAULT_TOKEN", "dev-token")
        manager.configure_vault(VaultConfig(url=vault_url, token=vault_token))

    else:
        # Development: Environment variables
        manager.configure_env()


# ─── Convenience Functions ───

def get_secret(path: str, key: Optional[str] = None, default: Any = None) -> Any:
    """Get a secret with optional default."""
    try:
        return get_secrets_manager().get_secret(path, key)
    except SecretNotFoundError:
        if default is not None:
            return default
        raise


def set_secret(path: str, data: Dict[str, Any]) -> bool:
    return get_secrets_manager().set_secret(path, data)


def delete_secret(path: str) -> bool:
    return get_secrets_manager().delete_secret(path)


# ─── Application Secret Helpers ───

def get_database_url() -> str:
    return get_secret("database", "url", settings.DATABASE_URL)


def get_groq_api_key() -> str:
    return get_secret("llm/groq", "api_key", settings.GROQ_API_KEY)


def get_openai_api_key() -> str:
    return get_secret("llm/openai", "api_key", settings.OPENAI_API_KEY)


def get_anthropic_api_key() -> str:
    return get_secret("llm/anthropic", "api_key", os.getenv("ANTHROPIC_API_KEY", ""))


def get_deepgram_api_key() -> str:
    return get_secret("asr/deepgram", "api_key", settings.DEEPGRAM_API_KEY)


def get_jwt_secret() -> str:
    return get_secret("auth/jwt", "secret", settings.JWT_SECRET)


def get_redis_url() -> str:
    return get_secret("redis", "url", settings.REDIS_URL)


def get_kafka_bootstrap_servers() -> str:
    return get_secret("kafka", "bootstrap_servers", settings.KAFKA_BOOTSTRAP_SERVERS)


def get_neo4j_credentials() -> Dict[str, str]:
    return get_secret("neo4j", None, {
        "uri": settings.NEO4J_URI,
        "user": settings.NEO4J_USER,
        "password": settings.NEO4J_PASSWORD,
    })


def get_qdrant_credentials() -> Dict[str, str]:
    return get_secret("qdrant", None, {
        "url": settings.QDRANT_URL,
        "api_key": settings.QDRANT_API_KEY,
    })


def get_minio_credentials() -> Dict[str, str]:
    return get_secret("minio", None, {
        "endpoint": settings.MINIO_ENDPOINT,
        "access_key": settings.MINIO_ACCESS_KEY,
        "secret_key": settings.MINIO_SECRET_KEY,
    })


def get_langfuse_keys() -> Dict[str, str]:
    return get_secret("observability/langfuse", None, {
        "public_key": os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        "secret_key": os.getenv("LANGFUSE_SECRET_KEY", ""),
        "host": os.getenv("LANGFUSE_HOST", "http://langfuse:3000"),
    })


def get_clerk_keys() -> Dict[str, str]:
    return get_secret("auth/clerk", None, {
        "publishable_key": settings.CLERK_PUBLISHABLE_KEY,
        "secret_key": settings.CLERK_SECRET_KEY,
    })


def get_integration_secrets(provider: str) -> Dict[str, Any]:
    """Get integration-specific secrets (OAuth tokens, API keys, webhook secrets)."""
    return get_secret(f"integrations/{provider}", None, {})


# ─── Exports ───

__all__ = [
    "VaultConfig",
    "AWSSecretsConfig",
    "SecretsBackend",
    "VaultBackend",
    "AWSSecretsBackend",
    "EnvBackend",
    "SecretsManager",
    "SecretNotFoundError",
    "SecretsBackendError",
    "get_secrets_manager",
    "get_secret",
    "set_secret",
    "delete_secret",
    "get_database_url",
    "get_groq_api_key",
    "get_openai_api_key",
    "get_anthropic_api_key",
    "get_deepgram_api_key",
    "get_jwt_secret",
    "get_redis_url",
    "get_kafka_bootstrap_servers",
    "get_neo4j_credentials",
    "get_qdrant_credentials",
    "get_minio_credentials",
    "get_langfuse_keys",
    "get_clerk_keys",
    "get_integration_secrets",
]