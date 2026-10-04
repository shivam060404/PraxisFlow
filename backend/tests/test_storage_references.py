from unittest.mock import MagicMock

import pytest

from app.services.storage import StorageService


@pytest.mark.asyncio
async def test_delete_file_accepts_durable_bucket_object_reference(monkeypatch):
    service = object.__new__(StorageService)
    service.client = MagicMock()

    assert await service.delete_file("audio/tenant/meeting/recording.webm")
    service.client.remove_object.assert_called_once_with(
        "audio", "tenant/meeting/recording.webm"
    )


@pytest.mark.asyncio
async def test_delete_file_keeps_legacy_url_support(monkeypatch):
    service = object.__new__(StorageService)
    service.client = MagicMock()

    assert await service.delete_file(
        "https://minio.example.test/transcripts/tenant/meeting.json"
    )
    service.client.remove_object.assert_called_once_with(
        "transcripts", "tenant/meeting.json"
    )
