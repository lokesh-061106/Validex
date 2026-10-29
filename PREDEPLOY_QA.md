# Validex pre-deployment QA

Run date: 29 October 2026

## Results

- Backend compile check: `python -m compileall -q app` passed.
- Focused backend regression suite: **36 passed, 4 deselected** across OCR, spatial rules, persistent workflow services, AI modules, and production administrator bootstrap. The four exclusions are tests requiring the unavailable database/transaction setup; the complete TestClient suite previously stalled during app startup in this environment.
- Frontend production build: passed (`tsc -b` and Vite). Vite reports a 820 KB JavaScript chunk, above its 500 KB advisory threshold.
- Frontend lint: exited 0. Existing lint warnings remain, including effect state updates, Fast Refresh export warnings, and `no-unused-expressions` warnings.
- Python application sources compile successfully.
- Production output contains the PWA manifest, service worker, and 192/512 px icons.
- Production administrator bootstrap is covered: first admin creation, audit entry, weak/incomplete credential rejection, and no duplicate admin on repeated startup.
- Local browser smoke check as a scrutiny user: dashboard, triage queue, rules, deadlines/EVC, audit ledger, and infrastructure review rendered. Three applications appeared in the queue. The application detail page also has a role-gated final decision control in source; final decisions are only available to the approving-officer role.
- Admin and workflow configuration routes redirected to the dashboard for the signed-in scrutiny account, as required by role protection. Those screens and assignment controls still need a separate admin/supervisor-authenticated end-to-end pass.

## Not verified in this environment

- A production preview server could not be reached from the sandbox due local socket restrictions; therefore browser service-worker registration and install prompting were not independently confirmed. Static PWA output was confirmed in `frontend/dist`.
- The included Render blueprint currently uses free service/database plans and local file storage. It must be upgraded/configured with persistent storage and backups before handling confidential institutional records.
- A full API integration run remains unverified because the TestClient startup stalls. Four database-dependent cases were excluded from the passing focused suite.
- The source is pushed to GitHub, but the public app was not updated. Vercel and Render were signed out when checked. GitHub Actions reported success while skipping checkout/build/push because the Hugging Face deployment variables/secrets are absent. The existing public URL may still serve the earlier build.
- No app-store package was produced; the mobile deliverable is a Progressive Web App installable through supported browsers.
- Real external authority checks, email delivery, push delivery, and statutory decision authority require organization-managed integrations and credentials. Synthetic evaluation records and simulated authority sources must not be represented as official data or completed external verification.

## Pre-deployment follow-up

Before representing this release as an operational government service, run the full API suite against its configured database, complete role-specific browser checks for institution, supervisor, approver, and administrator, verify the production PWA over HTTPS, configure and test authorized mail/authority providers, and deploy through the organization's linked hosting project. Confirm email receipt and QR verification from their actual responses; do not infer success from local generation.
