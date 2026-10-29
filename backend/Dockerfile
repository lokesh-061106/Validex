# Light image (default): no PyTorch. Object detection runs YOLOv8n through ONNX Runtime and OCR of
# scans uses Tesseract, so the API fits hosts with 512 MB RAM (e.g. Render free).
# Dockerfile.full adds EasyOCR and the ultralytics stack for bigger hosts.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 OMP_NUM_THREADS=2 MALLOC_ARENA_MAX=2

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libpq5 tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home validex && mkdir -p storage_vault ml_models && chown -R validex /app
USER validex

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
