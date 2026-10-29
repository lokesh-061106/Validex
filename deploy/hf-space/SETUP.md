# Hosting the backend on a Hugging Face Space

> **Cost:** Hugging Face now requires a PRO subscription to run Docker (and Gradio) Spaces, including on the
> CPU-basic hardware; only static Spaces are free. For free hosting use the light image on Render instead
> (`backend/Dockerfile`, fits 512 MB). Use this guide if you have PRO or need the full EasyOCR build.

Frontend stays on Vercel. Backend runs as a Hugging Face **Docker Space** (CPU basic, about 16 GB RAM; needs PRO).
The database is a free **Neon** Postgres, because the Space's disk is wiped on every restart.

```
Vercel (frontend) ──► https://<hf-user>-validex-api.hf.space (backend, Hugging Face) ──► Neon Postgres
```

Things to know first:

* The Space must be **public** so the browser can call it. Anyone can then read the backend code in the
  Space's *Files* tab (your GitHub repo can stay private). Secrets you add in Space settings stay hidden.
* It sleeps after about 48 hours without visits and takes 1–2 minutes to wake. Open `/health` before a demo.
* Uploaded files are lost on restart. With `RESEED_DEMO_ON_START=true` the three demo applications are
  rebuilt on every start; this **deletes all applications** in the database, including ones made during a demo.
* All data must stay synthetic.

## 1. Database (Neon)

1. Sign up at https://neon.tech and create a project. Pick the Asia region closest to you.
2. Copy the connection string (`postgresql://…?sslmode=require`). You need it in step 3.

## 2. Create the Space

1. Sign up at https://huggingface.co.
2. **New Space**: name `validex-api`, SDK **Docker** (blank template), hardware **CPU basic (free)**, visibility **Public**.
3. Your backend URL will be `https://<hf-user>-validex-api.hf.space` (your Hugging Face username, lowercase).

## 3. Space settings → Variables and secrets

| Type | Name | Value |
|---|---|---|
| Secret | `SECRET_KEY` | output of `python -c "import secrets; print(secrets.token_hex(32))"` |
| Secret | `DATABASE_URL` | the Neon connection string |
| Variable | `ENVIRONMENT` | `demo` (seeds the demo accounts; never use `production` for the demo) |
| Variable | `RESEED_DEMO_ON_START` | `true` |
| Variable | `USE_MINIO` | `false` |

The Vercel site `https://validex-two.vercel.app` is already allowed by the backend's CORS settings.
If the frontend URL changes, add a variable `FRONTEND_ORIGINS` with the new URL.

## 4. Automatic deploys from GitHub

1. Hugging Face → *Settings → Access Tokens* → create a token with **write** access to the Space.
2. GitHub → repo *Settings → Secrets and variables → Actions*:
   * secret `HF_TOKEN` = that token
   * variable `HF_SPACE` = `<hf-user>/validex-api`
3. GitHub → *Actions → Deploy backend to Hugging Face Space → Run workflow*.
   After this, every push to `main` that touches the backend redeploys the Space.
4. Watch the build in the Space's *Logs* tab. The first build takes roughly 10–15 minutes (PyTorch and the
   model weights are baked into the image). Then check `https://<hf-user>-validex-api.hf.space/health`.

Manual alternative, without GitHub Actions:

```bash
bash deploy/hf-space/build_context.sh /tmp/space
cd /tmp/space && git init -b main && git lfs install && git add -A && git commit -m deploy
git push --force https://<hf-user>:<HF_TOKEN>@huggingface.co/spaces/<hf-user>/validex-api main
```

## 5. Point the frontend at the Space

1. Vercel → project *Settings → Environment Variables*: set `VITE_API_URL` to
   `https://<hf-user>-validex-api.hf.space/api` (all environments).
2. Update `frontend/vercel.json` so its `/api` rewrite points at the same host (fallback route).
3. Redeploy the frontend (Vercel → *Deployments → Redeploy*), because `VITE_API_URL` is read at build time.
4. Optional: suspend the Render service so there is only one backend.

## Troubleshooting

* **Build fails at the model download step**: re-run the build; it fetches YOLOv8n and EasyOCR weights from GitHub.
* **`Incorrect email or password` for demo logins**: `ENVIRONMENT` is `production`, or the start-up seed failed (see *Logs*).
* **Browser shows CORS errors**: the frontend origin is not in `FRONTEND_ORIGINS` / `CORS_ORIGINS`.
* **Push rejected for binary files**: the build script tracks images and weights with Git LFS; make sure `git lfs install` ran.
