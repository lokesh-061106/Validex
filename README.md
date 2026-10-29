# Validex — SIH26262 AICTE Application Validation Portal Model

**SIH 2026 · Problem Statement SIH26262 · Team We Aren't Robots**

> Validex is an independent portal model for SIH26262. It is not an official AICTE system and is not endorsed by AICTE. All bundled institutions and evaluation records are synthetic. External authority lookups use simulated adapters unless an authorized provider is configured and confirmed.

Validex pre-screens AICTE approval applications (EoA and other categories). It reads the uploaded documents, checks them against configurable Approval Process Handbook rules and AICTE's own institutional records, looks for signs of tampering and re-used evidence, verifies certificates with their issuing authorities (signed QR codes and registry lookups), and assists with infrastructure evidence using computer vision.

Every result is an **evidence-linked, explainable finding** for an official. The system never approves, rejects or issues notices on its own. Decisions are recorded by an authorised officer, with reasons, in a hash-chained audit ledger.

> All data in this repository is synthetic. The issuing authorities and AICTE records are simulated behind pluggable adapters; the system does not assume access to any restricted database.

---

## What the problem statement asks for, and where it is

| Requirement | Implementation |
|---|---|
| Category-based checklist and configurable rules | `services/rule_engine.py`: a **deterministic** compliance engine, no generative AI. Rules are data (`requires_doc` + `check {fact or expr, op, value, unit}`), filtered by category, versioned, edited by admins with an audited reason. Bounds are exact `Decimal` arithmetic through a whitelisted expression evaluator (`ceil`, `floor`, `min`, `max`, `round`, `abs`), e.g. faculty ≥ `ceil(intake × years / 20)`, professors ≥ `ceil(required / 9)`, classroom ≥ 66 m², with units normalised (acres, m², ft²). Each outcome carries the calculation trace, the handbook clause and a **Green / Amber / Red** label. |
| Retrieve records from authorised AICTE systems | `services/records_service.py` via the connector: approved intake, faculty on record, TER payment, previous EoA, open deficiencies. Used by rules and cross-checks. |
| OCR, classification, extraction | Native PDF text (visibility-aware, so text hidden under a whiteout is ignored), EasyOCR with OpenCV preprocessing for scans/photos, keyword classifier with a wrong-slot warning, domain extractors with multi-format dates. |
| Missing / incomplete / expired / inconsistent | Completeness and expiry via rules; fuzzy name matching (RapidFuzz + abbreviation normalisation) across documents, the application and AICTE records; land and faculty cross-checks. |
| Chain of custody | `services/custody_service.py`: before storage every file is stamped with a visible and an invisible watermark (`VALIDEX - CHAIN OF CUSTODY - VERIFIED <timestamp>`) and an HMAC-signed manifest. PDFs get an incremental-update stamp, XMP metadata and an embedded manifest (the original bytes stay recoverable byte-for-byte); images get a visible band plus an LSB watermark; MP4s get a `uuid` box; GeoJSON gets a `validex_custody` member. Only the stamped object is written to MinIO (`REQUIRE_MINIO=true` disables the local fallback). Analysis runs on the original recovered from the stamped object; any later change to the stored object is a custody breach (`GET /api/documents/{id}/custody`). |
| Collusion across institutions | `services/graph_service.py`: faculty (PAN, faculty ID, biometric template reference) and equipment serials become graph nodes linked to institutions. With `NEO4J_URI` set it uses Neo4j (`MERGE` on ingest, Cypher queries shown to officers); otherwise an in-process equivalent built from the database. Identifiers are HMAC-keyed and PANs masked (`VXDFA****B`); no face images are stored or compared. |
| Spatial / square-footage claims | `services/spatial_service.py`: the campus boundary (GeoJSON) is measured geodesically and compared with the deed (±5%); declared buildings must lie inside it; observed building footprints from a pluggable GIS provider (simulated, or OpenStreetMap Overpass with `GEODATA_PROVIDER=osm`) are compared with the plan's ground coverage (±15%); each stated room area is checked against its length × width. |
| Alterations, duplicates, metadata, mismatched identifiers | `ml/forgery_detector.py` (cover-up boxes, overlapping text layers, font/baseline anomalies, revision history, editing-tool metadata; for images: noise consistency, verified copy-move, ELA as a weak signal). `services/duplicate_service.py` (exact hash, perceptual hash across institutions, the same certificate/UDIN number used by different institutions). |
| Verification at the source | `services/verification_service.py`: Ed25519-signed QR codes checked offline (and compared with the printed text), plus registry lookups. Statuses: verified, mismatch, expired, pending, source unavailable, manual review, each with source, identifiers sent, timestamp, field-by-field comparison and reason. Retry with exponential backoff, a circuit breaker and a periodic sweep (Celery beat). |
| Infrastructure assistance | `ml/infrastructure_cv.py`: YOLOv8 on photos and video keyframes, equipment minimums from rules, evidence-quality checks (dark, blurred, low resolution), honest "not detectable / manual review" when it cannot tell. Floor-plan classroom areas are checked by rule. |
| Dashboard, alerts, audit trail | **Triage & Human Console (officers only)**: RAG queue ordered by unreviewed red items; split-screen review with the watermarked document (from MinIO) beside the handbook clauses, calculation traces and findings (from PostgreSQL); red items need *confirm* or *override* with a reason before approval; collusion-graph and spatial views; custody check; append-only hash-chained ledger. |
| Institution alerts / rectification | The college portal is **blind**: after upload it shows only "Document received" (no progress, stages, flags, scores, findings or self-check), so institutions cannot probe or adapt to the detectors. Amber items (missing, expired, unreadable) go back as **encrypted clarification requests**: RSA-OAEP-2048 + AES-256-GCM to a key pair generated in the institution's browser (private key non-extractable, in IndexedDB). Requests list only what to supply, never forensic reasons. The ledger keeps the plaintext hash. |
| Role-based access, human review | Roles: admin, scrutiny, expert, institution. Object-level access checks on every endpoint. Self-registration creates institutions only. Adverse decisions, and overrides of the AI advice, require written reasons. |
| Security, confidentiality, retention | Salted PBKDF2 passwords, JWT, login rate limit, upload type sniffing and size limit, server-generated storage names, document-view logging, retention purge (dry run by default), security headers, internal-only network in production compose. |

