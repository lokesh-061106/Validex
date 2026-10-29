# Validex repository audit

Audit date: 2026-10-29. Source inspected: nested `Validex-main/` directory. No `.git` directory or `AGENTS.md` was present in the supplied workspace, so repository history and branch state could not be checked.

## Stack and layout

- Backend: Python 3.14 host, FastAPI, SQLAlchemy 2, SQLite by default/PostgreSQL optionally, Celery/Redis optional.
- Frontend: React 19, TypeScript 6, Vite 8, Tailwind 4, Oxlint.
- AI/document: PyMuPDF, OpenCV, Tesseract/EasyOCR optional, ONNX optional, RapidFuzz.
- Storage: local vault fallback or optional MinIO. External authorities are simulated unless a connector URL is configured.
- Schema: SQLAlchemy metadata plus additive `sync_schema`; Alembic has no actual revisions yet.
- Existing modules include authentication/RBAC, institution-owned applications, uploads/custody, OCR/extraction, compliance rules, signed QR validation, mocked registry lookups, clarification notices, dashboard aggregates, audit chain, and synthetic-data scripts.

## Baseline checks (before changes)

| Check | Result | Reason |
|---|---|---|
| `python -m pytest -q` in `backend/` | Not run | `pytest` is not installed (`No module named pytest`). |
| `npm run build` in `frontend/` | Not run | Frontend dependencies are not installed (`tsc` not recognized). |
| `npm run lint` in `frontend/` | Not run | Frontend dependencies are not installed (`oxlint` not recognized). |

These are environment blockers, not passing checks. Dependency installation requires network access and is outstanding.

## Findings by area

### Implemented in code (not baseline-tested here)

- Password hashing/JWT and backend role checks; institution application reads filter on institution ID.
- Draft, submit/resubmit, clarification request, review and decision endpoints; decision reasons are required in adverse/override cases.
- Evidence processing, custody verification, OCR extraction, duplicate detection and forensic/CV helpers.
- Data-driven, versioned compliance rules and stored validation findings.
- In-app encrypted clarification notices, acknowledgement, optional SMTP send, signed QR verification and connector-backed registry lookups.
- Operational dashboards derived from stored rows and an append-only hash-linked audit ledger.
- Synthetic sample generation and evaluation scripts.

### Partial or unverified

- Email helper performs SMTP submission when configured, but a successful SMTP handoff is not equivalent to recipient delivery; no delivery state is tracked. Configuration has no explicit TLS mode or delivery record.
- QR generation/signing exists in synthetic-data helpers and simulated authority code, but there is no institution/official-facing issuance endpoint. Verification proves a signature against bundled demo keys; it does not establish official issuer authority.
- Celery beat retries source verification. General deadline scheduling, overdue notices and escalations are absent.
- Compliance engine supports configurable rules, but regulatory correctness is not guaranteed; README itself says handbook clause numbers/thresholds need confirmation.
- Schema additions are applied additively at startup. No reviewed, versioned Alembic migration history exists.
- Dashboard is official-focused; institution dashboard/UI exists, but broad report export and filtered audit/report APIs are limited.
- Authentication/RBAC and tenant isolation are represented in code/tests but not executed in this environment.

### Missing relative to this request

- First-class configurable workflow stage definitions and general transition policy.
- Persistent EVC schedules, undertaking records, lease/document expiration tasks, reminder/escalation policy and deduplicated scheduler runs.
- Real-time push notifications (current notice list requires polling/refresh).
- Genuine QR production endpoint for application/document verification credentials; current issuance is demo-data oriented.
- Explicit delivery tracking and honest SMTP result representation.
- Report export and complete requirement-level traceability documentation.

### Reliability/security review notes

- No repository history is available for checking local modifications.
- SQLite/default startup is convenient; production guidance exists, but no Alembic revisions means upgrades need care.
- This is a prototype with synthetic external registries and bundled demo accounts. Do not treat it as an official AICTE integration or statutory decision system.
- Audit-chain integrity is tamper-evident within the database but is not an externally anchored/non-repudiation service.

## Official UI reference

Direct access to `https://www.aicte-india.org/` and the official Approval Process Handbook PDF both timed out in the browsing service. Search surfaced the official AICTE-hosted [Approval Process Handbook 2024–2027](https://aicte-qa.aicte-india.org/sites/default/files/APH%20Final.pdf), but its PDF could not be opened for detailed review. No visual specifications were inferred from inaccessible pages. The existing interface remains Validex-branded and the product sidebar now says “Independent prototype”; it must not imply AICTE ownership or endorsement.

## Current verification progress

- Frontend dependencies installed from the lockfile; production build passed after implementation. Vite reports a bundle above 500 kB.
- Oxlint exits successfully; it reports existing fast-refresh/state-in-effect warnings plus warnings in the new data-loading pages.
- Backend requirements installed. `python -m compileall -q app tests` passed.
- Backend unit tests: `python -m pytest -q tests/test_ocr.py tests/test_rules_spatial.py tests/test_persistent_workflow_services.py tests/test_ai_modules.py -k 'not rule_edit_is_versioned_and_changes_outcome and not invalid_rule_rejected and not deleting_application_keeps_audit_chain_intact and not audit_chain_detects_tampering'` — **28 passed, 4 deselected**. Includes OCR, compliance/rule engine, spatial/forensics, deadline idempotency/escalation, persisted workflow edge evaluation, and signed QR generation/decode/signature verification.
- Full backend pytest suite and HTTP-level regression tests have not completed: latest FastAPI/Starlette `TestClient` hangs during `__enter__`, including for an empty FastAPI app. Starlette warns that its current test client requires its `httpx2` transport. The attempted environment transport/version adjustment did not complete because package-index requests stalled. No full-suite pass is claimed.
- Frontend: `npm run build` — **passed**, with the Vite >500 kB chunk warning. `npm run lint` — **passed with warnings** (mainly existing fast-refresh and state-in-effect rules; new data-loading pages follow the same pattern).
