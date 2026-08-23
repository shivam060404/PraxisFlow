"""
Token authentication for PraxisFlow.

Two modes:
  - "clerk": RS256 verification against Clerk's JWKS when Clerk keys are
    configured (production path).
  - "local": HS256 with JWT_SECRET for development. Tokens signed with the
    known default secret are REJECTED outside the development environment.

The verifier is the single source of truth for request identity. Middleware
and FastAPI dependencies both route through verify_access_token().
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from jose import jwt as jose_jwt
from jose import jwk as jose_jwk
from jose.exceptions import JOSEError

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_DEV_SECRET = "dev_secret_change_in_production"

# Roles this product understands at the security layer.
KNOWN_ROLES = {"admin", "tenant_admin", "team_lead", "member", "viewer", "api_service", "bot"}

# Normalize DB/product role names onto security-layer roles.
ROLE_ALIASES = {
    "admin": "admin",
    "tenant_admin": "admin",
    "team_lead": "member",
    "member": "member",
    "viewer": "viewer",
    "api_service": "bot",
    "bot": "bot",
}


class AuthError(Exception):
    """Raised when a token cannot be trusted."""


@dataclass
class VerifiedToken:
    tenant_id: str
    user_id: str
    role: str = "member"
    claims: Dict[str, Any] = field(default_factory=dict)


def auth_mode() -> str:
    """'clerk' when Clerk credentials are present, otherwise 'local'."""
    if getattr(settings, "CLERK_SECRET_KEY", None) and (
        getattr(settings, "CLERK_ISSUER", None) or getattr(settings, "CLERK_JWKS_URL", None)
    ):
        return "clerk"
    return "local"


def assert_production_secret() -> None:
    """Refuse to run production with the shipped default secret."""
    if settings.ENVIRONMENT.lower() in {"production", "prod"}:
        secret = getattr(settings, "JWT_SECRET", "")
        if not secret or secret == DEFAULT_DEV_SECRET:
            raise RuntimeError(
                "JWT_SECRET must be set to a strong unique value in production. "
                "Refusing to start with the default development secret."
            )


_jwks_cache: Dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 3600


async def _get_signing_key(token: str):
    """Fetch and cache the Clerk JWKS, select the key matching the token kid."""
    issuer = settings.CLERK_JWKS_URL or f"{settings.CLERK_ISSUER.rstrip('/')}/.well-known/jwks.json"
    now = time.time()
    if _jwks_cache["keys"] is None or now - _jwks_cache["fetched_at"] > _JWKS_TTL_SECONDS:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(issuer)
            resp.raise_for_status()
            _jwks_cache["keys"] = resp.json().get("keys", [])
            _jwks_cache["fetched_at"] = now

    try:
        header = jose_jwt.get_unverified_header(token)
    except JOSEError as e:
        raise AuthError(f"Malformed token header: {e}")

    kid = header.get("kid")
    for key_data in _jwks_cache["keys"]:
        if key_data.get("kid") == kid:
            return jose_jwk.construct(key_data)

    raise AuthError("No matching signing key found in JWKS")


async def verify_access_token(token: str) -> VerifiedToken:
    """
    Verify a bearer token and return its identity claims.
    Raises AuthError for anything untrusted.
    """
    mode = auth_mode()

    try:
        if mode == "clerk":
            key = await _get_signing_key(token)
            claims = jose_jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                options={"verify_aud": False},
                audience=None,
            )
            tenant_id = claims.get("org_id") or claims.get("tenant_id")
            user_id = claims.get("sub")
            meta = claims.get("metadata") or claims.get("public_metadata") or {}
            role = claims.get("role") or (meta.get("role") if isinstance(meta, dict) else None) or "member"
        else:
            secret = getattr(settings, "JWT_SECRET", "")
            if not secret:
                raise AuthError("JWT_SECRET is not configured")
            claims = jose_jwt.decode(
                token,
                secret,
                algorithms=["HS256"],  # alg whitelist; 'none'/RS never accepted
                options={"require_exp": True, "verify_exp": True},
            )
            # Never accept tokens minted with the well-known dev secret
            # outside of local development.
            if secret == DEFAULT_DEV_SECRET and settings.ENVIRONMENT.lower() not in {
                "development", "dev", "local", "test", ""
            }:
                raise AuthError("Default dev secret cannot authenticate in this environment")

            tenant_id = claims.get("tenant_id")
            user_id = claims.get("sub") or claims.get("user_id")
            role = claims.get("role") or "member"

        if not tenant_id or not user_id:
            raise AuthError("Token missing tenant or subject claim")

        role_norm = ROLE_ALIASES.get(str(role).lower(), "member")
        return VerifiedToken(
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            role=role_norm,
            claims=claims,
        )

    except AuthError:
        raise
    except JOSEError as e:
        raise AuthError(f"Invalid token: {e}")
    except Exception as e:
        raise AuthError(f"Token verification failed: {e}")


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer "):].strip()
    return token or None
