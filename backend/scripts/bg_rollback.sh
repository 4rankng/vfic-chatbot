#!/usr/bin/env bash
# bg_rollback.sh — flip traffic back to the previous color/tag. ~1s, no rebuild.
#
# Revives the previously-deployed web color at its recorded tag, recreates the
# workers to match, flips Caddy back, and stops the just-demoted color. Swaps
# ACTIVE<->PREV so rollback is itself reversible. Requires that a successful
# bg_deploy.sh ran first (it writes PREV_COLOR/PREV_TAG).

set -euo pipefail

cd /opt/vfic

ACTIVE_FILE="/opt/vfic/ACTIVE_COLOR"
PREV_COLOR_FILE="/opt/vfic/PREV_COLOR"
PREV_TAG_FILE="/opt/vfic/PREV_TAG"
WORKERS="worker-chatbot worker-persistence worker-ingest worker-followup scheduler"

ACTIVE="$(tr -d '[:space:]' < "$ACTIVE_FILE" 2>/dev/null || true)"
PREV="$(tr -d '[:space:]' < "$PREV_COLOR_FILE" 2>/dev/null || true)"
PREV_TAG="$(tr -d '[:space:]' < "$PREV_TAG_FILE" 2>/dev/null || true)"

if [ -z "$PREV" ] || [ -z "$PREV_TAG" ]; then
  echo "bg_rollback: no PREV_COLOR/PREV_TAG recorded (run a blue/green deploy first)" >&2
  exit 2
fi

echo "==> bg_rollback: active=$ACTIVE -> prev=$PREV tag=$PREV_TAG"

# Stop maintenance code from the demoted image before reviving the previous
# application version. The database eligibility checkpoint makes a later run
# resumable; a rejected image must not keep mutating production after rollback.
docker compose --profile maintenance stop oa-profile-backfill || true

# Revive the previous color at its tag + bring workers to the same tag.
IMAGE_TAG="$PREV_TAG" docker compose up -d --no-deps --force-recreate "web-$PREV" $WORKERS

# Wait for it healthy before flipping.
cid="$(IMAGE_TAG="$PREV_TAG" docker compose ps -q "web-$PREV")"
ok=0
for i in $(seq 1 60); do
  st="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "")"
  if [ "$st" = "healthy" ]; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != "1" ]; then
  echo "==> web-$PREV did not become healthy. ABORTING — web-$ACTIVE keeps serving." >&2
  exit 1
fi

# Flip Caddy back (graceful).
IMAGE_TAG="$PREV_TAG" ./scripts/flip_caddy.sh "$PREV"

# Swap ACTIVE <-> PREV so rollback is reversible.
demoted_cid="$(IMAGE_TAG="$PREV_TAG" docker compose ps -q "web-$ACTIVE" 2>/dev/null || true)"
if [ -n "$demoted_cid" ]; then
  demoted_img="$(docker inspect --format '{{.Config.Image}}' "$demoted_cid" 2>/dev/null || echo "")"
  echo "${demoted_img##*:}" > "$PREV_TAG_FILE"
fi
echo "$ACTIVE" > "$PREV_COLOR_FILE"
echo "$PREV" > "$ACTIVE_FILE"

# Stop the demoted color.
IMAGE_TAG="$PREV_TAG" docker compose stop "web-$ACTIVE" || true

echo "==============================================================="
echo " bg_rollback done. active=web-$PREV tag=$PREV_TAG"
echo "   health: https://bot.tingting.vip/health"
echo "==============================================================="
