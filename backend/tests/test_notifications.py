from types import SimpleNamespace

import pytest

from app.services.notifications import (
    _key, _summary, build_slack_payload, build_teams_payload,
    create_action_token, verify_action_token,
)


def test_notification_key_is_stable():
    assert _key("meeting-1", "email", "a@example.com") == _key(
        "meeting-1", "email", "a@example.com"
    )
    assert _key("meeting-1", "email", "a@example.com") != _key(
        "meeting-2", "email", "a@example.com"
    )


def test_summary_escapes_meeting_title():
    text, body = _summary(SimpleNamespace(id="m1", title="<script>alert(1)</script>"))
    assert "<script>" not in body
    assert "m1" in text


def test_native_payloads_include_signed_actions():
    meeting = SimpleNamespace(id="m1", tenantId="t1", title="Planning")
    task = SimpleNamespace(id="task-1", tenantId="t1", title="Ship it")
    slack = build_slack_payload(meeting, [task])
    teams = build_teams_payload(meeting, [task])
    assert any(block["type"] == "actions" for block in slack["blocks"])
    assert "AdaptiveCard" == teams["attachments"][0]["content"]["type"]
    assert "verify" in slack["blocks"][-1]["elements"][0]["url"]


def test_action_tokens_are_signed_and_expire(monkeypatch):
    monkeypatch.setattr("app.services.notifications.settings.NOTIFICATION_ACTION_SECRET", "secret")
    token = create_action_token("task", "tenant", "verify", now=100)
    assert verify_action_token(token, now=100)["task_id"] == "task"
    with pytest.raises(ValueError):
        verify_action_token(token[:-1] + "0", now=100)
    with pytest.raises(ValueError):
        verify_action_token(token, now=100 + 7 * 24 * 60 * 60 + 1)
