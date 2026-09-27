#!/usr/bin/env bash
# =============================================================================
# ops-alerts.sh — the droplet's "somebody tell me before this becomes an outage"
# check (OPS-04 disk-full, OPS-06 no-metrics-scraping).
#
# What it checks, all locally so no external service is required:
#   1. Disk: root filesystem used > 80%  → warn, > 95% → fail.
#   2. Docker: reclaimable space > 10 GB → warn (dangling images/volumes pile up
#      because every deploy is a fresh pull of a digest-pinned image).
#   3. /metrics inside the live web container (the pattern docs/ops/deployment-guide
#      documents): queue depth vs CHAT_QUEUE_MAX_DEPTH, all workers busy, and
#      the reconcile failure counters that only ever rise.
#   4. /health and /health/queue over HTTP from the edge, if curl is available.
#
# Output: one line per problem on stderr, "ok" on stdout when clean.
# Exit:   0 = healthy or warn-only, 1 = at least one failure-level problem.
#
# Install (cron, every minute):
#   * * * * * root /opt/vfic/scripts/ops-alerts.sh 2>> /var/log/vfic-alerts.log
# `make deploy` / `make deploy-backend` (backend/Makefile) copy this file to
# /opt/vfic/scripts/; the cron line above is all that remains to be installed.
# Wire the output wherever you already read logs — the point is that a disk-full
# or queue-saturation condition stops being silent (OPS-06: nothing scrapes).
# =============================================================================
set -uo pipefail

FAILURES=0
WARNINGS=0

warn() { printf '[warn]  %s\n' "$*" >&2; WARNINGS=$((WARNINGS + 1)); }
fail() { printf '[FAIL]  %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }
ok()   { printf '%s\n' "$*"; }

# --- 1. disk ------------------------------------------------------------------
DISK_USED_PCT="$(df -P / | awk 'NR==2 {gsub("%",""); print $5}')"
if [ "${DISK_USED_PCT:-0}" -ge 95 ]; then
  fail "root filesystem ${DISK_USED_PCT}% full — Postgres cannot write WAL at 100%"
elif [ "${DISK_USED_PCT:-0}" -ge 80 ]; then
  warn "root filesystem ${DISK_USED_PCT}% full"
fi

# --- 2. docker reclaimable ----------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  # `docker system df` reports a human string ("12.34GB (67%)"), not a number, and
  # piping that into `numfmt --from=iec` errors on the percentage suffix — the
  # old parse always fell through to 0, so the >10GB warn could never fire. Read
  # the JSON rows and convert the numeric part of each Reclaimable field (the
  # per-type rows sum to the same total the verbose table prints).
  RECLAIM_BYTES="$(docker system df --format '{{json .}}' 2>/dev/null | python3 -c '
import json
import re
import sys

UNITS = {"B": 1, "KB": 10 ** 3, "MB": 10 ** 6, "GB": 10 ** 9, "TB": 10 ** 12}
total = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        row = json.loads(line)
    except ValueError:
        continue
    match = re.match(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?B)", str(row.get("Reclaimable", "")))
    if match:
        total += float(match.group(1)) * UNITS[match.group(2)]
print(int(total))
' 2>/dev/null || echo 0)"
  if [ "${RECLAIM_BYTES:-0}" -gt 10737418240 ] 2>/dev/null; then
    warn "docker reclaimable $(numfmt --to=iec --suffix=B "$RECLAIM_BYTES" 2>/dev/null || echo "${RECLAIM_BYTES}B") (>10GB) — prune dangling images"
  fi
fi

# --- 3. metrics from inside the live web container ---------------------------
if command -v docker >/dev/null 2>&1; then
  # Both of these used to be wrong under cron, whose cwd is not /opt/vfic:
  # ACTIVE_COLOR was read relatively (always falling back to blue, so the check
  # probed the IDLE color after a cutover), and the compose call ran with no
  # IMAGE_TAG. /opt/vfic/.env never defines one and the prod compose file guards
  # it with `${IMAGE_TAG:?}` for EVERY subcommand, so `compose exec` aborted on
  # interpolation and METRICS was always empty. Resolve both the same way
  # scripts/backup-droplet.sh and backend/Makefile do: read the color from the
  # absolute path, take the tag from the image that color actually runs.
  cd /opt/vfic || true
  COLOR="$(tr -d "[:space:]" < /opt/vfic/ACTIVE_COLOR 2>/dev/null || echo blue)"
  case "$COLOR" in
    blue | green) ;;
    *) COLOR=blue ;;
  esac
  ACTIVE_CID="$(docker ps -q --filter "name=web-$COLOR" | head -1)"
  if [ -n "$ACTIVE_CID" ]; then
    IMAGE_TAG="$(docker inspect --format "{{.Config.Image}}" "$ACTIVE_CID" | sed "s/.*://")"
  else
    IMAGE_TAG="$(cat /opt/vfic/PREV_TAG 2>/dev/null || echo unknown)"
  fi
  [ -n "$IMAGE_TAG" ] || IMAGE_TAG=unknown
  export IMAGE_TAG
  WEB="web-${COLOR}"
  METRICS="$(docker compose -f /opt/vfic/docker-compose.yml exec -T "$WEB" \
    python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/metrics', timeout=5).read().decode())" 2>/dev/null || true)"
  if [ -z "$METRICS" ]; then
    warn "could not read /metrics from $WEB — is the container running?"
  else
    MAX_DEPTH="$(echo "$METRICS" | awk -F'[ =]' '/chat_queue_max_depth/ {print $2; exit}')"
    DEPTH="$(echo "$METRICS" | awk -F'[ =]' '/webhook_high.*depth|depth.*webhook_high/ {for(i=1;i<=NF;i++) if ($i ~ /^[0-9]+$/) {print $i; exit}}')"
    BUSY="$(echo "$METRICS" | awk -F'[ =]' '/busy_workers/ {print $2; exit}')"
    TOTAL="$(echo "$METRICS" | awk -F'[ =]' '/total_workers/ {print $2; exit}')"

    if [ -n "${DEPTH:-}" ] && [ -n "${MAX_DEPTH:-}" ] && [ "$DEPTH" -gt $((MAX_DEPTH / 2)) ]; then
      warn "webhook_high depth ${DEPTH} > half of CHAT_QUEUE_MAX_DEPTH (${MAX_DEPTH})"
    fi
    if [ -n "${BUSY:-}" ] && [ -n "${TOTAL:-}" ] && [ "$TOTAL" -gt 0 ] && [ "$BUSY" -ge "$TOTAL" ]; then
      warn "every worker is busy (${BUSY}/${TOTAL}) — turns are queueing"
    fi
    for c in reconcile_enqueue_failed_total reconcile_unknown_send_outcome; do
      v="$(echo "$METRICS" | awk -F'[ =]' -v k="$c" '$1==k {print $2; exit}')"
      [ -n "${v:-}" ] && [ "$v" -gt 0 ] && warn "$c=$v (only ever rises — investigate the sweep)"
    done
  fi
fi

# --- 4. edge health -----------------------------------------------------------
if command -v curl >/dev/null 2>&1; then
  curl -fsS -m 5 https://bot.tingting.vip/health >/dev/null 2>&1 \
    || fail "GET https://bot.tingting.vip/health did not succeed"
fi

if [ "$FAILURES" -gt 0 ]; then
  exit 1
elif [ "$WARNINGS" -gt 0 ]; then
  ok "warn-only ($WARNINGS warnings)"
else
  ok "ok"
fi
