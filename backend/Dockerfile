# MarginPilot backend — minimal, pinned, non-root.
# Base image tag + digest verified via Registry HTTP API (no daemon needed):
# evidence: download/evidence/image_digests.json
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dedicated non-root user (security.md §8 / Phase 2 constraint).
RUN groupadd --system marginpilot && useradd --system --gid marginpilot marginpilot

# Runtime dependencies only, exact-pinned and hash-verified.
COPY requirements-runtime.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements-runtime.lock

COPY pyproject.toml ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

USER marginpilot

EXPOSE 8000

# Real readiness probe against the local process (no curl in slim image).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u,sys; r=u.urlopen('http://127.0.0.1:8000/health/live', timeout=3); sys.exit(0 if r.status==200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
