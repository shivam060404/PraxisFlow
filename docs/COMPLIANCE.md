# PraxisFlow Compliance Framework
# EU AI Act, GDPR, SOC 2, ISO 27001 Implementation Guide

---

## 1. EU AI Act Compliance (Mandatory: August 2, 2026)

### 1.1 Risk Classification
PraxisFlow is classified as a **High-Risk AI System** under Annex III:
- AI systems intended to be used for recruitment or selection of natural persons
- AI systems for making decisions on promotion and termination of work-related contractual relationships
- AI systems for monitoring and evaluating work performance and behavior

### 1.2 Compliance Requirements Mapping

| EU AI Act Article | Requirement | PraxisFlow Implementation | Status |
|-------------------|-------------|--------------------------|--------|
| **Art. 9** | Risk Management System | AI Risk Register with quarterly reviews, incident tracking, mitigation procedures | ✅ Implemented |
| **Art. 10** | Data Governance | Data lineage tracking, consent management, DPA with sub-processors, PII redaction pipeline | ✅ Implemented |
| **Art. 11** | Technical Documentation | Model cards, system architecture docs, data flow diagrams, guardrail configs | ✅ Implemented |
| **Art. 12** | Record Keeping | Immutable AI audit log (every LLM call), trace retention 7 years, tamper-evident storage | ✅ Implemented |
| **Art. 13** | Transparency | User-facing AI disclosure, extraction confidence display, human review queue visibility | ✅ Implemented |
| **Art. 14** | Human Oversight | HITL verification (confidence < 0.9), reviewer assignment, override capability, SLA tracking | ✅ Implemented |
| **Art. 15** | Accuracy, Robustness, Cybersecurity | Continuous evals, adversarial testing, drift detection, pen testing, vulnerability management | 🟡 In Progress |
| **Art. 16** | Obligations of Providers | Quality management, post-market monitoring, incident reporting (72h), conformity assessment | ✅ Implemented |

### 1.3 Conformity Assessment
- **Internal Control**: Self-assessment with documented QMS
- **Notified Body**: Required for biometric/credit scoring - NOT applicable to PraxisFlow
- **CE Marking**: Applied after successful assessment
- **Declaration of Conformity**: Maintained and available to authorities

### 1.4 Post-Market Monitoring
- Continuous accuracy monitoring via Langfuse evals
- Hallucination rate tracking (< 2% threshold)
- User feedback collection via HITL review queue
- Incident reporting workflow (72-hour notification)
- Annual reassessment trigger

---

## 2. GDPR Compliance

### 2.1 Lawful Basis
| Processing Activity | Lawful Basis | Implementation |
|---------------------|--------------|----------------|
| Meeting transcription | Legitimate interest (business operations) | Opt-in consent at recording start |
| Task extraction | Legitimate interest | Transparent AI processing notice |
| PII redaction | Legal obligation (data minimization) | Automated Presidio pipeline |
| Audit logging | Legal obligation (accountability) | Immutable append-only log |
| Integration sync | Contract performance | User-initiated, explicit consent |

### 2.2 Data Subject Rights Implementation

| Right | Implementation | API Endpoint | SLA |
|-------|---------------|--------------|-----|
| **Access (Art. 15)** | Export all tenant data (JSON/CSV) | `GET /api/v1/compliance/export` | 30 days |
| **Rectification (Art. 16)** | Update/correct meeting data, tasks | `PATCH /api/v1/meetings/{id}`, `PATCH /api/v1/tasks/{id}` | 30 days |
| **Erasure (Art. 17)** | Cascade delete: audio → transcript → embeddings → tasks → audit | `DELETE /api/v1/compliance/erase-tenant` | 30 days |
| **Restriction (Art. 18)** | Processing freeze flag on tenant/meeting | `POST /api/v1/compliance/restrict` | Immediate |
| **Portability (Art. 20)** | Standardized export format (JSON/CSV) | `GET /api/v1/compliance/export` | 30 days |
| **Object (Art. 21)** | Opt-out from AI processing, manual review only | `POST /api/v1/compliance/opt-out` | Immediate |

