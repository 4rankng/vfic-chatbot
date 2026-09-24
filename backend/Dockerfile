# VFIC backend image — shared by web + RQ workers + scheduler.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Build deps for psycopg/argon2. No curl: every healthcheck in
# docker-compose.yml probes /health with `python -c urllib.request`.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uv is a build-time tool: it renders uv.lock into the pinned runtime
# requirement set, so no dependency is resolved from PyPI at image-build time.
# It is installed, used and uninstalled inside one RUN, so no layer of the
# final image contains it.
ARG UV_VERSION=0.11.13

# Install dependencies first (better layer caching). Runtime deps only — the
# dev extras (pytest, ruff) are not part of the exported set. `--frozen` makes
# the build fail on a pyproject.toml/uv.lock mismatch instead of silently
# resolving different versions, and the hashes pin the exact artefacts.
COPY pyproject.toml uv.lock ./
RUN pip install --upgrade pip "uv==${UV_VERSION}" \
    && uv export --frozen --no-dev --no-emit-project \
        --output-file /tmp/runtime-requirements.txt \
    && pip install --require-hashes -r /tmp/runtime-requirements.txt \
    && pip uninstall -y uv

# Application code. Explicit allowlist on purpose: mock_servers/ (the fake Zalo
# endpoint `make dev` runs) and .env.example must never reach the production
# image, and naming the paths here keeps them out even if .dockerignore is
# edited later. `scripts/` is needed — compose and bg_deploy.sh run
# `python -m scripts.<x>` inside the container.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

# Editable install of the project itself. Its dependencies are already pinned
# and installed above, so --no-deps resolves nothing here either.
RUN pip install --no-deps -e .

# Default: run the web process. Workers/scheduler override the command in
# compose. Single uvicorn worker — --workers 2 forks two uvicorn processes
# which doubled cold-boot RSS and produced a multi-second listener gap on the
# 1.9GiB host where the deploy verification probe could overshoot.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
