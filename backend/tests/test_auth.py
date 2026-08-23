"""
Authentication & authorization security tests.

These tests exercise the real token verifier — forged signatures, expired
tokens, algorithm-confusion attempts, missing claims, and the default-secret
guard must all fail closed.
"""

import time
import base64
import json
import pytest
from jose import jwt

from app.security.auth import (
    verify_access_token,
    extract_bearer_token,
    AuthError,
    DEFAULT_DEV_SECRET,
    ROLE_ALIASES,
)


SECRET = "test_strong_secret_for_smoke"
now = int(time.time())


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    """
    Override conftest's global settings MagicMock: these tests exercise the
    REAL verifier against REAL Settings behavior (production guard included),
    so the settings object must not be a mock.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CLERK_SECRET_KEY", None)
    monkeypatch.setattr(settings, "CLERK_ISSUER", None)
    monkeypatch.setattr(settings, "CLERK_JWKS_URL", None)
    yield


@pytest.fixture(autouse=True)
def local_mode():
    """Kept for readability; real work happens in mock_settings above."""
    yield


def _tok(claims=None, secret=SECRET, alg="HS256"):
    payload = {"sub": "user-1", "tenant_id": "tenant-1", "exp": now + 600}
    payload.update(claims or {})
    return jwt.encode(payload, secret, algorithm=alg)


def _verify(token):
    """Run the async verifier on an isolated loop.

    Deliberately NOT asyncio.run(): it clears the current event loop on exit,
    which breaks pytest-asyncio's shared loop for subsequent async tests.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(verify_access_token(token))
    finally:
        loop.close()


class TestValidTokens:
    def test_valid_token_returns_identity(self):
        v = _verify(_tok())
        assert v.tenant_id == "tenant-1"
        assert v.user_id == "user-1"

    def test_role_alias_tenant_admin_maps_to_admin(self):
        v = _verify(_tok({"role": "tenant_admin"}))
        assert v.role == "admin"

    def test_unknown_role_falls_back_to_member(self):
        v = _verify(_tok({"role": "super_god"}))
        assert v.role == "member"

    def test_clerk_shaped_claims_accepted_in_local_mode(self):
        # sub-only tokens still need tenant_id — Clerk mode maps org_id;
        # in local mode tenant_id claim remains mandatory.
        with pytest.raises(AuthError):
            _verify(jwt.encode({"sub": "user-9", "org_id": "org-1", "exp": now + 600}, SECRET, algorithm="HS256"))


class TestRejectedTokens:
    def test_expired_rejected(self):
        with pytest.raises(AuthError):
            _verify(_tok({"exp": now - 10}))

    def test_wrong_signature_rejected(self):
        with pytest.raises(AuthError):
            _verify(_tok(secret="attacker-controlled-secret"))

    def test_missing_tenant_claim_rejected(self):
        with pytest.raises(AuthError):
            _verify(jwt.encode({"sub": "u", "exp": now + 600}, SECRET, algorithm="HS256"))

    def test_missing_subject_claim_rejected(self):
        with pytest.raises(AuthError):
            _verify(jwt.encode({"tenant_id": "t", "exp": now + 600}, SECRET, algorithm="HS256"))

    def test_alg_none_rejected(self):
        b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=")
        token = b64({"alg": "none", "typ": "JWT"}) + b"." + b64(
            {"sub": "u", "tenant_id": "t", "exp": now + 600}
        ) + b"."
        with pytest.raises(AuthError):
            _verify(token.decode())

    def test_default_dev_secret_rejected_outside_development(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
        token = jwt.encode(
            {"sub": "u", "tenant_id": "t", "exp": now + 600},
            DEFAULT_DEV_SECRET,
            algorithm="HS256",
        )
        with pytest.raises(AuthError):
            _verify(token)

    def test_default_dev_secret_allowed_in_development(self, monkeypatch):
        """Vanilla dev setup (JWT_SECRET left at its default) still works."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "JWT_SECRET", DEFAULT_DEV_SECRET)
        token = jwt.encode(
            {"sub": "u", "tenant_id": "t", "exp": now + 600},
            DEFAULT_DEV_SECRET,
            algorithm="HS256",
        )
        v = _verify(token)
        assert v.user_id == "u"


class TestProductionGuard:
    def test_production_validator_raises_on_default_secret(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "JWT_SECRET", DEFAULT_DEV_SECRET)
        with pytest.raises(Exception):
            settings.validate_security_settings()

    def test_production_validator_accepts_strong_secret(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "JWT_SECRET", "x" * 48)
        settings.validate_security_settings()  # must not raise


class TestBearerExtraction:
    def test_extracts_token(self):
        assert extract_bearer_token("Bearer abc.def") == "abc.def"

    def test_none_for_missing_or_malformed(self):
        assert extract_bearer_token(None) is None
        assert extract_bearer_token("Basic xyz") is None
        assert extract_bearer_token("Bearer ") is None


class TestRoleAliases:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("tenant_admin", "admin"),
            ("admin", "admin"),
            ("team_lead", "member"),
            ("member", "member"),
            ("viewer", "viewer"),
            ("api_service", "bot"),
            ("bot", "bot"),
        ],
    )
    def test_mapping(self, raw, expected):
        assert ROLE_ALIASES[raw] == expected


class TestWebhookReceiverExemption:
    """Middleware must exempt ONLY provider receivers — never /register or /hitl."""

    @pytest.fixture
    def middleware(self):
        from app.security.middleware import TenantIsolationMiddleware

        return TenantIsolationMiddleware(lambda scope, receive, send: None)

    class _Req:
        method = "POST"

        class url:
            path = ""

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("/api/v1/webhooks/jira", True),
            ("/api/v1/webhooks/TEAMS", True),
            ("/api/v1/webhooks/register", False),
            ("/api/v1/webhooks/hitl/resume", False),
            ("/api/v1/meetings", False),
            ("/api/v1/webhooks/jira/x", False),
        ],
    )
    def test_paths(self, middleware, path, expected):
        req = self._Req()
        req.url.path = path
        assert middleware._is_webhook_receiver(req) is expected

    def test_get_method_not_exempt(self, middleware):
        req = self._Req()
        req.method = "GET"
        req.url.path = "/api/v1/webhooks/jira"
        assert middleware._is_webhook_receiver(req) is False