### 2.3 Data Protection Impact Assessment (DPIA)
- **Completed**: Yes (high-risk processing: AI + employee monitoring)
- **Review Cycle**: Annual or on significant changes
- **Key Risks Identified**:
  1. Automated decision-making affecting employment (mitigated: HITL required)
  2. Cross-border data transfers (mitigated: EU region locking)
  3. PII exposure in LLM prompts (mitigated: Presidio redaction + guardrails)

### 2.4 Data Processing Agreements (DPAs)
| Sub-processor | Purpose | DPA Status | Location |
|---------------|---------|------------|----------|
| Deepgram | ASR transcription | ✅ Signed | US/EU regions |
| Groq | LLM inference (primary) | ✅ Signed | US |
| OpenAI | LLM inference (fallback) | ✅ Signed | US |
| Anthropic | LLM inference (fallback) | ✅ Signed | US |
| AWS | Infrastructure | ✅ Signed | Global regions |
| Pinecone/Qdrant | Vector storage | ✅ Signed | US/EU |

### 2.5 International Transfers
- **Standard Contractual Clauses (SCCs)**: In place for all non-EU subprocessors
- **Transfer Impact Assessments**: Completed for US transfers post-Schrems II
- **EU Data Residency**: Dedicated eu-west-1 region for EU tenants
- **No adequacy decision reliance**: SCCs + supplementary measures

---

## 3. SOC 2 Type II Controls

### 3.1 Trust Service Criteria Mapping

| TSC | Control | Implementation | Evidence |
|-----|---------|----------------|----------|
| **CC1.1** | Control Environment | Code of conduct, org structure, competence management | Employee handbook, org chart |
| **CC1.2** | Communication | Security policies, incident communication, vendor management | Policy docs, vendor contracts |
| **CC2.1** | Risk Assessment | Annual risk assessment, threat modeling, vendor risk scoring | Risk register, threat models |
| **CC2.2** | Fraud Risk | Background checks, access reviews, anomaly detection | HR records, audit logs |
| **CC3.1** | Control Activities | RBAC, encryption, backup, change management | Config, runbooks, test results |
| **CC3.2** | IT Controls | SDLC, deployment pipeline, monitoring, incident response | CI/CD config, runbooks |
| **CC4.1** | Monitoring | Continuous monitoring, SIEM, alerting, quarterly reviews | Grafana, PagerDuty, review notes |
| **CC4.2** | Deficiency Remediation | Incident management, root cause analysis, corrective actions | Incident tickets, RCA docs |
| **CC5.1** | Control Activities | Automated controls (RBAC, encryption), manual reviews | Test results, configs |
| **CC6.1** | Logical Access | RBAC/ABAC, MFA, session management, IP allowlists | IAM configs, access reviews |
| **CC6.2** | Access Provisioning | Automated onboarding/offboarding, quarterly access reviews | HR integration, review records |
| **CC6.3** | Network Security | VPC, security groups, WAF, mTLS, network segmentation | Network diagrams, configs |
| **CC6.4** | Data Protection | Encryption at rest/transit, key management, DLP | KMS configs, DLP rules |
| **CC6.5** | Physical Security | AWS/Azure/GCP data center controls | CSP SOC 2 reports |
| **CC6.6** | Encryption | AES-256 at rest, TLS 1.3 in transit, envelope encryption | Key management docs |
| **CC6.7** | Data Transmission | TLS 1.3, certificate management, API security | Cert configs, API gateway |
| **CC6.8** | System Access | Break-glass procedures, privileged access management | PAM configs, access logs |
| **CC7.1** | System Monitoring | Infrastructure + application monitoring, log aggregation | Prometheus, CloudWatch, ELK |
| **CC7.2** | Monitoring Controls | Alerting thresholds, runbooks, escalation policies | Alert configs, runbooks |
| **CC7.3** | Change Detection | FIM, config drift detection, deployment tracking | Drift detection, deploy logs |
| **CC7.4** | Incident Response | IR plan, runbooks, communication plan, post-mortems | IR plan, incident tickets |
| **CC8.1** | Change Management | CI/CD with approval gates, rollback capability, testing | Pipeline config, test results |
| **CC9.1** | Risk Mitigation | Vendor management, BCP/DR, insurance | Vendor assessments, DR test results |
| **A1.1** | Availability | 99.9% SLA, multi-AZ, auto-scaling, health checks | SLA docs, architecture diagrams |
| **A1.2** | Capacity Management | Auto-scaling, capacity planning, performance testing | Scaling configs, load test results |
| **A1.3** | Backup & Recovery | RPO < 5min, RTO < 1hr, automated backups, DR drills | Backup configs, DR test results |
| **PI1.1** | Processing Integrity | Input validation, output verification, reconciliation | Validation rules, audit trails |
| **PI1.2** | Error Handling | Retry logic, dead letter queues, error alerting | Retry configs, DLQ monitoring |
| **PI1.3** | Data Quality | Schema validation, completeness checks, anomaly detection | Validation rules, quality metrics |

