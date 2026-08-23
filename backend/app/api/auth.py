"""
Authentication endpoints.

/dev-token exists ONLY to make local development usable: the dashboard needs
a bearer token and there is no Clerk instance in dev. It is hard-gated to
development environments and refuses to exist anywhere else.
"""

import time
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from app.core.config import settings
from app.db.prisma import get_db
from app.security.auth import DEFAULT_DEV_SECRET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

_DEV_ENVIRONMENTS = {"development", "dev", "local", "test", ""}


class DevTokenRequest(BaseModel):
    # Deliberately a plain string: seeded dev users use admin@dev.local, which
    # EmailStr/email-validator rejects as a reserved TLD.
    email: str
    expires_in_seconds: int = 43200  # 12h max

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v or ""):
            raise ValueError("must look like an email address")
        return v.lower().strip()


class DevTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    tenant_id: str
    role: str


def _dev_auth_enabled() -> bool:
    return (
        settings.ENVIRONMENT.lower() in _DEV_ENVIRONMENTS
        and auth_mode_is_local()
    )


def auth_mode_is_local() -> bool:
    from app.security.auth import auth_mode

    return auth_mode() == "local"


@router.post("/dev-token", response_model=DevTokenResponse)
async def issue_dev_token(
    body: DevTokenRequest,
    db=Depends(get_db),
):
    """Mint a local HS256 token for a seeded user (DEVELOPMENT ONLY)."""
    if not _dev_auth_enabled():
        # 404 rather than 403: don't advertise the endpoint's existence
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    user = await db.user.find_first(
        where={
            "email": body.email,
            "status": {"not": "DELETED"},
        }
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown user. Run scripts/seed_dev.py first.",
        )

    from jose import jwt

    expires_in = max(60, min(body.expires_in_seconds, 86400))
    token = jwt.encode(
        {
            "sub": user.id,
            "tenant_id": user.tenantId,
            "role": user.role,
            "iat": int(time.time()),
            "exp": int(time.time()) + expires_in,
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )

    logger.info(f"Dev token issued for {user.email} (tenant {user.tenantId})")
    return DevTokenResponse(
        access_token=token,
        expires_in=expires_in,
        user_id=user.id,
        tenant_id=user.tenantId,
        role=user.role,
    )
