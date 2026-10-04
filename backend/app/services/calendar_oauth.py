"""Provider-neutral OAuth and calendar transport boundaries.

This module deliberately keeps bearer tokens out of API models, logs, and
database records. Connectors receive a secret reference and resolve it only
for the duration of an outbound request.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import urlencode
from base64 import urlsafe_b64encode
import hashlib
from cryptography.fernet import Fernet

import httpx
from jose import JWTError, jwt

from app.core.config import settings


class SecretStore(Protocol):
    async def resolve(self, reference: str) -> str: ...
    async def store(self, secret: str, *, hint: str) -> str: ...


class EncryptedSecretStore:
    """Small deployment-safe fallback; Vault/AWS adapters can implement the same protocol."""

    def __init__(self, key: str):
        self._fernet = Fernet(key if len(key) == 44 else urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))

    async def resolve(self, reference: str) -> str:
        if not reference.startswith("encrypted://"):
            raise ValueError("Unsupported secret reference")
        return self._fernet.decrypt(reference.removeprefix("encrypted://").encode()).decode()

    async def store(self, secret: str, *, hint: str) -> str:
        return "encrypted://" + self._fernet.encrypt(secret.encode()).decode()


def default_secret_store() -> EncryptedSecretStore:
    return EncryptedSecretStore(settings.CALENDAR_TOKEN_ENCRYPTION_KEY)


def validate_secret_reference(value: str | None, *, required: bool = False) -> str | None:
    """Accept references, never an OAuth token accidentally posted by a client."""
    if value is None and not required:
        return None
    if not value or len(value) > 500 or " " in value:
        raise ValueError("OAuth tokens must be stored as a secret reference")
    if not value.startswith(("vault://", "aws-sm://", "encrypted://", "secret://")):
        raise ValueError("OAuth tokens must be stored as a secret reference")
    return value


@dataclass(frozen=True)
class OAuthState:
    tenant_id: str
    provider: str
    external_account: str
    expires_at: datetime


def create_oauth_state(*, tenant_id: str, provider: str, external_account: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"typ": "calendar_oauth", "tenant": tenant_id, "provider": provider,
         "account": external_account, "exp": int((now + timedelta(minutes=10)).timestamp()),
         "iat": int(now.timestamp())},
        settings.CALENDAR_OAUTH_STATE_SECRET,
        algorithm="HS256",
    )


def validate_oauth_state(token: str, *, provider: str) -> OAuthState:
    try:
        claims = jwt.decode(token, settings.CALENDAR_OAUTH_STATE_SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise ValueError("Invalid or expired OAuth state") from exc
    if claims.get("typ") != "calendar_oauth" or claims.get("provider") != provider:
        raise ValueError("Invalid OAuth state")
    return OAuthState(
        tenant_id=str(claims["tenant"]),
        provider=str(claims["provider"]),
        external_account=str(claims["account"]),
        expires_at=datetime.fromtimestamp(int(claims["exp"]), timezone.utc),
    )


@dataclass(frozen=True)
class ProviderConfig:
    authorize_url: str
    token_url: str
    scope: str
    events_url: str


def provider_config(provider: str) -> ProviderConfig:
    if provider == "google":
        return ProviderConfig(
            settings.GOOGLE_OAUTH_AUTHORIZE_URL, settings.GOOGLE_OAUTH_TOKEN_URL,
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        )
    if provider == "microsoft":
        return ProviderConfig(
            settings.MICROSOFT_OAUTH_AUTHORIZE_URL, settings.MICROSOFT_OAUTH_TOKEN_URL,
            "offline_access Calendars.Read",
            "https://graph.microsoft.com/v1.0/me/calendarView",
        )
    raise ValueError(f"Unsupported calendar provider: {provider}")


async def exchange_code(
    provider: str, *, code: str, redirect_uri: str, client: httpx.AsyncClient
) -> dict[str, Any]:
    config = provider_config(provider)
    client_id = settings.GOOGLE_OAUTH_CLIENT_ID if provider == "google" else settings.MICROSOFT_OAUTH_CLIENT_ID
    client_secret = settings.GOOGLE_OAUTH_CLIENT_SECRET if provider == "google" else settings.MICROSOFT_OAUTH_CLIENT_SECRET
    response = await client.post(config.token_url, data={
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    })
    response.raise_for_status()
    return response.json()


async def refresh_access_token(
    provider: str, *, refresh_token: str, client: httpx.AsyncClient
) -> dict[str, Any]:
    config = provider_config(provider)
    client_id = settings.GOOGLE_OAUTH_CLIENT_ID if provider == "google" else settings.MICROSOFT_OAUTH_CLIENT_ID
    client_secret = settings.GOOGLE_OAUTH_CLIENT_SECRET if provider == "google" else settings.MICROSOFT_OAUTH_CLIENT_SECRET
    response = await client.post(config.token_url, data={
        "refresh_token": refresh_token, "client_id": client_id,
        "client_secret": client_secret, "grant_type": "refresh_token",
    })
    if response.status_code in (400, 401):
        raise PermissionError("Calendar authorization expired; reauthorization required")
    response.raise_for_status()
    return response.json()


@dataclass(frozen=True)
class SyncResult:
    events: list[dict[str, Any]]
    cursor: str | None
    deleted_external_ids: list[str]
    reauth_required: bool = False


async def fetch_calendar_delta(
    provider: str, *, access_token: str, cursor: str | None, client: httpx.AsyncClient
) -> SyncResult:
    """Fetch one bounded page and return an opaque provider cursor."""
    config = provider_config(provider)
    url = cursor or config.events_url
    headers = {"Authorization": f"Bearer {access_token}"}
    params = None if cursor else {"singleEvents": "true", "showDeleted": "true", "maxResults": "250"}
    response = await client.get(url, headers=headers, params=params)
    if response.status_code == 410:
        # Provider invalidated the cursor; caller must perform a full resync.
        return SyncResult([], None, [])
    if response.status_code in (401, 403):
        return SyncResult([], cursor, [], reauth_required=True)
    response.raise_for_status()
    body = response.json()
    if provider == "google":
        events = body.get("items", [])
        next_cursor = body.get("nextSyncToken") or body.get("nextPageToken") or cursor
        deleted = [event["id"] for event in events if event.get("status") == "cancelled" and event.get("id")]
    else:
        events = body.get("value", [])
        next_cursor = body.get("@odata.deltaLink") or body.get("@odata.nextLink") or cursor
        deleted = [event["id"] for event in events if event.get("@removed") and event.get("id")]
    return SyncResult(events, next_cursor, deleted)


def authorization_url(provider: str, *, tenant_id: str, external_account: str, redirect_uri: str) -> str:
    config = provider_config(provider)
    client_id = settings.GOOGLE_OAUTH_CLIENT_ID if provider == "google" else settings.MICROSOFT_OAUTH_CLIENT_ID
    state = create_oauth_state(tenant_id=tenant_id, provider=provider, external_account=external_account)
    params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
              "scope": config.scope, "state": state, "access_type": "offline", "prompt": "consent"}
    return f"{config.authorize_url}?{urlencode(params)}"
