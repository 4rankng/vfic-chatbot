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
WORKERS="worker-chatbot worker-persistence worker-ingest worker-followup scheduler worker-maintenance metrics-watch"
PUBLIC_BASE_URL="https://bot.tingting.vip"

_count_lines() {
  awk 'NF { count += 1 } END { print count + 0 }'
}

# Expected container count for a service, read from the compose file
# (``deploy.replicas``) instead of a literal. A hardcoded 2 here aborted the
# 2026-09-22 deploy *after* the flip once worker-chatbot moved to 3 replicas, and
# the same literal in bg_rollback.sh then failed the rollback verification too.
# Falls back to 1 when the count cannot be read, which is safe because the check
# only fails when FEWER containers are running than declared.
declared_replicas() {
  local service="$1" value
  value="$(
    IMAGE_TAG="${IMAGE_TAG:-latest}" docker compose config --format json 2>/dev/null \
      | python3 -c '
import json, sys

services = json.load(sys.stdin).get("services", {})
service = services.get(sys.argv[1], {})
replicas = service.get("deploy", {}).get("replicas", 1)
print(replicas if isinstance(replicas, int) and replicas > 0 else 1)
' "$service" 2>/dev/null || true
  )"
  case "$value" in
    '' | *[!0-9]*) echo 1 ;;
    *) echo "$value" ;;
  esac
}

require_running_service_count() {
  local service="$1" expected="${2:-}"
  [ -n "$expected" ] || expected="$(declared_replicas "$service")"
  local cids cid state health restart found=0 actual_count
  cids="$(IMAGE_TAG="$PREV_TAG" docker compose ps -q "$service" 2>/dev/null || true)"
  if [ -z "$cids" ]; then
    echo "==> rollback check: service $service has no running container" >&2
    return 1
  fi
  actual_count="$(printf '%s\n' "$cids" | _count_lines)"
  if [ "$actual_count" -lt "$expected" ]; then
    echo "==> rollback check: service $service expected at least $expected running container(s), found $actual_count" >&2
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

service_healthy_count() {
  local service="$1" cid count=0
  for cid in $(IMAGE_TAG="$IMAGE_TAG" docker compose ps -q "$service" 2>/dev/null || true); do
    [ -n "$cid" ] || continue
    if [ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo unknown)" = "healthy" ]; then
      count=$((count + 1))
    fi
  done
  echo "$count"
}

# The oldest running container of $service still on a tag other than $IMAGE_TAG.
stale_service_container() {
  local service="$1" cid image
  for cid in $(IMAGE_TAG="$IMAGE_TAG" docker compose ps -q "$service" 2>/dev/null || true); do
    [ -n "$cid" ] || continue
    image="$(docker inspect --format '{{.Config.Image}}' "$cid" 2>/dev/null || echo "")"
    if [ "${image##*:}" != "$IMAGE_TAG" ]; then
      echo "$cid"
      return 0
    fi
  done
  return 1
}

# Recreate $service replicas ONE AT A TIME (see the long note in bg_deploy.sh).
# Kept as a copy rather than a shared library on purpose: this script is the
# emergency path and must not depend on a sibling file being present on the
# droplet. Duplicating the helper follows the convention already used for
# _count_lines / declared_replicas / require_running_service_count here.
rolling_recreate_service() {
  local service="$1"
  local expected stale replaced=0 waited
  local budget="${ROLLING_HEALTH_BUDGET:-180}"
  expected="$(declared_replicas "$service")"

  if [ "$expected" -le 1 ]; then
    echo "==> rollback rolling recreate $service: 1 replica, single recreate"
    IMAGE_TAG="$IMAGE_TAG" docker compose up -d --no-deps --force-recreate "$service"
    return 0
  fi

  echo "==> rollback rolling recreate $service: $expected replicas, one at a time (keeping $((expected - 1)) consuming)"
  while stale="$(stale_service_container "$service")"; do
    echo "    replacing stale container=$stale"
    docker rm -f "$stale" >/dev/null 2>&1 || true
    IMAGE_TAG="$IMAGE_TAG" docker compose up -d --no-deps --no-recreate \
      --scale "$service=$expected" "$service" >/dev/null
    replaced=$((replaced + 1))
    waited=0
    while [ "$(service_healthy_count "$service")" -lt "$((expected - 1))" ] && [ "$waited" -lt "$budget" ]; do
      sleep 2
      waited=$((waited + 2))
    done
    if [ "$replaced" -ge "$expected" ]; then
      break
    fi
  done

  IMAGE_TAG="$IMAGE_TAG" docker compose up -d --no-deps --no-recreate \
    --scale "$service=$expected" "$service" >/dev/null
  echo "    $service healthy replicas: $(service_healthy_count "$service")/$expected"
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

  # Same rationale and the same coverage as bg_deploy.sh: every $WORKERS
  # service is asserted, including worker-maintenance (the dispatcher that
  # pushes bot replies to Zalo) and metrics-watch, which were missing here.
  local _deadline=$(( $(date +%s) + ${POST_FLIP_WAIT_BUDGET:-300} ))
  while :; do
    require_running_service_count "frontend" &&
      require_running_service_count "worker-chatbot" &&
      require_running_service_count "worker-persistence" &&
      require_running_service_count "worker-ingest" &&
      require_running_service_count "worker-followup" &&
      require_running_service_count "scheduler" &&
      require_running_service_count "worker-maintenance" &&
      require_running_service_count "metrics-watch" && break
    if [ "$(date +%s)" -ge "$_deadline" ]; then
      echo "==> rollback check: services still not ready after ${POST_FLIP_WAIT_BUDGET:-300}s budget" >&2
      return 1
    fi
    sleep 10
  done

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

  # Pipeline gate (same rationale as bg_deploy.sh): workers existing is not the
  # same as work draining — assert no conversation is waiting for a reply.
  IMAGE_TAG="$PREV_TAG" docker compose exec -T "web-$color" python -m scripts.turn_pipeline_check || {
    echo "==> rollback check: turn pipeline stalled (inbound unanswered or outbox not draining)" >&2
    return 1
  }
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

# Revive the previous color at its tag + bring workers to the same tag. The
# turn worker is rolled one replica at a time so webhook_high keeps a live
# consumer across the restart (same defect class as bg_deploy.sh step 4).
NON_TURN_WORKERS=""
for svc in $WORKERS; do
  case " worker-chatbot " in
    *" $svc "*) continue ;;
  esac
  NON_TURN_WORKERS="$NON_TURN_WORKERS $svc"
done
# shellcheck disable=SC2086 # word-splitting the service list is intended
IMAGE_TAG="$PREV_TAG" docker compose up -d --no-deps --force-recreate "web-$PREV" $NON_TURN_WORKERS
IMAGE_TAG="$PREV_TAG"
export IMAGE_TAG
rolling_recreate_service worker-chatbot
if [ "$(service_healthy_count worker-chatbot)" -lt 1 ]; then
  echo "==> no healthy worker-chatbot replica after rollback; webhooks would queue unanswered" >&2
  exit 1
fi

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
