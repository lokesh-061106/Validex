# SIH26262 requirement-to-feature mapping

The repository README labels itself SIH26261; this project work follows the user-provided SIH26262 label. Official/legal thresholds must be verified by an authorized subject-matter reviewer.

| Requirement | Existing implementation | Status / limitation |
|---|---|---|
| Identity, roles, tenant boundaries | `backend/app/api/auth.py`, `core/dependencies.py`, user model | Present; baseline authorization tests blocked by missing dependencies. |
| Application intake and workflow | `api/applications.py`, `api/workflow.py`, `models/workflow_transition.py` | Draft/submit/clarification/decision plus admin-configurable, persisted status edges and role policies. Final decision authority and evidence blockers remain independently enforced. |
| Evidence intake and review | `api/documents.py`, `services/document_service.py`, `services/custody_service.py` | Present; OCR and forensic outputs are advisory. |
| Compliance monitoring | `services/rule_engine.py`, `api/compliance.py`, `ComplianceRule` | Configurable/versioned, evidence-linked; handbook references/thresholds need validation. |
| AICTE registry / issuing authorities | `services/connectors.py`, `mock_authority/` | Simulated by default; no production official credentials/interfaces supplied. |
| Signed QR generation and verification | `POST /api/verification/demo-qr`, `ml/qr_verifier.py`, `services/verification_service.py` | Generates a real PNG QR and verifies it server-side with deterministic demo keys; production endpoint is disabled. This is explicitly simulated issuer signing, not an official credential or AICTE verification. |
| Clarification and resubmission | `api/applications.py`, `services/notification_service.py`, secure inbox | Encrypted institution requests and resubmission; notification UI is not push-based. |
| EVC scheduling and undertakings | `models/deadline.py`, `/api/deadlines`, Deadlines & EVC UI | Implemented as application-scoped persistent records; EVC is official-scheduled, institution can register undertakings. Requires live app verification. |
| Lease/document expiry and reminders | Deadline kinds `lease_expiry` and `document_expiry`; configurable reminder window | Implemented for explicitly recorded expiry dates; existing compliance rules also check extracted document dates. Automatic extraction-to-deadline creation is not yet implemented. |
| Escalation | `services/deadline_service.py`; Celery beat every 5 minutes; manual sweep API | Persisted reminder flag and escalation level avoid repeated alerts; overdue escalation notifies assigned recipient plus active scrutiny/admin users. SQLite concurrent-worker locking needs operational caution. |
| Email | Optional SMTP in `services/notification_service.py` | SMTP send can be attempted with config; no recipient delivery confirmation/status. |
| In-app notifications | `Notification` model/API; Header polls every 30 seconds | Persisted and recipient-filtered; polling rather than push/WebSocket delivery. |
| Dashboards and reporting | `dashboard_service.py`, `/api/dashboard/report.csv`, frontend dashboard | Live database metrics and CSV export with optional date/status/search filters; no PDF export. |
| Audit history | `audit_service.py`, `api/audit.py` | Hash-linked persistent events and verify endpoint; not externally anchored. |
| Official-style UI | Existing React portal and officer console | Visual alignment not yet checked against live AICTE reference; Validex must remain clearly independent. |
| Baseline QA | pytest/build/lint commands attempted | Frontend build/lint pass; 28 backend unit tests pass. Full HTTP suite is blocked by a TestClient startup hang, documented in the audit. |

See [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md) and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for audit details and sequenced work.
