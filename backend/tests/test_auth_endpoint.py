"""
Tests for the development-only token endpoint.

The /auth/dev-token route must be invisible outside local development and
must only issue tokens for real, non-deleted users.
"""

import time
import asyncio
import pytest
from jose import jwt

from app.core.config import settings

SECRET = "test_strong_secret_for_smoke"


@pytest.fixture(autouse=True)
def real_settings(monkeypatch):
    """Override conftest's settings mock — this module tests real gating."""
    monkeypatch.setattr(settings, "JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CLERK_SECRET_KEY", None)
    monkeypatch.setattr(settings, "CLERK_ISSUER", None)
    monkeypatch.setattr(settings, "CLERK_JWKS_URL", None)
    yield


class FakeUser:
    def __init__(self, id="u-1", tenant_id="t-1", email="admin@dev.local", role="tenant_admin"):
        self.id = id
        self.tenantId = tenant_id
        self.email = email
        self.role = role
        self.status = "ACTIVE"


class FakeUserQuery:
    def __init__(self, user):
        self._user = user

    async def find_first(self, where):
        return self._user


class FakeDB:
    def __init__(self, user=None):
        self.user = FakeUserQuery(user)


def _issue(body, user):
    """Run on an isolated loop — asyncio.run() would clear the shared loop."""
    from app.api.auth import issue_dev_token

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(issue_dev_token(body, db=FakeDB(user)))
    finally:
        loop.close()


class TestDevTokenEndpoint:
    def test_issued_in_development(self):
        from app.api.auth import DevTokenRequest

        resp = _issue(DevTokenRequest(email="admin@dev.local"), FakeUser())
        assert resp.token_type == "bearer"

        claims = jwt.decode(resp.access_token, SECRET, algorithms=["HS256"])
        assert claims["sub"] == "u-1"
        assert claims["tenant_id"] == "t-1"
        assert claims["role"] == "tenant_admin"
        assert 0 < claims["exp"] - claims["iat"] <= 86400

    def test_expiry_clamped_to_max(self):
        from app.api.auth import DevTokenRequest

        resp = _issue(
            DevTokenRequest(email="admin@dev.local", expires_in_seconds=999_999),
            FakeUser(),
        )
        claims = jwt.decode(resp.access_token, SECRET, algorithms=["HS256"])
        assert claims["exp"] - claims["iat"] <= 86400

    def test_404_in_production(self, monkeypatch):
        from fastapi import HTTPException
        from app.api.auth import DevTokenRequest

        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        with pytest.raises(HTTPException) as exc:
            _issue(DevTokenRequest(email="admin@dev.local"), FakeUser())
        assert exc.value.status_code == 404

    def test_404_when_clerk_mode_active(self, monkeypatch):
        """Even in dev, hide the endpoint once Clerk is configured."""
        from fastapi import HTTPException
        from app.api.auth import DevTokenRequest

        monkeypatch.setattr(settings, "CLERK_SECRET_KEY", "sk_test_x")
        monkeypatch.setattr(settings, "CLERK_ISSUER", "https://clerk.example")
        with pytest.raises(HTTPException) as exc:
            _issue(DevTokenRequest(email="admin@dev.local"), FakeUser())
        assert exc.value.status_code == 404

    def test_404_for_unknown_user(self):
        from fastapi import HTTPException
        from app.api.auth import DevTokenRequest

        with pytest.raises(HTTPException) as exc:
            _issue(DevTokenRequest(email="nope@dev.local"), None)
        assert exc.value.status_code == 404