### 3.2 Control Implementation Evidence
- **Automated Controls**: Tested via CI/CD (RBAC, encryption, validation)
- **Manual Controls**: Quarterly review with evidence collection
- **Continuous Monitoring**: Real-time dashboards with alerting
- **Annual Assessment**: Third-party auditor (scheduled Q1 annually)

---

## 4. ISO 27001 Alignment

### 4.1 Annex A Control Mapping

| Control | Description | Implementation |
|---------|-------------|----------------|
| **A.5.1** | Information security policies | Documented, approved, communicated, reviewed annually |
| **A.6.1** | Internal organization | Roles defined (CISO, DPO, Security Engineer), segregation of duties |
| **A.6.2** | Mobile devices | MDM policy, encryption, remote wipe capability |
| **A.7.1** | Prior to employment | Background checks, NDAs, security training |
| **A.7.2** | During employment | Annual security awareness, phishing simulations, access reviews |
| **A.7.3** | Termination | Immediate access revocation, exit interviews, asset return |
| **A.8.1** | Asset inventory | CMDB with all assets, ownership, classification |
| **A.8.2** | Information classification | Data classification schema (Public, Internal, Confidential, Restricted) |
| **A.8.3** | Media handling | Encryption, secure disposal, chain of custody |
| **A.9.1** | Access control policy | RBAC/ABAC, least privilege, need-to-know |
| **A.9.2** | User access management | Lifecycle management, periodic review, privileged access control |
| **A.9.3** | User responsibilities | Password policy, MFA, clean desk, reporting obligations |
| **A.9.4** | System/application access | Secure logon, password management, session timeout |
| **A.10.1** | Cryptographic controls | AES-256, TLS 1.3, key lifecycle management (HSM/KMS) |
| **A.11.1** | Physical security | CSP responsibility (AWS/Azure/GCP), office access control |
| **A.12.1** | Operational procedures | Documented runbooks, change management, capacity management |
| **A.12.2** | Malware protection | EDR on endpoints, container scanning, dependency scanning |
| **A.12.3** | Backup | Automated, encrypted, tested, off-site, RPO/RTO documented |
| **A.12.4** | Logging & monitoring | Centralized logging, SIEM, alerting, log retention (7 years) |
| **A.12.5** | Technical vulnerability management | Monthly scanning, patch SLA (critical: 72h, high: 14d) |
| **A.13.1** | Network security | Segmentation, firewall rules, IDS/IPS, DDoS protection |
| **A.13.2** | Information transfer | Encryption, DPA with carriers, secure file transfer |
| **A.14.1** | Secure development | SDLC with security gates, SAST/DAST/SCA, threat modeling |
| **A.14.2** | System testing | Unit, integration, contract, security, performance, chaos |
| **A.15.1** | Supplier relationships | Vendor risk assessment, DPA, SLA, continuous monitoring |
| **A.16.1** | Incident management | IR plan, classification, escalation, evidence preservation |
| **A.17.1** | Business continuity | BCP/DRP, RTO/RPO, annual testing, alternate processing |
| **A.18.1** | Compliance | Legal register, regulatory monitoring, audit program |

