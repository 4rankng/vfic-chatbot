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
PUBLIC_BASE_URL="https://bot.tingting.vip"

opposite() { [ "$1" = "blue" ] && echo green || echo blue; }

_count_lines() {
  awk 'NF { count += 1 } END { print count + 0 }'
}

require_running_service_count() {
  local service="$1" expected="$2"
  local cids cid state health restart found=0
  cids="$(IMAGE_TAG="$IMAGE_TAG" docker compose ps -q "$service" 2>/dev/null || true)"
  if [ -z "$cids" ]; then
    echo "==> post-flip check: service $service has no running container" >&2
    return 1
  fi
  actual_count="$(printf '%s\n' "$cids" | _count_lines)"
  if [ "$actual_count" != "$expected" ]; then
    echo "==> post-flip check: service $service expected $expected running container(s), found $actual_count" >&2
    return 1
  fi
  while IFS= read -r cid; do
    [ -n "$cid" ] || continue
    found=1
    state="$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo unknown)"
    restart="$(docker inspect --format '{{.RestartCount}}' "$cid" 2>/dev/null || echo '?')"
    echo "    service $service container=$cid state=$state health=$health restarts=$restart"
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
    echo "==> post-flip check: Caddyfile does not route to web-$color:8000" >&2
    return 1
  fi
  echo "    Caddyfile routes to web-$color:8000"
}

