"""Tenant-scoped calendar connection and synchronization API."""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.prisma import get_db
from app.security import Subject, get_current_subject, require_permission, Permission
from app.services.calendar_sync import upsert_calendar_event
from app.services.calendar_oauth import (
    authorization_url, default_secret_store, exchange_code, fetch_calendar_delta,
    refresh_access_token, validate_oauth_state, validate_secret_reference,
)
from app.core.config import settings
import httpx

router = APIRouter(prefix="/calendar", tags=["Calendar"])


class CalendarConnectionCreate(BaseModel):
    provider: str = Field(pattern="^(google|microsoft)$")
    external_account: str = Field(min_length=1, max_length=320)
    access_token_ref: str = Field(min_length=1, max_length=500)
    refresh_token_ref: str | None = Field(default=None, max_length=500)

    def validate_refs(self):
        validate_secret_reference(self.access_token_ref, required=True)
        validate_secret_reference(self.refresh_token_ref)


class CalendarEventSync(BaseModel):
    event: dict[str, Any]


@router.post("/connections")
async def create_connection(
    data: CalendarConnectionCreate,
    subject: Subject = Depends(require_permission(Permission.INTEGRATION_CREATE)),
    db=Depends(get_db),
):
    data.validate_refs()
    return await db.calendarconnection.upsert(
        where={
            "tenantId_provider_externalAccount": {
                "tenantId": subject.tenant_id,
                "provider": data.provider,
                "externalAccount": data.external_account,
            }
        },
        data={
            "create": {
                "tenantId": subject.tenant_id,
                "provider": data.provider,
                "externalAccount": data.external_account,
                "accessTokenRef": data.access_token_ref,
                "refreshTokenRef": data.refresh_token_ref,
            },
            "update": {
                "accessTokenRef": data.access_token_ref,
                "refreshTokenRef": data.refresh_token_ref,
                "status": "ACTIVE",
            },
        },
    )


@router.get("/oauth/{provider}/authorize")
async def begin_oauth(provider: str, external_account: str,
                      subject: Subject = Depends(require_permission(Permission.INTEGRATION_CREATE))):
    if provider not in ("google", "microsoft"):
        raise HTTPException(status_code=400, detail="Unsupported calendar provider")
    return {"authorization_url": authorization_url(
        provider, tenant_id=subject.tenant_id, external_account=external_account,
        redirect_uri=settings.CALENDAR_REDIRECT_URI,
    )}


@router.get("/oauth/callback")
async def oauth_callback(code: str, state: str, db=Depends(get_db)):
    oauth_state = None
    for provider in ("google", "microsoft"):
        try:
            oauth_state = validate_oauth_state(state, provider=provider)
            break
        except ValueError:
            continue
    if not oauth_state:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            tokens = await exchange_code(oauth_state.provider, code=code,
                                         redirect_uri=settings.CALENDAR_REDIRECT_URI, client=client)
        if not tokens.get("access_token"):
            raise ValueError("OAuth provider returned no access token")
        store = default_secret_store()
        access_ref = await store.store(tokens["access_token"], hint="calendar-access")
        refresh_ref = await store.store(tokens["refresh_token"], hint="calendar-refresh") if tokens.get("refresh_token") else None
        expires = datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
        return await db.calendarconnection.upsert(
            where={"tenantId_provider_externalAccount": {
                "tenantId": oauth_state.tenant_id, "provider": oauth_state.provider,
                "externalAccount": oauth_state.external_account}},
            data={"create": {"tenantId": oauth_state.tenant_id, "provider": oauth_state.provider,
                    "externalAccount": oauth_state.external_account, "accessTokenRef": access_ref,
                    "refreshTokenRef": refresh_ref, "tokenExpiresAt": expires},
                  "update": {"accessTokenRef": access_ref, "refreshTokenRef": refresh_ref,
                    "tokenExpiresAt": expires, "status": "ACTIVE"}},
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connections/{connection_id}/events")
async def sync_event(
    connection_id: UUID,
    data: CalendarEventSync,
    subject: Subject = Depends(require_permission(Permission.INTEGRATION_SYNC)),
    db=Depends(get_db),
):
    connection = await db.calendarconnection.find_first(
        where={"id": str(connection_id), "tenantId": subject.tenant_id, "status": "ACTIVE"}
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Calendar connection not found")
    return await upsert_calendar_event(connection=connection, payload=data.event, db=db)


@router.post("/connections/{connection_id}/sync")
async def sync_connection(
    connection_id: UUID,
    subject: Subject = Depends(require_permission(Permission.INTEGRATION_SYNC)),
    db=Depends(get_db),
):
    connection = await db.calendarconnection.find_first(
        where={"id": str(connection_id), "tenantId": subject.tenant_id}
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Calendar connection not found")
    store = default_secret_store()
    try:
        access = await store.resolve(connection.accessTokenRef)
        if connection.tokenExpiresAt and connection.tokenExpiresAt <= datetime.now(timezone.utc) + timedelta(minutes=2):
            if not connection.refreshTokenRef:
                await db.calendarconnection.update(where={"id": connection.id}, data={"status": "REAUTH_REQUIRED"})
                raise HTTPException(status_code=409, detail="Calendar reauthorization required")
            async with httpx.AsyncClient(timeout=15) as client:
                tokens = await refresh_access_token(
                    str(connection.provider), refresh_token=await store.resolve(connection.refreshTokenRef), client=client
                )
            access = tokens["access_token"]
            connection = await db.calendarconnection.update(
                where={"id": connection.id},
                data={"accessTokenRef": await store.store(access, hint="calendar-access"),
                      "tokenExpiresAt": datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600))),
                      "status": "ACTIVE"},
            )
        async with httpx.AsyncClient(timeout=15) as client:
            result = await fetch_calendar_delta(str(connection.provider), access_token=access,
                                                cursor=connection.syncCursor, client=client)
        if result.reauth_required:
            await db.calendarconnection.update(where={"id": connection.id}, data={"status": "REAUTH_REQUIRED"})
            raise HTTPException(status_code=409, detail="Calendar reauthorization required")
        for event in result.events:
            await upsert_calendar_event(connection=connection, payload=event, db=db)
        for external_id in result.deleted_external_ids:
            await db.calendarevent.update_many(
                where={"connectionId": connection.id, "externalEventId": external_id},
                data={"status": "cancelled", "lastSeenAt": datetime.now(timezone.utc)},
            )
        await db.calendarconnection.update(
            where={"id": connection.id, "tenantId": subject.tenant_id},
            data={"syncCursor": result.cursor, "status": "ACTIVE"},
        )
        return {"processed": len(result.events), "deleted": result.deleted_external_ids, "cursor": result.cursor}
    except HTTPException:
        raise
    except PermissionError as exc:
        await db.calendarconnection.update(where={"id": connection.id}, data={"status": "REAUTH_REQUIRED"})
        raise HTTPException(status_code=409, detail=str(exc)) from exc
