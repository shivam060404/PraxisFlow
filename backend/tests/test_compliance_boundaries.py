from app.services.pii_redaction import PIIRedactionService


def test_medical_identifiers_are_redacted():
    service = PIIRedactionService()
    result = service.redact_text("Patient MRN: ABC12345 has NPI: 9876543210")

    assert result["has_redactions"] is True
    assert "ABC12345" not in result["text"]
    assert "9876543210" not in result["text"]
