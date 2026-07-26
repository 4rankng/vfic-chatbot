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
PUBLIC_BASE_URL="https://bot.tingting.vip"

_count_lines() {
  awk 'NF { count += 1 } END { print count + 0 }'
}

require_running_service_count() {
  local service="$1" expected="$2"
  local cids cid state health restart found=0 actual_count
  cids="$(IMAGE_TAG="$PREV_TAG" docker compose ps -q "$service" 2>/dev/null || true)"
  if [ -z "$cids" ]; then
    echo "==> rollback check: service $service has no running container" >&2
    return 1
  fi
  actual_count="$(printf '%s\n' "$cids" | _count_lines)"
  if [ "$actual_count" != "$expected" ]; then
    echo "==> rollback check: service $service expected $expected running container(s), found $actual_count" >&2
    return 1
  fi
  while IFS= read -r cid; do
    [ -n "$cid" ] || continue
    found=1
    state="$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo unknown)"
    restart="$(docker inspect --format '{{.RestartCount}}' "$cid" 2>/dev/null || echo '?')"
    echo "    rollback service $service container=$cid state=$state health=$health restarts=$restart"
    if [ "$state" != "running" ]; then
      return 1
    fi
    if [ "$health" != "none" ] && [ "$health" != "healthy" ]; then
      return 1
    fi
  done <<EOF
$cids
EOF
  [ "$found" = "1" ]
}

assert_caddy_routes_color() {
  local color="$1"
  if ! grep -q "web-${color}:8000" Caddyfile; then
    echo "==> rollback check: Caddyfile does not route to web-$color:8000" >&2
    return 1
  fi
  echo "    rollback Caddyfile routes to web-$color:8000"
}

verify_post_flip_readiness() {
  local color="$1" expected_tag="$2"
  local active_cid active_img active_tag public_health_body

  echo "==> rollback verify_post_flip_readiness: public edge, active tag, frontend, and queue health"

  active_cid="$(IMAGE_TAG="$PREV_TAG" docker compose ps -q "web-$color" 2>/dev/null || true)"
  if [ -z "$active_cid" ]; then
    echo "==> rollback check: web-$color container missing" >&2
    return 1
  fi
  active_img="$(docker inspect --format '{{.Config.Image}}' "$active_cid" 2>/dev/null || echo "")"
  active_tag="${active_img##*:}"
  echo "    rollback active web-$color image=$active_img"
  if [ "$active_tag" != "$expected_tag" ]; then
    echo "==> rollback check: active web-$color tag $active_tag did not match expected $expected_tag" >&2
    return 1
  fi

  assert_caddy_routes_color "$color" || return 1

  public_health_body="$(curl -fsS --max-time 15 "$PUBLIC_BASE_URL/health")" || {
    echo "==> rollback check: public /health request failed" >&2
    return 1
  }
  python3 - "$public_health_body" <<'PY'
import json
import sys

body = json.loads(sys.argv[1])
if body.get("status") != "ok":
    raise SystemExit(f"public /health returned status={body.get('status')!r}")
PY

  curl -fsS --max-time 15 "https://bot.tingting.vip/" >/dev/null || {
    echo "==> rollback check: frontend root request failed" >&2
    return 1
  }

  require_running_service_count "frontend" 1 || return 1
  require_running_service_count "worker-chatbot" 2 || return 1
  require_running_service_count "worker-persistence" 1 || return 1
  require_running_service_count "worker-ingest" 1 || return 1
  require_running_service_count "worker-followup" 1 || return 1
  require_running_service_count "scheduler" 1 || return 1

  IMAGE_TAG="$PREV_TAG" docker compose exec -T "web-$color" python - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/health/queue", timeout=10) as response:
    data = json.load(response)

required = (
    "queue_depth",
    "busy_workers",
    "total_workers",
    "llm_avg_latency_ms",
    "llm_invokes_last_2m",
    "minimax_429s_last_1m",
)
missing = [key for key in required if key not in data]
if missing:
    raise SystemExit(f"/health/queue missing keys: {missing}")

queue_depth = data["queue_depth"]
busy_workers = data["busy_workers"]
total_workers = data["total_workers"]
if not isinstance(queue_depth, int) or queue_depth < 0:
    raise SystemExit(f"queue_depth invalid: {queue_depth!r}")
if not isinstance(total_workers, int) or total_workers < 5:
    raise SystemExit(f"total_workers invalid: {total_workers!r}")
if not isinstance(busy_workers, int) or busy_workers < 0 or busy_workers > total_workers:
    raise SystemExit(
        f"busy_workers invalid: {busy_workers!r} total_workers={total_workers!r}"
    )
print(json.dumps({"queue_depth": queue_depth, "busy_workers": busy_workers, "total_workers": total_workers}))
PY
}

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

if ! verify_post_flip_readiness "$PREV" "$PREV_TAG"; then
  echo "==> rollback verification failed; web-$PREV stays running, web-$ACTIVE remains available, and state files are unchanged. Operator intervention required." >&2
  exit 1
fi

# Swap ACTIVE <-> PREV so rollback is reversible.
demoted_cids="$(IMAGE_TAG="$PREV_TAG" docker compose ps -q "web-$ACTIVE" 2>/dev/null || true)"
demoted_count="$(printf '%s\n' "$demoted_cids" | _count_lines)"
if [ "$demoted_count" != "1" ]; then
  echo "==> rollback reversibility check failed; expected exactly one demoted web-$ACTIVE container, found $demoted_count. Both colors stay running and state files are unchanged. Operator intervention required." >&2
  exit 1
fi
demoted_cid="$(printf '%s\n' "$demoted_cids" | awk 'NF { print; exit }')"
demoted_img="$(docker inspect --format '{{.Config.Image}}' "$demoted_cid" 2>/dev/null || echo "")"
demoted_tag="${demoted_img##*:}"
if [ -z "$demoted_img" ] || [ -z "$demoted_tag" ]; then
  echo "==> rollback reversibility check failed; web-$ACTIVE image tag could not be inspected. Both colors stay running and state files are unchanged. Operator intervention required." >&2
  exit 1
fi
echo "$demoted_tag" > "$PREV_TAG_FILE"
echo "$ACTIVE" > "$PREV_COLOR_FILE"
echo "$PREV" > "$ACTIVE_FILE"

# Stop the demoted color.
IMAGE_TAG="$PREV_TAG" docker compose stop "web-$ACTIVE" || true

echo "==============================================================="
echo " bg_rollback done. active=web-$PREV tag=$PREV_TAG"
echo "   health: https://bot.tingting.vip/health"
echo "==============================================================="