verify_post_flip_readiness() {
  local color="$1"
  local active_cid active_img active_tag public_health_body

  echo "==> [8b/10] verify_post_flip_readiness: public edge, active tag, frontend, and queue health"

  active_cid="$(IMAGE_TAG="$IMAGE_TAG" docker compose ps -q "web-$color" 2>/dev/null || true)"
  if [ -z "$active_cid" ]; then
    echo "==> post-flip check: web-$color container missing" >&2
    return 1
  fi
  active_img="$(docker inspect --format '{{.Config.Image}}' "$active_cid" 2>/dev/null || echo "")"
  active_tag="${active_img##*:}"
  echo "    active web-$color image=$active_img"
  if [ "$active_tag" != "$IMAGE_TAG" ]; then
    echo "==> post-flip check: active web-$color tag $active_tag did not match expected $IMAGE_TAG" >&2
    return 1
  fi

  assert_caddy_routes_color "$color" || return 1

  public_health_body="$(curl -fsS --max-time 15 "$PUBLIC_BASE_URL/health")" || {
    echo "==> post-flip check: public /health request failed" >&2
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
    echo "==> post-flip check: frontend root request failed" >&2
    return 1
  }

  # Workers are recreated at the new tag before the flip and only the web
  # color got a dedicated health wait; their healthchecks (start_period 15s +
  # 5 retries x 30s) legitimately need minutes after boot warmup. Poll within
  # a bounded budget instead of demanding instant health.
  local _deadline=$(( $(date +%s) + ${POST_FLIP_WAIT_BUDGET:-300} ))
  while :; do
    require_running_service_count "frontend" 1 &&
      require_running_service_count "worker-chatbot" 2 &&
      require_running_service_count "worker-persistence" 1 &&
      require_running_service_count "worker-ingest" 1 &&
      require_running_service_count "worker-followup" 1 &&
      require_running_service_count "scheduler" 1 && break
    if [ "$(date +%s)" -ge "$_deadline" ]; then
      echo "==> post-flip check: services still not ready after ${POST_FLIP_WAIT_BUDGET:-300}s budget" >&2
      return 1
    fi
    sleep 10
  done

  IMAGE_TAG="$IMAGE_TAG" docker compose exec -T "web-$color" python - <<'PY'
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

rollback_post_flip_failure() {
  echo "==> POST-FLIP VERIFICATION FAILED: $1" >&2
  if [ -n "$ACTIVE" ] && [ -s "$PREV_COLOR_FILE" ] && [ -s "$PREV_TAG_FILE" ]; then
    echo "==> rolling back to previous color via bg_rollback.sh..." >&2
    if bash scripts/bg_rollback.sh; then
      echo "==> rollback complete; previous color restored." >&2
    else
      echo "==> rollback failed; manual intervention required." >&2
    fi
  else
    echo "==> inaugural deploy has no previous color; web-$NEXT stays running and Caddy remains routed there. Operator intervention required." >&2
  fi
  exit 1
}

if [ -f "$ACTIVE_FILE" ] && [ -s "$ACTIVE_FILE" ]; then
  ACTIVE="$(cat "$ACTIVE_FILE" | tr -d '[:space:]')"
else
  ACTIVE=""
fi
# Inaugural deploy: ACTIVE is empty -> bring up blue first.
if [ -n "$ACTIVE" ]; then
  NEXT="$(opposite "$ACTIVE")"
else
  NEXT="blue"
fi
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

# 5. Wait for the new color's healthcheck to pass. Cold-boot on the droplet can
#    exceed 120s (image pull + uvicorn + scheduler registration + DB-pool
#    warmup), so budget 240s and log progress — a silent abort is impossible to
#    diagnose after the failed-run container is gone.
echo "==> [5/10] waiting for web-$NEXT healthy (budget 240s)..."
cid="$(IMAGE_TAG="$IMAGE_TAG" docker compose ps -q "web-$NEXT")"
ok=0
for i in $(seq 1 120); do
  st="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "")"
  if [ "$st" = "healthy" ]; then ok=1; break; fi
  if [ $((i % 10)) -eq 0 ]; then
    rc="$(docker inspect --format '{{.RestartCount}}' "$cid" 2>/dev/null || echo '?')"
    echo "    ...still ${st:-unknown} after $((i * 2))s (restarts=$rc)"
  fi
  sleep 2
done
if [ "$ok" != "1" ]; then
  echo "==> web-$NEXT did not become healthy within 240s (last status: ${st:-unknown}). ABORTING — ${ACTIVE:-<none>} keeps serving." >&2
  echo "==> last 40 log lines from web-$NEXT:" >&2
  docker logs --tail=40 "$cid" >&2 2>/dev/null || true
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
echo "$NEXT" > "$ACTIVE_FILE"

if ! verify_post_flip_readiness "$NEXT"; then
  rollback_post_flip_failure "new route failed health/frontend/queue verification"
fi

# 9. Stop the old color (kept for instant rollback via `make rollback`).
if [ -n "$ACTIVE" ]; then
  echo "==> [9/10] draining old web-$ACTIVE for 5s, then stopping..."
  sleep 5
  IMAGE_TAG="$IMAGE_TAG" docker compose stop "web-$ACTIVE" || true
else
  echo "==> [9/10] inaugural deploy — no old color to stop."
fi

# Start the resumable OA-only profile sweep only after traffic is on the healthy
# new color. Its dedicated container has inspectable logs and exit status, while
# its PostgreSQL advisory lock prevents overlapping runs.
echo "==> [9b/10] starting missing OA profile backfill..."
if old_backfill_id="$(docker compose --profile maintenance ps -aq oa-profile-backfill)" && \
  [ -n "$old_backfill_id" ]; then
  echo "==> previous OA profile backfill status: $(docker inspect --format '{{.State.Status}} exit={{.State.ExitCode}}' "$old_backfill_id" 2>/dev/null || echo unknown)"
  docker compose --profile maintenance logs --tail=20 oa-profile-backfill || true
fi
if ! IMAGE_TAG="$IMAGE_TAG" docker compose --profile maintenance up -d --no-deps \
  --force-recreate oa-profile-backfill; then
  echo "==> OA profile backfill start failed; deployment remains active." >&2
else
  echo "==> OA profile backfill started. Status: make -C backend profile-backfill-status"
  echo "==> OA profile backfill logs  : make -C backend profile-backfill-logs"
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
