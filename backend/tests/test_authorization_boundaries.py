import asyncio

import pytest

from app.security.base import (
    Action,
    AuthorizationService,
    Permission,
    Resource,
    Role,
    Subject,
)


def test_cross_tenant_owner_cannot_bypass_isolation():
    async def check():
        service = AuthorizationService()
        subject = Subject(id="user-1", tenant_id="tenant-a", roles=[])
        resource = Resource(
            type="task",
            id="task-1",
            tenant_id="tenant-b",
            owner_id="user-1",
        )

        return await service.authorize(
            subject,
            resource,
            Action(permission=Permission.TASK_UPDATE),
        )

    decision = asyncio.run(check())
    assert decision.allowed is False
    assert decision.reason == "Cross-tenant access denied"


def test_unconfigured_abac_policy_fails_closed():
    async def check():
        from app.security.base import ABACManager

        return await ABACManager().evaluate(
            Subject(id="user-1", tenant_id="tenant-a", roles=[Role.MEMBER]),
            Resource(type="task", id="task-1", tenant_id="tenant-a"),
            Action(permission=Permission.TASK_READ),
            policies=[],
        )

    decision = asyncio.run(check())
    assert decision.allowed is False
