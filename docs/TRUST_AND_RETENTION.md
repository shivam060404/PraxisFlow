# Trust, retention, and redaction boundaries

Tenant settings now define:

- `dataRegion`
- `kmsKeyArn`
- `retentionDays`
- `recordingConsentRequired`
- `phiProcessingEnabled`

These values are tenant-owned policy inputs. `kmsKeyArn` is a reference to a
customer-managed AWS KMS key; key provisioning, grants, rotation, and regional
AWS policy must be completed in deployment infrastructure before enabling
customer-managed encryption for a production tenant.

Ambient capture scheduling requires explicit meeting consent. The bot scheduler
only selects meetings whose `consentStatus` is `granted`; consent can be
recorded through:

```http
POST /api/v1/meetings/{meeting_id}/consent
```

Transcript PII redaction is fail-closed. If Presidio is unavailable or throws,
transcription fails instead of persisting or sending unredacted content to the
LLM pipeline. Custom recognizers cover medical record and NPI/license
identifiers in addition to standard PII entities.

Celery Beat runs `enforce_retention_policies` daily. For each tenant it removes
expired transcript rows and associated audio objects according to
`retentionDays`, while retaining task and AI audit records for the configured
audit-retention period.

SOC 2, HIPAA, BAA, residency, and KMS controls require external AWS/provider
configuration and legal agreements; code-level policy fields are not evidence
that those controls are certified.
