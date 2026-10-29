# Hugging Face Docker Space image for the Validex backend.
# Build context (made by build_context.sh): backend/, scripts/, sample_docs/lab_photos/, start.sh
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libpq5 tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as uid 1000
RUN useradd --create-home --uid 1000 user
ENV HOME=/home/user YOLO_CONFIG_DIR=/home/user/.config/Ultralytics
WORKDIR /app

RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
COPY --chown=user backend/requirements.txt backend/requirements-ml.txt backend/
RUN pip install -r backend/requirements-ml.txt

COPY --chown=user . /app
RUN chown user /app
USER user

# Bake the model weights into the image so a sleeping Space wakes without downloads
RUN cd backend && mkdir -p ml_models/easyocr && python -c "\
from ultralytics import YOLO; YOLO('ml_models/yolov8n.pt'); \
import easyocr; easyocr.Reader(['en'], gpu=False, verbose=False, model_storage_directory='ml_models/easyocr')" \
    && ls ml_models ml_models/easyocr

EXPOSE 7860
CMD ["sh", "/app/start.sh"]
