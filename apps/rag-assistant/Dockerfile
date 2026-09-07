FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/apps/rag-assistant

WORKDIR /app

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app

COPY requirements.lock ./
RUN pip install --no-cache-dir --requirement requirements.lock

COPY ingestion ./ingestion
COPY gateway ./gateway
COPY sample-data ./sample-data
COPY apps/rag-assistant ./apps/rag-assistant

RUN mkdir -p /app/generated /var/log/reference/runtime /var/log/reference/audit \
    && python -m ingestion.build_index --source /app/sample-data --output /app/generated/index.json \
    && chown -R app:app /app/generated /var/log/reference

USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "secure_rag.api:app", "--app-dir", "/app/apps/rag-assistant", "--host", "0.0.0.0", "--port", "8000"]
