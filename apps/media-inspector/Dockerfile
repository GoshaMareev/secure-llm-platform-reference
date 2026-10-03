FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/apps/rag-assistant HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 OMP_NUM_THREADS=2
WORKDIR /app

RUN apt-get update && apt-get install --no-install-recommends -y \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY apps/media-inspector/requirements.lock ./media-requirements.lock
RUN pip install --no-cache-dir --require-hashes -r media-requirements.lock
COPY scripts/download_asr_model.py /app/download_asr_model.py
RUN python /app/download_asr_model.py
COPY apps/rag-assistant /app/apps/rag-assistant
COPY ingestion /app/ingestion
COPY apps/media-inspector/service.py /app/media_service.py
USER 10001:10001
CMD ["uvicorn", "media_service:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log", "--log-level", "error"]

# Test-only stage. The deployed inspector does not contain a speech generator.
FROM runtime AS fixtures
USER 0:0
RUN apt-get update && apt-get install --no-install-recommends -y espeak-ng fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY scripts/generate_media_fixtures.py /app/generate_media_fixtures.py
USER 10001:10001
CMD ["python", "/app/generate_media_fixtures.py", "--output", "/fixtures"]
