# VFIC backend image — shared by web + RQ workers + scheduler.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Build deps for psycopg/argon2; curl for healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (better layer caching). Runtime deps only — the
# dev extras (pytest, ruff) are not needed in the production image.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e .

# Copy application code.
COPY . .

# Default: run the web process. Workers/scheduler override the command in
# compose. Single uvicorn worker — --workers 2 forks two uvicorn processes
# which doubled cold-boot RSS and produced a multi-second listener gap on the
# 1.9GiB host where the deploy verification probe could overshoot.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
