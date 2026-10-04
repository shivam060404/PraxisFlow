import pytest
import asyncio

from app.clients.llm_gateway.budgets import TokenBudgetManager


@pytest.mark.asyncio
async def test_record_usage_supports_legacy_two_argument_shape():
    manager = TokenBudgetManager()
    manager._initialized = True

    await manager.record_usage("tenant-1", 25)

    assert manager.budgets["tenant:tenant-1"].used_tokens == 25


@pytest.mark.asyncio
async def test_record_usage_rejects_negative_tokens():
    manager = TokenBudgetManager()
    manager._initialized = True

    with pytest.raises(ValueError):
        await manager.record_usage("tenant", "tenant-1", -1)


@pytest.mark.asyncio
async def test_monthly_reservation_is_atomic_and_settlement_replaces_hold():
    manager = TokenBudgetManager()
    manager._initialized = True

    results = await asyncio.gather(*(
        manager.reserve_monthly_cost("tenant", 1.0, 0.60)
        for _ in range(2)
    ))

    assert results == [True, False]
    await manager.settle_monthly_cost("tenant", 0.60, 0.25)
    assert await manager.reserve_monthly_cost("tenant", 1.0, 0.75) is True


@pytest.mark.asyncio
async def test_monthly_reservation_rejects_negative_values():
    manager = TokenBudgetManager()
    manager._initialized = True

    with pytest.raises(ValueError):
        await manager.reserve_monthly_cost("tenant", 1.0, -0.01)