---

## Architecture

```
React (Vite + Tailwind) ── institution portal · scrutiny workspace · rules editor · audit ledger
        │ /api (JWT)
FastAPI ── auth/RBAC · applications · documents · triage · verification · rules · audit · clarifications
   │            │                         │                    Neo4j (optional) ── collusion graph
   │   Celery workers (Redis)        Connector adapters ──► simulated issuing authorities (separate service)
   │   heavy: OCR, forensics, YOLO        (in-process or HTTP)  └► simulated AICTE institutional records
   │   light: source checks, email
   │   beat : retry sweep
PostgreSQL / SQLite (findings, RAG, reviews, hash-chained audit) · MinIO (watermarked files + evidence images; local vault only for dev)
```

## Persistent workflow deadlines

Deadline records can represent a workflow due date, EVC visit, undertaking, lease expiry, or supporting-document expiry. They are scoped to an application, visible to its institution and authorized officials, and audited when created or completed. Officials can create/schedule EVC and workflow events; institution users can register undertaking/expiry dates. Reminder windows and escalation intervals are configurable per record. The repeat-safe processor writes in-app notifications and escalates overdue items to active scrutiny/admin accounts.

The API is available under `/api/deadlines`: `GET` lists records, `POST` creates one, `PATCH /{id}` updates its status, and authorized officials can invoke `POST /process-due` to process due work. When Celery is enabled, beat runs the same processor every five minutes. Local direct mode has no always-running scheduler; use the endpoint or run Celery/Redis. These notifications are persisted in-app records; the current interface refreshes/polls them rather than using push delivery.

Admins configure allowed state edges and role policies in the **Workflow Config** page or through `GET /api/workflow/transitions` and `PUT /api/workflow/transitions`. Each change requires a reason and is written to the audit ledger. Seeded defaults preserve the existing submission → review → clarification/decision lifecycle.

