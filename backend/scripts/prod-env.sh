#!/usr/bin/env bash
# Generate /opt/vfic/.env on first deploy: strong random infra secrets filled,
# third-party API keys left BLANK for the operator to fill. Idempotent.
set -euo pipefail

ENV_FILE="${VFIC_ENV_FILE:-/opt/vfic/.env}"

if [ -f "$ENV_FILE" ]; then
  echo "==> $ENV_FILE already exists; leaving untouched."
  exit 0
fi

mkdir -p "$(dirname "$ENV_FILE")"

PG_PASS=$(openssl rand -hex 18)
REDIS_PASS=$(openssl rand -hex 18)
JWT_SECRET=$(openssl rand -hex 32)
ADMIN_PASS=$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 20)
# AES-256-GCM key for admin-managed integration secrets (Zalo OA tokens, etc.).
# Required in production by Settings.model_post_init; any high-entropy string works
# (IntegrationSettingsCipher derives the AES key via sha256). Generated, not operator-filled.
INTEGRATION_SETTINGS_ENC_KEY=$(openssl rand -hex 32)

umask 077
cat > "$ENV_FILE" <<EOF
# VFIC production env — generated on first deploy (mode 0600).
# Fill the blank API keys below, then recreate the app services:
#   cd /opt/vfic && docker compose up -d --force-recreate web worker-chatbot worker-ingest scheduler

APP_ENV=production
CORS_ORIGINS=https://bot.tingting.vip

# ---- Postgres (self-hosted, pgvector) ----
POSTGRES_USER=vfic
POSTGRES_PASSWORD=$PG_PASS
POSTGRES_DB=vfic
DATABASE_URL=postgresql+asyncpg://vfic:$PG_PASS@postgres:5432/vfic
DATABASE_URL_SYNC=postgresql+psycopg://vfic:$PG_PASS@postgres:5432/vfic

# ---- Redis (RQ broker + per-chat mutex + pub/sub) ----
REDIS_PASSWORD=$REDIS_PASS
REDIS_URL=redis://:$REDIS_PASS@redis:6379/0

# ---- Auth (JWT) ----
JWT_SECRET=$JWT_SECRET
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=14

# ---- Integration secrets at-rest encryption (AES-256-GCM). Required in production. ----
INTEGRATION_SETTINGS_ENCRYPTION_KEY=$INTEGRATION_SETTINGS_ENC_KEY

# ---- Bootstrap admin (used once by \`make deploy\` -> scripts.create_admin) ----
VFIC_BOOTSTRAP_ADMIN_EMAIL=admin@vfic.vn
VFIC_BOOTSTRAP_ADMIN_PASSWORD=$ADMIN_PASS

# ---- Zalo Bot Platform (bot-api.zaloplatforms.com) — the single Zalo integration. ----
# ZALO_BOT_TOKEN: Bot Platform bot token (rides in the URL path /bot{TOKEN}/{method}).
# ZALO_BOT_WEBHOOK_SECRET: the secret_token passed to setWebhook; verified via X-Bot-Api-Secret-Token.
ZALO_BOT_TOKEN=
ZALO_BOT_WEBHOOK_SECRET=

# ---- LLM providers (OpenAI-compatible). Enable exactly one. ----
MINIMAX_ENABLE=true
MINIMAX_API_KEY=
MINIMAX_BASE_URL=https://api.minimax.io/v1
MINIMAX_AGENT_MODEL=MiniMax-M2.7-highspeed
MINIMAX_SAFETY_MODEL=MiniMax-M2.5-highspeed
MINIMAX_REQUEST_TIMEOUT=60

OPENROUTER_ENABLE=false
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_AGENT_MODEL=deepseek/deepseek-v3.2
OPENROUTER_SAFETY_MODEL=deepseek/deepseek-v3.2
OPENROUTER_DIGEST_MODEL=deepseek/deepseek-v3.2
OPENROUTER_REQUEST_TIMEOUT=60
OPENROUTER_DIGEST_TIMEOUT=180

# ---- Embeddings: Google Gemini (3072-dim). ----
GEMINI_API_KEY=
GEMINI_EMBEDDING_MODEL=gemini-embedding-2
EMBEDDING_DIM=3072

# ---- Email: Resend (password-reset OTPs). Sender: vficbot@1stop.app. ----
# Verify the 1stop.app sending domain in Resend before using.
RESEND_API_KEY=

# ---- Runtime ----
WEB_CONCURRENCY=2
EOF

echo "==> Created $ENV_FILE (mode 0600)."
echo "==> Bootstrap admin -> email: admin@vfic.vn   password: $ADMIN_PASS"
echo "    (also stored in $ENV_FILE as VFIC_BOOTSTRAP_ADMIN_PASSWORD)"
