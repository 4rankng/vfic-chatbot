#!/usr/bin/env bash
# bg_deploy.sh — blue/green, zero-downtime backend deploy. Runs ON THE DROPLET.
#
# Flow (cd /opt/vfic, IMAGE_TAG=<git sha> in env):
#   1. pull the new image
#   2. ensure postgres + redis
#   3. alembic widen + upgrade head (one-shot web-blue run)
#   4. bring up the INACTIVE web color + workers at the new tag
#   5. wait for the new color healthy
#   6. SMOKE GATE: run one real turn on the new color; abort if it fails
#   7. flip Caddy onto the new color (graceful reload)
#   8. record PREV_COLOR/PREV_TAG for `make rollback`
#   9. stop the old color (kept stopped, not removed -> instant rollback)
#   10. inaugural only: remove the legacy single-`web` container
#
# Safety: the old color keeps serving until step 7. A smoke/health failure exits
# BEFORE the flip, so prod never routes to a broken image. The first deploy
# (no ACTIVE_COLOR file yet) treats `blue` as the initial color.

set -euo pipefail

cd /opt/vfic

IMAGE_TAG="${IMAGE_TAG:?IMAGE_TAG is required (passed by Makefile)}"
WORKERS="worker-chatbot worker-persistence worker-ingest worker-followup scheduler"
ACTIVE_FILE="/opt/vfic/ACTIVE_COLOR"
PREV_COLOR_FILE="/opt/vfic/PREV_COLOR"
PREV_TAG_FILE="/opt/vfic/PREV_TAG"

opposite() { [ "$1" = "blue" ] && echo green || echo blue; }

if [ -f "$ACTIVE_FILE" ] && [ -s "$ACTIVE_FILE" ]; then
  ACTIVE="$(cat "$ACTIVE_FILE" | tr -d '[:space:]')"
else
  ACTIVE=""
fi
# Inaugural deploy: ACTIVE is empty -> bring up blue first.
NEXT="$(opposite "${ACTIVE:-blue}")"
echo "==> bg_deploy: active=${ACTIVE:-<inaugural>} next=$NEXT tag=$IMAGE_TAG"

# 1. Pull the new image (web + workers share franknguyenvd/vfic-backend:$TAG).
echo "==> [1/10] pulling images..."
IMAGE_TAG="$IMAGE_TAG" docker compose pull "web-$NEXT" $WORKERS

# 2. Postgres + Redis (idempotent; never --force-recreate the data stores).
echo "==> [2/10] ensuring postgres + redis..."
IMAGE_TAG="$IMAGE_TAG" docker compose up -d postgres redis
for i in $(seq 1 30); do
  if IMAGE_TAG="$IMAGE_TAG" docker compose exec -T postgres pg_isready -U vfic >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

# 3. Migrations (widen alembic version column, then upgrade). Additive migrations
#    are safe for blue/green (old color runs against the migrated schema too).
echo "==> [3/10] alembic widen + upgrade head..."
IMAGE_TAG="$IMAGE_TAG" docker compose run --rm --no-deps web-blue \
  sh -c 'python -m scripts.widen_alembic_version && alembic upgrade head'

# 4. Bring up the new color + workers at the new tag.
echo "==> [4/10] bringing up web-$NEXT + workers at $IMAGE_TAG..."
IMAGE_TAG="$IMAGE_TAG" docker compose up -d --no-deps --force-recreate "web-$NEXT" $WORKERS

# 5. Wait for the new color's healthcheck to pass.
echo "==> [5/10] waiting for web-$NEXT healthy..."
cid="$(IMAGE_TAG="$IMAGE_TAG" docker compose ps -q "web-$NEXT")"
ok=0
for i in $(seq 1 60); do
  st="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "")"
  if [ "$st" = "healthy" ]; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != "1" ]; then
  echo "==> web-$NEXT did not become healthy. ABORTING — ${ACTIVE:-<none>} keeps serving." >&2
  exit 1
fi

# 6. SMOKE GATE — one real bot turn on the new image. This is what catches a bad
#    image that boots and passes /health but crashes mid-turn (the 2026-07
#    outage class). Failure aborts before the flip.
echo "==> [6/10] smoke gate on web-$NEXT..."
if ! IMAGE_TAG="$IMAGE_TAG" docker compose exec -T "web-$NEXT" python -m scripts.smoke_turn; then
  echo "==> SMOKE GATE FAILED on web-$NEXT. ABORTING — ${ACTIVE:-<none>} keeps serving." >&2
  exit 1
fi

# 7. Flip Caddy onto the new color (graceful, <1s, no dropped connections).
echo "==> [7/10] flipping Caddy -> web-$NEXT..."
IMAGE_TAG="$IMAGE_TAG" ./scripts/flip_caddy.sh "$NEXT"

# 8. Record rollback state BEFORE changing ACTIVE (so a crash here is safe).
if [ -n "$ACTIVE" ]; then
  old_cid="$(IMAGE_TAG="$IMAGE_TAG" docker compose ps -q "web-$ACTIVE" 2>/dev/null || true)"
  if [ -n "$old_cid" ]; then
    old_img="$(docker inspect --format '{{.Config.Image}}' "$old_cid" 2>/dev/null || echo "")"
    echo "${old_img##*:}" > "$PREV_TAG_FILE"
  fi
  echo "$ACTIVE" > "$PREV_COLOR_FILE"
fi

# 9. Stop the old color (kept for instant rollback via `make rollback`).
if [ -n "$ACTIVE" ]; then
  echo "==> [9/10] draining old web-$ACTIVE for 5s, then stopping..."
  sleep 5
  IMAGE_TAG="$IMAGE_TAG" docker compose stop "web-$ACTIVE" || true
else
  echo "==> [9/10] inaugural deploy — no old color to stop."
fi

echo "$NEXT" > "$ACTIVE_FILE"

# Start the resumable OA-only profile sweep only after traffic is on the healthy
# new color. It is detached so Zalo calls cannot delay or roll back a cutover.
echo "==> [9b/10] starting missing OA profile backfill..."
if ! IMAGE_TAG="$IMAGE_TAG" docker compose exec -T -d "web-$NEXT" \
  python -m scripts.backfill_oa_profiles --apply --limit "${OA_PROFILE_BACKFILL_LIMIT:-0}"; then
  echo "==> OA profile backfill start failed; deployment remains active." >&2
fi

# 10. Inaugural only: remove the legacy single-`web` container (no longer in the
#     compose). Try both compose v2 naming conventions; ignore if absent.
if [ -z "$ACTIVE" ]; then
  echo "==> [10/10] inaugural: removing legacy single-web container if present..."
  for legacy in vfic-web-1 vfic_web_1; do
    docker rm -f "$legacy" >/dev/null 2>&1 || true
  done
fi

echo "==============================================================="
echo " bg_deploy done. active=web-$NEXT  tag=$IMAGE_TAG"
echo "   health  : https://bot.tingting.vip/health"
echo "   rollback: make rollback"
echo "==============================================================="