### 4.2 Statement of Applicability (SoA)
- **Scope**: All AI Meeting Intelligence platform services
- **Exclusions**: None (all Annex A controls applicable)
- **Risk Treatment**: Documented in Risk Treatment Plan
- **Review**: Annual or on significant change

---

## 5. Implementation Checklist

### 5.1 Immediate (Pre-Launch)
- [x] AI Risk Register documented
- [x] Data Processing Agreements with all subprocessors
- [x] DPIA completed and approved
- [x] PII redaction pipeline operational
- [x] Immutable audit logging implemented
- [x] Human-in-the-loop verification active
- [x] Data residency controls (EU region)
- [x] Encryption at rest and in transit
- [x] RBAC/ABAC with OPA policy engine
- [x] Rate limiting and circuit breakers
- [x] Vulnerability scanning in CI/CD
- [x] Incident response plan documented
- [x] Disaster recovery plan tested
- [x] Penetration test scheduled

### 5.2 Ongoing (Post-Launch)
- [ ] Monthly: AI accuracy monitoring (hallucination rate, faithfulness)
- [ ] Monthly: Vulnerability scan review and patching
- [ ] Quarterly: Access review (user roles, permissions)
- [ ] Quarterly: AI risk register review
- [ ] Quarterly: Vendor risk assessment
- [ ] Semi-annually: Penetration testing
- [ ] Annually: SOC 2 Type II audit
- [ ] Annually: ISO 27001 surveillance audit
- [ ] Annually: GDPR compliance review
- [ ] Annually: EU AI Act conformity reassessment
- [ ] Annually: Disaster recovery drill
- [ ] Annually: Security awareness training completion

### 5.3 Documentation Repository
```
docs/compliance/
├── ai-risk-register.md
├── dpia-report.md
├── dpa-inventory.md
├── model-cards/
│   ├── llama-3.3-70b.md
│   ├── gpt-4o.md
│   └── claude-sonnet-4.md
├── audit-log-spec.md
├── incident-response-plan.md
├── disaster-recovery-plan.md
├── business-continuity-plan.md
├── vendor-risk-assessments/
├── penetration-test-reports/
├── soc2-evidence/
├── iso27001-evidence/
└── gdpr-compliance-evidence/
```

---

## 6. Regulatory Contacts

| Regulation | Authority | Contact | Notification Timeline |
|------------|-----------|---------|----------------------|
| EU AI Act | National Competent Authority | Varies by member state | 72 hours (serious incidents) |
| GDPR | Lead Supervisory Authority | Data Protection Commission (Ireland) | 72 hours |
| SOC 2 | AICPA | Licensed CPA firm | Annual |
| ISO 27001 | Accredited Certification Body | BSI/SAI Global/etc. | Annual surveillance |
| CCPA | California AG | California Attorney General | 72 hours (breach) |

---

## 7. Compliance Dashboard Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| AI Hallucination Rate | < 2% | - | 🟡 Monitoring |
| HITL Review SLA (< 4h) | 100% | - | 🟡 Monitoring |
| Data Subject Request SLA | 30 days | - | 🟡 Monitoring |
| Vulnerability Patch SLA (Critical) | 72 hours | - | 🟡 Monitoring |
| System Uptime | 99.9% | - | 🟡 Monitoring |
| Backup Success Rate | 100% | - | 🟡 Monitoring |
| DR Drill Success | 100% | - | 🟡 Annual |
| Access Review Completion | 100% | - | 🟡 Quarterly |
| Security Training Completion | 100% | - | 🟡 Annual |

---

*Document Version: 2.0 | Last Updated: July 2026 | Classification: Internal - Confidential*
*Next Review: October 2026 | Owner: Security & Compliance Team*