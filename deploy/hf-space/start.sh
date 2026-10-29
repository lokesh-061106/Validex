#!/bin/sh
# Container entrypoint for the Hugging Face Space.
# The Space disk is wiped on every restart, so uploaded files do not survive. With
# RESEED_DEMO_ON_START=true the synthetic demo applications are rebuilt on each boot
# (this deletes all applications in the database, including ones created during a demo).
set -e
cd /app/backend

if [ "${RESEED_DEMO_ON_START:-false}" = "true" ]; then
  echo "Re-seeding synthetic demo data..."
  python ../scripts/generate_demo_data.py --reset || echo "WARNING: demo seeding failed; starting API anyway"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}" --proxy-headers --forwarded-allow-ips="*"
