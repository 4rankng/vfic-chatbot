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
  RECLAIM_KB="$(docker system df -v 2>/dev/null | awk '/Total reclaimable/ {print $3}' | head -1)"
  # `docker system df -v` prints e.g. "Total reclaimable:  12.34GB"; fall back to
  # the plain table when the verbose header differs across versions.
  RECLAIM_BYTES="$(docker system df --format '{{.Reclaimable}}' 2>/dev/null | head -1)"
  if [ -n "${RECLAIM_BYTES:-}" ]; then
    warn_if="$(echo "$RECLAIM_BYTES" | numfmt --from=iec 2>/dev/null || echo 0)"
    [ "${warn_if:-0}" -gt 10737418240 ] && warn "docker reclaimable ${RECLAIM_BYTES} (>10GB) — prune dangling images"
  fi
  unset RECLAIM_KB
fi

# --- 3. metrics from inside the live web container ---------------------------
if command -v docker >/dev/null 2>&1; then
  COLOR="$(cat ACTIVE_COLOR 2>/dev/null || echo blue)"
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
