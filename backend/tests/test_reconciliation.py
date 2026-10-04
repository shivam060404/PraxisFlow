from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.integrations.asana import AsanaAdapter
from app.integrations.base import IntegrationConfig
from app.integrations.jira import JiraAdapter
from app.integrations.linear import LinearAdapter


CONFIG = IntegrationConfig(
    provider="test",
    display_name="test",
    config={"access_token": "token", "base_url": "https://jira.example"},
)


def task(external_id="EXT-1"):
    return SimpleNamespace(external_id=external_id)


@pytest.mark.asyncio
async def test_jira_reconciliation_normalizes_status():
    response = httpx.Response(200, json={"key": "PROJ-1", "fields": {"status": {"name": "In Progress"}}})

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return response

    adapter = JiraAdapter()
    adapter._get_client = lambda config: Client()
    state = await adapter.reconcile_task(CONFIG, task("PROJ-1"))
    assert state["status"] == "in_progress"
    assert state["external_url"].endswith("/browse/PROJ-1")


@pytest.mark.asyncio
async def test_asana_reconciliation_treats_404_as_missing():
    adapter = AsanaAdapter()
    request = httpx.Request("GET", "https://app.asana.com/api/1.0/tasks/123")
    response = httpx.Response(404, request=request)
    adapter._make_request = AsyncMock(side_effect=httpx.HTTPStatusError("missing", request=request, response=response))

    state = await adapter.reconcile_task(CONFIG, task("123"))
    assert state == {"missing": True, "external_id": "123"}


@pytest.mark.asyncio
async def test_linear_reconciliation_preserves_rate_or_provider_errors():
    adapter = LinearAdapter()
    adapter._execute_query = AsyncMock(return_value={"errors": [{"message": "rate limit exceeded"}]})

    with pytest.raises(RuntimeError, match="reconciliation failed"):
        await adapter.reconcile_task(CONFIG, task("ENG-1"))
