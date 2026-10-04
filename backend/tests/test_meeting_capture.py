from app.services.meeting_capture import normalize_capture_event, verify_capture_signature


def test_normalizes_recall_recording_ready_event():
    event = normalize_capture_event(
        {
            "data": {
                "bot_id": "bot-123",
                "status": "recording_ready",
                "recording_url": "s3://recordings/meeting.mp4",
            }
        }
    )

    assert event["external_bot_id"] == "bot-123"
    assert event["status"] == "COMPLETED"
    assert event["recording_url"].endswith("meeting.mp4")


def test_capture_signature_requires_exact_body():
    body = b'{"status":"completed"}'
    import hmac
    import hashlib

    signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_capture_signature(body, f"sha256={signature}", "secret")
    assert not verify_capture_signature(body + b" ", f"sha256={signature}", "secret")
