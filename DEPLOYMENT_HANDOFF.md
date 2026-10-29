# Validex SIH26262 — implementation and deployment handoff

**Status as of 30 October 2026**  
**GitHub:** [lokesh-061106/APPAR-ReconX](https://github.com/lokesh-061106/APPAR-ReconX)  
**Current branch:** `main`  
**Latest implementation commit before this documentation update:** `f5a49ff` (`Prepare production provisioning and deployment routing`)

> Validex is an independent SIH26262 portal model. It is not an official AICTE service and is not endorsed by AICTE. Evaluation records and the external-authority examples are synthetic/simulated. Do not use it for real statutory decisions or confidential institutional records until the production gaps below are resolved.

## 1. Executive status

The application source, PWA assets, README, production bootstrap changes, and deployment configuration are in GitHub. Backend and frontend checks have passed as recorded below. **A new public deployment has not been completed or verified.** The Vercel import screen was opened for this repository; the Render API and PostgreSQL resources still need to be created and deployed. The earlier site at [validex-two.vercel.app](https://validex-two.vercel.app/) may still run an older build.

The mobile deliverable in this repository is an installable **Progressive Web App (PWA)**. It is not an Android APK or iOS App Store package.

## 2. What has been implemented

### Portal and application workflows

- Responsive, AICTE-portal-inspired navigation, application pages, review workspaces, and mobile layouts. Validex branding and a non-affiliation notice are retained.
- Role-based workspaces for institutions, scrutiny officers, experts, supervisors, approving officers, and administrators.
- Application intake, evidence upload, status tracking, deficiency clarification flow, and reviewer assignment.
- Final approval/rejection control is limited to the approving-officer role; reasons and actions enter the audit history.
- Configurable, versioned compliance rules and workflow transitions, with audit records for administrative changes.
- Deadline records for workflow due dates, EVC visits, undertakings, lease expiry, and document expiry, with persisted reminder/escalation processing.
- Dashboards, queue views, CSV report export, notification inbox, audit ledger, and chain verification.
- Document OCR/classification/extraction, rules checks, custody watermarking, forgery/duplicate indicators, spatial evidence checks, CV assistance, QR signature checking, and external-source adapters.

### Mobile PWA

- `frontend/public/manifest.webmanifest` defines app name, launch mode, display settings, and app icons.
- `frontend/public/sw.js` caches the application shell and static assets; API responses are not cached.
- The service worker is registered in production builds. The install button appears where the browser exposes an install prompt.
- The UI is responsive and can be added to a phone home screen after the site is served over HTTPS.

### Production provisioning and deployment files

- `render.yaml` defines a Render API service and PostgreSQL database, production environment, generated `SECRET_KEY`, and first-admin bootstrap fields.
- `frontend/vercel.json` routes `/api/*` through the Render API URL configured for this repository and sends application routes to the SPA entry point.
- Production first-admin bootstrap creates an administrator only if the users table is empty and valid bootstrap email/password variables are provided. It records an audit event and does not log the password. The password must be at least 16 characters.
- `.env.example` and `.env.production.example` list local and production configuration. The root `.gitignore` excludes real `.env` files; never commit deployment secrets.

## 3. Repository history and links

- Initial project upload: `459d20e` — `Publish Validex SIH26262 portal model`.
- Production provisioning and API route setup: `f5a49ff` — `Prepare production provisioning and deployment routing`.
- Source repository: [GitHub](https://github.com/lokesh-061106/APPAR-ReconX).
- Requirement mapping: [PS62_REQUIREMENT_MAPPING.md](PS62_REQUIREMENT_MAPPING.md).
- Latest pre-deployment checks and limitations: [PREDEPLOY_QA.md](PREDEPLOY_QA.md).
- Environment template: [.env.production.example](.env.production.example).

## 4. Local startup and reproducible workflow

These commands are for Windows PowerShell. Start the API in one terminal:

```powershell
cd C:\Users\LOKESH\Downloads\Validex-main\Validex-main
Copy-Item .env.example .env   # only if .env does not already exist
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In a second terminal, start the web application:

```powershell
cd C:\Users\LOKESH\Downloads\Validex-main\Validex-main\frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. The Vite development server proxies `/api` to the local API at port 8000. Local accounts and synthetic evaluation data are seeded only outside `ENVIRONMENT=production`; credentials and details are documented in [README.md](README.md). Never use these sample credentials in a public production environment.

Local check commands:

```powershell
# Backend, from backend/
$env:PYTHONPATH = (Get-Location).Path
python -m compileall -q app
python -m pytest -q

# Frontend, from frontend/
npm run build
npm run lint
```

The full backend test suite must still be run in a stable database/TestClient environment. The completed focused run and its four deselections are recorded in [PREDEPLOY_QA.md](PREDEPLOY_QA.md).

## 5. Deploy the API and database on Render

The blueprint is in the repository root as `render.yaml`. Render's Blueprint flow reads that file from the selected Git branch. Official Render documentation: [Blueprints](https://render.com/docs/infrastructure-as-code), [Blueprint specification](https://render.com/docs/blueprint-spec), and [environment variables](https://render.com/docs/configure-environment-variables).

1. Sign in to Render with the GitHub account that can access `lokesh-061106/APPAR-ReconX`.
2. Select **New → Blueprint** and choose this repository and the `main` branch.
3. Review the resources from `render.yaml`. The service is named `validex-appar-reconx-api`; the database is `validex-appar-reconx-db`. Render may append a suffix if those resource names already exist in the workspace.
4. Keep `ENVIRONMENT=production`. Render generates `SECRET_KEY` and links `DATABASE_URL` to the PostgreSQL resource.
5. For the initial production administrator, enter an email account controlled by the deployment owner and a unique password of at least 16 characters when Render prompts for `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`. Do not put either value in GitHub or in this document.
6. Deploy the Blueprint and wait for the API service to report **Live**. Check `https://<actual-render-service-host>/health`; it should return JSON with `"status":"healthy"`. `/docs` exposes the FastAPI API documentation.
7. After the first successful startup, remove `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` from the Render service environment and redeploy. The administrator remains in the database; removing the variables prevents accidental credential reuse if the database is later emptied.
8. Record the actual Render hostname. If Render had to append a suffix or generated a different host, update the API destination in `frontend/vercel.json`, commit, and push that change before creating the frontend deployment.

`CORS_ORIGINS` is not required for the standard Vercel setup because the browser calls `/api` on the Vercel origin and Vercel proxies those requests server-side. If a browser or external client calls Render directly, configure the actual frontend origin in Render's environment and redeploy.

### Important Render plan/storage warning

The checked-in blueprint currently chooses free plans and sets `USE_MINIO=false`. Render's current documentation states that Free Postgres expires 30 days after creation, has no backups, and free web services cannot retain local filesystem changes. See [Render free instance limitations](https://render.com/docs/free). The API's document storage would use local fallback storage with this blueprint. **Do not store real application documents or sensitive institutional data on this configuration.** For an operational service, select a suitable paid persistent PostgreSQL plan, configure a durable private MinIO/S3-compatible object store and backups, enable strict object storage (`REQUIRE_MINIO=true`), test recovery, and review access controls before any real data is accepted.

## 6. Deploy the frontend on Vercel

The user-visible Vercel import flow is the next frontend step. Official documentation: [Deploying Git repositories](https://vercel.com/docs/git) and [Build configuration](https://vercel.com/docs/builds/configure-a-build).

1. In Vercel, import `lokesh-061106/APPAR-ReconX` from GitHub and select branch `main`.
2. Set **Root Directory** to `frontend` (not the repository root).
3. Use **Framework Preset: Vite**, **Install Command: `npm ci`**, **Build Command: `npm run build`**, and **Output Directory: `dist`**. Vercel can auto-detect some of these; verify the values before deploying.
4. No `VITE_API_URL` is required for this setup. `frontend/vercel.json` proxies `/api/:path*` to the Render API and serves the React SPA for other routes.
5. Start the deployment. Wait for Vercel's build to finish and note the final HTTPS production URL. Confirm Vercel's deployment is for branch `main` and the latest intended commit.
6. If you changed the Render hostname, ensure `frontend/vercel.json` has the exact host before this build. If it changes afterward, push the corrected file and redeploy.
7. Test the Vercel URL: load `/login`, sign in as the bootstrapped administrator, create institution/supervisor/approver users, and check the main routes and API-backed behavior. Verify the app's `/manifest.webmanifest` and `/sw.js` URLs return successfully.

When the API and frontend are both live, the public application URL is Vercel's production URL. The source repository link is not the application URL.

## 7. Install on a phone

Use the final Vercel HTTPS URL:

- **Android:** open the URL in Chrome, use the browser's **Install app** or **Add to Home screen** action, and confirm the Validex icon appears on the launcher.
- **iPhone/iPad:** open the URL in Safari, tap **Share → Add to Home Screen**, enable **Open as Web App** if offered, then tap **Add**. Apple's instructions are at [Turn a website into an app in Safari on iPhone](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/27/ios/27).
- PWA installation requires HTTPS (except local development) and a valid manifest; see [MDN's PWA installability guide](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable).
- The PWA caches static shell assets only. It does not provide offline access to application/API data. No app-store package has been built or submitted.

## 8. Post-deployment smoke-test sequence

Run these checks against the deployed URLs after both services report healthy:

1. API health endpoint returns `status: healthy`; Vercel `/login` loads without a build/runtime error.
2. Sign in with the one-time bootstrap administrator. Confirm the token/session persists on refresh; remove bootstrap variables after the first startup.
3. Create an institution, supervisor, scrutiny reviewer, expert, and approving-officer account through Administration. Use non-production test identities unless an organization has approved onboarding.
4. As an institution, create an application and upload synthetic/non-sensitive test files. Verify the institution sees only its own application and public status/clarifications.
5. As supervisor, assign a case. As scrutiny/expert, review evidence and record item-level checks; verify another assigned reviewer cannot access that case.
6. As approving officer, test only an allowed final decision with a written reason. Verify the audit ledger entry and chain verification.
7. Create a test EVC/deadline/undertaking item; run the due sweep and verify reminders/escalations are persisted without duplicates.
8. Download a CSV report and verify its contents are scoped to the signed-in role.
9. Verify PWA manifest, icons, service-worker registration, responsive mobile layout, installation prompt/home-screen install, and refresh behavior.
10. Check Render and Vercel logs, database persistence across an API restart, and object recovery before considering any real operational use.

Never report an email as delivered without mailbox confirmation, an authority record as verified without a real provider response, or a QR as an official credential when it was signed with bundled synthetic keys.

## 9. Test and QA results

Latest run after production-bootstrap changes:

- Backend focused suite: **36 passed, 4 deselected**. The excluded tests are documented in the QA record; the full suite remains unverified because of the TestClient startup stall observed in this environment.
- Backend compile: passed.
- Frontend production build: passed. Vite warns that the main JavaScript bundle is about 820 KB, above its 500 KB advisory threshold.
- Frontend lint: exited 0 with existing warnings.
- Local scrutiny workspace smoke check: dashboard, triage queue, rules, deadlines/EVC, audit ledger, infrastructure review, and application detail loaded. Role-protected admin/supervisor pages still need authenticated browser QA after deployment.
- Static PWA outputs (manifest, service worker, 192 px and 512 px icons) exist in the build. A production install prompt was not independently browser-verified yet.

See [PREDEPLOY_QA.md](PREDEPLOY_QA.md) for the test record and limitations.

## 10. Remaining work before operational use

- Finish creating the Render Blueprint/API/database and the Vercel frontend project, then verify the production URL. The deployment has not yet been confirmed.
- Upgrade the free Render database/service and configure durable object storage, backups, data recovery, retention, and production security policy before any confidential data is uploaded.
- Run the complete API suite and authenticated browser end-to-end checks for all six roles against the deployed database.
- Configure an approved SMTP provider and verify actual mailbox receipt; configure and test authorized AICTE/issuer/registry connectors, credentials, and official QR trust keys.
- The in-app interface refreshes/polls notifications; push delivery/WebSocket real-time delivery is not currently verified.
- Confirm the actual Approval Process Handbook clause references and thresholds with authorized reviewers.
- Conduct privacy, security, accessibility, load, backup/restore, and incident-response reviews with the organization responsible for the service.
- Obtain official authorization before branding or operating this as an AICTE or Government of India service. Validex itself currently has no such affiliation.
- If a native app-store application is required, create and test native Android/iOS packages separately; the current phone installation path is the PWA.