SMTP is optional (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`). A `send_email` success means SMTP accepted the message for handoff; it does not prove delivery to the recipient mailbox. With no SMTP host configured, clarification notices remain in-app only.

The development-only administrative QR test endpoint returns a genuine QR PNG containing an Ed25519-signed payload and the server's verification result. It uses deterministic synthetic issuer keys, returns a non-official label, and is disabled in production. Document upload verification separately decodes QR images from evidence and checks signatures server-side. No official issuer authority is implied; configure approved issuer keys and credentials before an issuer integration.

See [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md) and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for phase status and verified limitations.

Processing pipeline per document (silent to institutions):
`watermark + manifest → store (MinIO) → recover original → OCR → classify → extract fields → locate fields → forensics → duplicates → QR + registry verification` (lab photos and videos go to the CV stage, campus boundaries to spatial verification, faculty lists and asset registers into the collusion graph).

RAG labels:
* **Green**: the deterministic bound is met; auto-pass.
* **Amber**: missing, expired or unreadable, fixable by the institution (sent as an encrypted clarification request), or a source that is pending or needs an officer look.
* **Red**: anomaly or rule failure (possible alteration, registry mismatch, shared PAN/biometric/equipment, footprint outside tolerance, bound violated). An officer must confirm or override each one; approval is blocked until then.

---

## Quick start (local, no Docker)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt                    # light: ONNX Runtime detector + Tesseract OCR, no PyTorch
# optional full ML (EasyOCR for scans): pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
#                                       pip install -r requirements-ml.txt
python ../scripts/generate_demo_data.py --reset    # synthetic evaluation records + 3 seeded applications
uvicorn app.main:app --port 8000
```

```bash
cd frontend
npm install
npm run dev                         # http://localhost:3000 (proxies /api to :8000)
```

* API docs (for portal integration): http://localhost:8000/docs
* Object detection uses the bundled `backend/app/ml/weights/yolov8n.onnx` (ONNX Runtime). OCR of scans uses EasyOCR when
  `requirements-ml.txt` is installed, otherwise Tesseract (install the `tesseract-ocr` system package). PDFs with a text
  layer need no OCR. `GET /health` lists the engines found.
* Uploads are processed as FastAPI background tasks locally; set `USE_CELERY=true` with Redis for workers.
* Put 2+ **real computer-lab photos** in `sample_docs/lab_photos/` before seeding; otherwise placeholders are used and the lab rule (correctly) asks for better evidence.

`sync_schema()` creates/adds application tables at backend startup, including the deadline and workflow policy tables. For recurring scheduled sweeps, configure `USE_CELERY=true`, start Redis, then run a worker and beat process from `backend/`:

```bash
celery -A app.core.celery_app.celery worker --loglevel=INFO -Q heavy,light,default
celery -A app.core.celery_app.celery beat --loglevel=INFO
```

Celery beat retries authority checks and evaluates deadlines every five minutes. Set SMTP environment values only for a server you are authorized to use. No external credentials are required for local startup; `.env.example` lists available settings. Production requires a strong `SECRET_KEY` and production database/storage configuration; evaluation accounts are not seeded in production.

For a new production database, set `BOOTSTRAP_ADMIN_EMAIL` and a unique `BOOTSTRAP_ADMIN_PASSWORD` (minimum 16 characters) in the hosting provider's secret settings. The backend creates this first administrator only when the users table is empty, writes an audit event, and logs no credential values. Remove both bootstrap variables after the first successful startup. The Render blueprint marks them as provider-managed settings.

### Docker

```bash
docker compose up -d --build                       # dev: web :3000, API :8000, Flower :5555
docker compose exec backend python ../scripts/generate_demo_data.py --reset
```

**Hosting:** `backend/Dockerfile` is the light image (no PyTorch). It fits Render's free plan (512 MB): measured peak
about 460 MB with a 12-MP lab photo, documents processed one at a time (`MAX_CONCURRENT_PROCESSING`).
`backend/Dockerfile.full` (used by docker-compose) adds EasyOCR and PyTorch and needs about 2 GB.
[deploy/hf-space/SETUP.md](deploy/hf-space/SETUP.md) runs the full image on a Hugging Face Docker Space, which now
requires a Hugging Face PRO subscription.

`docker-compose.prod.yml` keeps every service on an internal network and exposes only Nginx on :80. It requires `SECRET_KEY`, `POSTGRES_PASSWORD` and the MinIO credentials; see `.env.production.example`. Pre-load the `models` volume (YOLO + EasyOCR weights), because the internal network has no internet access.

---

## Evaluation accounts (synthetic; development only)

| Role | Email | Password |
|---|---|---|
| Scrutiny officer | scrutiny@aicte-india.org | scrutiny123 |
| Admin (rules, users, integration controls) | admin@aicte-india.org | admin123 |
| Expert committee | expert@aicte-india.org | expert123 |
| Approving officer (final approvals/rejections) | approver@aicte-india.org | approver123 |
| Supervisor (review assignment and oversight) | supervisor@aicte-india.org | supervisor123 |
| Apex Institute (clean) | principal@apex.edu.in | apex123 |
| Zenith College (problems) | principal@zenith.edu.in | zenith123 |
| Crescent Institute | principal@crescent.edu.in | crescent123 |

Evaluation accounts are seeded only when `ENVIRONMENT` is not `production`.

These credentials are for local/non-production evaluation only. Production deployments must use real institution and official accounts created through an authorized onboarding process.

The included Render blueprint uses a free service/database and local file storage defaults to make deployment configuration reproducible. Free plans can sleep and their database/storage choices are not appropriate for confidential institutional records. Configure paid persistent database and object storage (MinIO or an S3-compatible service), retention, backups, and approved identity/authority providers before accepting real records.

## Mobile access

The responsive web client is installable as a Progressive Web App (PWA) in supported browsers. Open the deployed HTTPS site on Android and choose **Install app** / **Add to Home screen**. On iPhone or iPad, use **Share → Add to Home Screen** in Safari. The PWA caches the application shell and static assets; API responses and private application records are not cached for offline access. This repository does not contain app-store packages for iOS or Android.

## Core workspaces

- **Institution:** create and track applications, upload evidence, receive encrypted clarification requests, and monitor deadlines.
- **Scrutiny / expert:** triage submissions, review evidence and rule outcomes, record human review, and send clarification requests.
- **Supervisor:** assign submitted cases to reviewers and monitor the scoped review queue.
- **Approving officer:** issue final approval or rejection with a reason recorded in the audit history.
- **Administrator:** manage users, configurable rules, workflow transitions, and integration settings. Administrators cannot issue statutory final decisions.
- **Shared modules:** dashboards and CSV reporting, document and QR analysis, spatial evidence, notifications, persistent deadlines/EVC/undertakings/expiry dates, and the hash-chained audit ledger.

See [PS62_REQUIREMENT_MAPPING.md](PS62_REQUIREMENT_MAPPING.md) for feature-to-requirement coverage and limitations.

## Feature walkthrough

1. **Scrutiny officer → Dashboard.** Live counts, critical alerts first.
2. **Triage Queue → Zenith** (21 red, 7 amber). In the split-screen review, each document sits beside its handbook clauses:
   * Fire NOC: a white box hides `15/03/2025` and `31/12/2027` is typed on top; the signed QR and the registry say 2025 (red);
   * Faculty list: 9 vs `ceil(300 × 4 / 20)` = 60 required, with the calculation trace (red); two PANs also on Apex's list and a biometric reference belonging to a Crescent faculty member (red, collusion graph);
   * Asset register: four computer serials registered to Crescent (red);
   * Building plan: room C-101 states 70 m² but 7 m × 9 m = 63 m² (red);
   * Campus boundary: "Hostel Block" lies outside the boundary and the observed footprint is 65% off the plan (red; see the Spatial tab);
   * audit report reuses Apex's UDIN; lab photo copies Crescent's (red);
   * land deed missing, NOC expired, TER unpaid, open deficiency (amber).
3. **Collusion graph** tab: Zenith linked to Apex and Crescent through shared faculty and equipment, with the Cypher query used.
4. **Admin → Rules Engine.** Change a threshold (e.g. land ≥ 2.5 → 15 acres) with a reason, re-run screening, and the finding changes. History shows v1 → v2.
5. **Admin → Administration → Simulate outage**, then re-verify a document: "source unavailable, retry scheduled". Restore and re-verify: it verifies.
6. Sign in once as **Zenith** (this creates the browser key pair). Then **Officer → Request clarification**: only amber items can be selected. Sign in as Zenith again: the request decrypts in the browser and lists what to supply, with no forensic reasons. Uploads only ever show "Document received".
7. **Officer → Apex → Record decision.** Approval is blocked until the red lab-photo item is confirmed or overridden with a reason. **Audit Ledger → Verify chain integrity** confirms the chain is intact.
8. Open **Deadlines & EVC** as scrutiny and create a synthetic EVC visit due in the past; click **Run due sweep**. The institution and active scrutiny/admin recipients receive stored in-app alerts, the escalation level is visible, and a second sweep creates no duplicates. Open **Workflow Config** as admin and disable/re-enable a test transition with a reason; the audit history records each edit and a disabled transition is rejected server-side. The dashboard **CSV report** exports persisted application rows.

---

## Evaluation and tests

```bash
cd backend
python -m pytest -q                  # run the complete backend test suite
python ../scripts/evaluate.py        # writes EVALUATION.md (add --quick to skip scanned-document OCR)
```

The backend test suite must be run after installing `backend/requirements.txt`; tests include transition enforcement, deadline reminder/escalation idempotency and synthetic signed QR generation. The frontend check commands are `npm ci`, `npm run build`, and `npm run lint` in `frontend/`. See [PREDEPLOY_QA.md](PREDEPLOY_QA.md) for the latest executed results and checks that still need an authorized deployment environment.

Latest results on the labelled synthetic set are in [EVALUATION.md](EVALUATION.md):
* PDF tampering: 20/20 detected, 0 false positives on 20 clean PDFs.
* Scans: 0 false positives, but recall 0.35. Digital pastes on noisy scans are caught; low-noise pastes and low-quality splices are not.
* Digital-PDF field extraction: 100%. Scanned OCR reads dates well but misreads separators in IDs, so OCR-read identifiers never produce an automatic "mismatch".
* Duplicate photos: 15/15 detected, 0 false matches.
* Verification statuses: 14/14 correct.

These are synthetic-set numbers, not real-world accuracy claims.

## Integrating with the AICTE portal

* REST API with OpenAPI at `/docs`. The institution side creates applications and uploads documents (the response is a static receipt). Officer systems use `/api/triage/{id}` (rules, findings, reviews, documents with custody hashes), `/api/validation/report/{id}` and `/api/compliance/check/{id}`; these are officer-only.
* Issuing authorities and AICTE records are reached only through `services/connectors.py`. Replace the simulated adapter with DigiLocker / API Setu / ICAI / state-portal connectors without touching validation logic. Only the identifier being verified is sent out.
* Signed QR format: `VALIDEX1:` + base64(JSON `{iss, data, sig}`), Ed25519 over `{iss, data}`. Issuers publish their public key (`/mock-authority/{issuer}/public-key`).

## Safeguards built in

* AI output is advisory. The AI never sets a final status; screening only moves `submitted → under_review`.
* Adverse decisions, and decisions that differ from the AI advice, need a written reason. Experts cannot approve or reject.
* Forgery findings are worded as "possible alteration — needs verification" and carry their evidence.
* Rules are data, versioned and audited; findings record the rule code and version applied.
* Every upload, check, source response, rule change, clarification request (plaintext hash), red-finding review, key registration, custody breach, document view and decision is in the hash-chained ledger (`/api/audit/verify-chain`).
* Institutions never see analysis output; officer-only endpoints return 403 to institutions.

## Known limits and next steps

* Pixel forensics on heavily compressed, low-noise scans is weak; QR and registry verification is the stronger control.
* YOLOv8n uses COCO classes (monitors appear as "tv"). A model fine-tuned on lab equipment would improve counts; fire extinguishers and projectors are currently "manual check".
* Room dimensions from photos are not estimated; classroom areas come from the sanctioned plan.
* **Handbook clauses:** rule clause texts are plain-language summaries, and `handbook_reference` says "enter clause/appendix no.". The team must fill in the actual Approval Process Handbook 2026-27 clause numbers and confirm each threshold before any real use.
* **Watermark wording:** the default text says "VERIFIED" even though it is stamped on receipt, before verification. It is configurable with `WATERMARK_TEXT`; "RECEIVED" would be more accurate.
* **Spatial:** footprints come from GIS vector data (simulated, or OSM), not satellite-image analysis. A building-footprint segmentation model on licensed imagery would be the next step.
* **Identity:** biometric data is a template reference from an attendance system, HMAC-keyed; there is no face recognition. Real use needs DPDP Act consent and a lawful basis.
* **Keys:** signing in on a new browser rotates the institution's key; older requests stay readable only where the old key lives (AICTE can re-issue).
* Neo4j and the Docker images with Neo4j were not run in this environment; the in-process graph backend is what the tests exercise.
* Not implemented: presigned multipart uploads, page streaming, Postgres row-level security, regional-language UI.

## Project layout

```
backend/app/api/            REST endpoints (auth, applications, documents, triage, validation, verification, compliance, audit, notifications, admin)
backend/app/services/       pipeline, custody, rule engine, validation, triage, graph, spatial, secure messaging, verification, connectors, duplicates, audit
backend/app/ml/             OCR, extraction, forensics, QR verification, perceptual hash, infrastructure CV
backend/app/mock_authority/ simulated issuing authorities + AICTE records (registry.json), issuer keys
backend/tests/              pytest suite
scripts/                    synthetic document factory, demo seeding, evaluation
frontend/src/               React app (triage console, blind portal, secure inbox (WebCrypto), DocumentReview, ui kit)
```
