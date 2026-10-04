from datetime import timezone

import pytest

from app.services.calendar_sync import normalize_calendar_event
from app.services.calendar_oauth import (
    EncryptedSecretStore, create_oauth_state, fetch_calendar_delta,
    refresh_access_token, validate_oauth_state, validate_secret_reference,
)
import httpx


@pytest.mark.parametrize(
    "provider,payload",
    [
        (
            "google",
            {
                "id": "google-1",
                "summary": "Quarterly review",
                "start": {"dateTime": "2026-10-05T10:00:00Z"},
                "end": {"dateTime": "2026-10-05T11:30:00Z"},
            },
        ),
        (
            "microsoft",
            {
                "id": "graph-1",
                "subject": "Quarterly review",
                "start": {"dateTime": "2026-10-05T10:00:00Z"},
                "end": {"dateTime": "2026-10-05T11:00:00Z"},
            },
        ),
    ],
)
def test_normalizes_calendar_event(provider, payload):
    event = normalize_calendar_event(provider, payload)

    assert event["externalEventId"] in {"google-1", "graph-1"}
    assert event["title"] == "Quarterly review"
    assert event["scheduledAt"].tzinfo == timezone.utc
    assert event["durationMinutes"] in {60, 90}


def test_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported calendar provider"):
        normalize_calendar_event("zoom", {"id": "event-1"})


def test_oauth_state_is_signed_and_provider_bound():
    token = create_oauth_state(tenant_id="tenant-1", provider="google", external_account="a@example.com")
    assert validate_oauth_state(token, provider="google").tenant_id == "tenant-1"
    with pytest.raises(ValueError):
        validate_oauth_state(token, provider="microsoft")


@pytest.mark.asyncio
async def test_secret_store_encrypts_without_exposing_plaintext():
    store = EncryptedSecretStore("test-calendar-key")
    reference = await store.store("bearer-token", hint="access")
    assert reference.startswith("encrypted://")
    assert "bearer-token" not in reference
    assert await store.resolve(reference) == "bearer-token"


def test_rejects_raw_token_values():
    with pytest.raises(ValueError):
        validate_secret_reference("ya29.raw-token", required=True)


@pytest.mark.asyncio
async def test_google_delta_uses_opaque_sync_cursor():
    def handler(request):
        assert request.headers["authorization"] == "Bearer access"
        return httpx.Response(200, json={"items": [{"id": "e1"}], "nextSyncToken": "opaque-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_calendar_delta("google", access_token="access", cursor=None, client=client)
    assert result.events == [{"id": "e1"}]
    assert result.cursor == "opaque-1"
    assert not result.reauth_required


@pytest.mark.asyncio
async def test_refresh_maps_provider_auth_failure_to_reauth():
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "invalid_grant"}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(PermissionError, match="reauthorization"):
            await refresh_access_token("microsoft", refresh_token="refresh", client=client)
