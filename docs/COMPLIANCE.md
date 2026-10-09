# Compliance engineering inventory

This document describes engineering evidence present in this repository. It is
not a legal assessment, compliance certification, or claim that an organization
has completed the required governance work. The previous version asserted
controls such as signed DPAs, completed DPIAs, immutable logs, regional data
residency, SOC 2 controls, and ISO 27001 controls without repository evidence;
those claims have been removed.

## Controls implemented in code or deployment configuration

| Area | Repository evidence | Limit |
|---|---|---|
| Tenant isolation | Runtime Prisma operations bind a verified tenant to PostgreSQL RLS; API and Celery paths carry tenant context. | The SQL and role path still need integration tests against a real PostgreSQL instance and two tenants. |
| Transcript PII handling | Presidio redaction runs before transcript persistence; production refuses to persist on redaction failure. | Detection quality, languages, provider-side handling, and retention require separate validation. |
| Human review | LangGraph interrupts are persisted in PostgreSQL; decisions require an authenticated reviewer and are recorded with the resulting task transaction. | No reviewer SLA, escalation, or independent review of the policy thresholds is established. |
| AI audit records | Extraction and human decisions create database audit records. | PostgreSQL records are not immutable or tamper-evident storage. Retention is not scheduled. |
| Data subject workflows | Tenant-scoped request/export/erasure endpoints exist in the API. | Their end-to-end effects across object storage, vector data, integrations, logs, and backups need a verified deletion exercise. |
| Network entry | The Compose reference publishes Nginx only; TLS requires operator-provided certificates. | Host firewall, certificate rotation, DNS, and deployment-specific network controls remain operator responsibilities. |
| Database backups | A daily job writes a logical dump to a configured off-host S3-compatible bucket. | No restore drill, RPO, or RTO has been demonstrated. |
| AI quality evaluation | A five-case synthetic gold set, absolute thresholds, and prior-report comparison are available. | The corpus is not representative, the live evaluation has not been run here, and no approved baseline is committed. |

## Organization-level evidence still required

- Determine the applicable legal classification and obligations with qualified
  counsel for each intended use and deployment jurisdiction.
- Establish lawful basis, notice/consent practices, retention schedules,
  processor agreements, transfer assessments, and data residency commitments.
- Complete and approve the required risk and impact assessments; maintain
  named owners, review dates, incident procedures, and post-deployment reviews.
- Obtain independent security testing and verify access controls, secrets
  handling, encryption, deletion, backup isolation, and incident response.
- Do not describe this repository as SOC 2 or ISO 27001 certified or audited.

## Release evidence to collect

1. Run a two-tenant RLS integration exercise through both API and Celery paths.
2. Run upload, redaction, extraction, persisted interrupt, reviewer resume, and
   retry scenarios against staging services.
3. Complete and record a restore drill from the off-host backup, including
   LangGraph checkpoints and tenant boundaries.
4. Expand and adjudicate the evaluation corpus, establish a reviewed baseline,
   and retain evaluation reports for each prompt/model release.
5. Review dependency/image versions and make security scans release-blocking.
