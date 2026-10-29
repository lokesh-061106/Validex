#!/usr/bin/env bash
# Assemble the Hugging Face Space repository contents into an output folder.
#   deploy/hf-space/build_context.sh <out-dir>
# Copies backend/ (without venv, model weights, local DB, uploads, tests), scripts/,
# any real lab photos, and the Space Dockerfile / README / start script.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:?usage: build_context.sh <out-dir>}"
mkdir -p "$OUT"

tar -C "$ROOT" -cf - \
  --exclude='backend/.venv' --exclude='backend/ml_models' --exclude='backend/storage_vault' \
  --exclude='backend/validex.db' --exclude='backend/tests' --exclude='backend/.env' \
  --exclude='__pycache__' --exclude='.pytest_cache' --exclude='*.pyc' \
  backend scripts | tar -C "$OUT" -xf -

mkdir -p "$OUT/sample_docs/lab_photos"
find "$ROOT/sample_docs/lab_photos" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) \
  -exec cp {} "$OUT/sample_docs/lab_photos/" \; 2>/dev/null || true

cp "$ROOT/deploy/hf-space/Dockerfile" "$ROOT/deploy/hf-space/README.md" "$ROOT/deploy/hf-space/start.sh" "$OUT/"

# Hugging Face requires binary files to go through LFS
cat > "$OUT/.gitattributes" <<'EOF'
*.jpg filter=lfs diff=lfs merge=lfs -text
*.jpeg filter=lfs diff=lfs merge=lfs -text
*.png filter=lfs diff=lfs merge=lfs -text
*.pdf filter=lfs diff=lfs merge=lfs -text
*.pt filter=lfs diff=lfs merge=lfs -text
*.pth filter=lfs diff=lfs merge=lfs -text
EOF

echo "Space context written to $OUT"
