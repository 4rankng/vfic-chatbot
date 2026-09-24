#!/usr/bin/env bash
# =============================================================================
# restore-droplet.sh — rebuild the VFIC stack on a FRESH droplet from a bundle.
#
# Run ON THIS MAC; pushes to the new droplet via SSH (mirrors `make deploy`).
#   bash scripts/restore-droplet.sh --bundle backups/vfic-droplet-backup-<TS> \
#     [--host root@bot.tingting.vip] [--tag <image-tag>] [--dry-run]
#
# What it restores: /opt/vfic/{docker-compose.yml,Caddyfile(+template),.env},
#   pulls the images at the tag RECORDED IN THE BUNDLE, seeds Caddy TLS + KB
#   uploads volumes (best-effort), starts postgres+redis, loads the SQL dump,
#   runs `alembic upgrade head` and asserts the schema revision equals the
#   image's head, brings up the full stack, verifies the running tag.
# Redis starts FRESH (not restored). Postgres is restored from the dump (the
#   role password comes from the restored .env, so DATABASE_URL still matches).
# create_admin is skipped — the dump already has admins.
# =============================================================================
set -euo pipefail

BUNDLE=""
HOST="root@bot.tingting.vip"
TAG=""
DRY_RUN=0
SSH_OPTS=(-o ConnectTimeout=15 -o ServerAliveInterval=30)

usage() {
  sed -n '3,16p' "${BASH_SOURCE[0]}" >&2
  echo "usage: $0 --bundle <unzipped-bundle-dir> [--host root@bot.tingting.vip] [--tag <image-tag>] [--dry-run]" >&2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --bundle)  BUNDLE="$2"; shift 2;;
    --host)    HOST="$2";   shift 2;;
    --tag)     TAG="$2";    shift 2;;
    --dry-run) DRY_RUN=1;   shift;;
    -h|--help) usage; exit 0;;
    *) echo "unknown arg: $1" >&2; usage; exit 2;;
  esac
done

[ -n "$BUNDLE" ] || { echo "--bundle <dir> is required" >&2; usage; exit 2; }
BUNDLE="${BUNDLE%/}"
[ -f "$BUNDLE/env/opt-vfic.env" ]               || { echo "missing $BUNDLE/env/opt-vfic.env" >&2; exit 2; }
[ -f "$BUNDLE/postgres/vfic_pg_dump.sql.gz" ]   || { echo "missing $BUNDLE/postgres/vfic_pg_dump.sql.gz" >&2; exit 2; }
[ -f "$BUNDLE/config-snapshot/docker-compose.yml" ] || { echo "missing config-snapshot/docker-compose.yml" >&2; exit 2; }

# The edge config: prefer the RENDERED Caddyfile the bundle captured from the
# live droplet. A template-only bundle (older, or hand-built) is rendered below
# with the same __WEB_UPSTREAM__ substitution flip_caddy.sh performs, so a
# missing backend/Caddyfile in the repo can no longer block a restore.
CADDY_SOURCE=""
if [ -f "$BUNDLE/config-snapshot/Caddyfile" ]; then
  CADDY_SOURCE=rendered
elif [ -f "$BUNDLE/config-snapshot/Caddyfile.template" ]; then
  CADDY_SOURCE=template
else
  echo "missing config-snapshot/Caddyfile (or config-snapshot/Caddyfile.template) — the bundle carries no edge config" >&2
  exit 2
fi

# Which colour Caddy routes to. A rendered Caddyfile already encodes it; a
# template needs it to render, and the droplet needs it in ACTIVE_COLOR.
COLOR="blue"
if [ -f "$BUNDLE/manifests/active-color.txt" ]; then
  COLOR="$(tr -d '[:space:]' < "$BUNDLE/manifests/active-color.txt")"
fi
case "$COLOR" in
  blue|green) ;;
  *) echo "bundle manifests/active-color.txt holds '$COLOR' (expected blue|green)" >&2; exit 2 ;;
esac

# Every prod compose command needs IMAGE_TAG (`${IMAGE_TAG:?}` interpolates the
# whole file), and it must be the tag that produced this dump — NOT `latest`,
# which is re-pushed on every deploy. Precedence: --tag, then the tag the backup
# recorded, then the docker-images manifest; if none is available we fail closed
# rather than boot new code against the restored schema.
TAG_SOURCE="--tag"
if [ -z "$TAG" ]; then
  TAG_SOURCE="manifests/image-tag.txt"
  if [ -f "$BUNDLE/manifests/image-tag.txt" ]; then
    TAG="$(tr -d '[:space:]' < "$BUNDLE/manifests/image-tag.txt")"
  elif [ -f "$BUNDLE/manifests/docker-images.txt" ]; then
    TAG_SOURCE="manifests/docker-images.txt"
    TAG="$(awk '$2 ~ /tinghire-be/ && $3 != "" && $3 != "TAG" { print $3; exit }' "$BUNDLE/manifests/docker-images.txt")"
  fi
fi
case "$TAG" in
  ""|latest)
    echo "cannot determine the image tag this dump was taken at (got '${TAG:-<none>}' from $TAG_SOURCE)." >&2
    echo "Refusing to restore: compose would resolve ':latest' — code that did not produce this schema." >&2
    echo "Re-run with an explicit tag:  $0 --bundle $BUNDLE --tag <git-sha>" >&2
    exit 2 ;;
esac

# The dump's integration_settings rows are sealed with a key derived from
# INTEGRATION_SETTINGS_ENCRYPTION_KEY (JWT_SECRET is the legacy fallback). If the
# bundle lost it, every restored credential raises InvalidTag and is silently
# dropped — refuse instead.
env_value() { sed -n "s/^$1=//p" "$BUNDLE/env/opt-vfic.env" | tail -1; }
if [ -z "$(env_value INTEGRATION_SETTINGS_ENCRYPTION_KEY)" ]; then
  [ -n "$(env_value JWT_SECRET)" ] || {
    echo "bundle .env carries neither INTEGRATION_SETTINGS_ENCRYPTION_KEY nor JWT_SECRET —" >&2
    echo "the restored integration_settings rows would be undecryptable. Refusing to restore." >&2
    exit 2
  }
  echo "WARN: bundle .env has no INTEGRATION_SETTINGS_ENCRYPTION_KEY; the JWT_SECRET fallback seals the rows." >&2
fi

step() { printf '\n\033[1;36m[%s]\033[0m %s\n' "$1" "$2" >&2; }
RENDERED_TMP=""
cleanup() { [ -n "$RENDERED_TMP" ] && rm -f "$RENDERED_TMP"; return 0; }
trap cleanup EXIT
rmt()  {  # run remote (echoed; skipped in dry-run)
  printf '  $ ssh %s %s\n' "$HOST" "$*" >&2
  [ "$DRY_RUN" -eq 1 ] || ssh "${SSH_OPTS[@]}" "$HOST" "$@"
}
put() {  # scp local -> remote (echoed; skipped in dry-run)
  printf '  scp %s -> %s:%s\n' "$1" "$HOST" "$2" >&2
  [ "$DRY_RUN" -eq 1 ] || scp -q "${SSH_OPTS[@]}" "$1" "$HOST:$2"
}

echo "== VFIC droplet restore ==" >&2
echo "  bundle : $BUNDLE" >&2
echo "  host   : $HOST"   >&2
echo "  images : $TAG (from $TAG_SOURCE)" >&2
echo "  caddy  : $CADDY_SOURCE (active colour: $COLOR)" >&2
echo "  dry-run: $DRY_RUN" >&2

# --- 0. preflight -------------------------------------------------------------
step "0/8" "preflight: SSH + Docker + free ports 80/443"
if [ "$DRY_RUN" -eq 0 ]; then
  ssh "${SSH_OPTS[@]}" "$HOST" "echo SSH_OK" >/dev/null || { echo "cannot SSH to $HOST" >&2; exit 1; }
  if ! ssh "${SSH_OPTS[@]}" "$HOST" "docker compose version" >/dev/null 2>&1; then
    echo "Docker + compose plugin NOT installed on $HOST. Run first:" >&2
    echo "  ssh $HOST 'curl -fsSL https://get.docker.com | sh'" >&2
    exit 1
  fi
  if ssh "${SSH_OPTS[@]}" "$HOST" "ss -ltn '( sport = :80 or sport = :443 )' | grep -q LISTEN"; then
    echo "WARN: something already listens on :80/:443 on $HOST (Caddy may fail to bind)." >&2
    echo "      (deploy tears down /opt/n8n-docker-caddy to free them — check if n8n is running)." >&2
  fi
else
  echo "  (would verify SSH, docker compose, and free :80/:443)" >&2
fi

# --- 1. /opt/vfic + compose + Caddyfile + .env --------------------------------
step "1/7" "copying compose + Caddyfile + .env -> /opt/vfic"
rmt "mkdir -p /opt/vfic"
put "$BUNDLE/config-snapshot/docker-compose.yml" /opt/vfic/docker-compose.yml

# Ship the template when the bundle carries one (flip_caddy.sh re-renders from
# it on every later cutover), then install the active edge config: the rendered
# Caddyfile the backup captured, or — for a template-only bundle — the template
# rendered here with the same __WEB_UPSTREAM__ substitution flip_caddy.sh uses.
if [ -f "$BUNDLE/config-snapshot/Caddyfile.template" ]; then
  put "$BUNDLE/config-snapshot/Caddyfile.template" /opt/vfic/Caddyfile.template
fi
if [ "$CADDY_SOURCE" = rendered ]; then
  put "$BUNDLE/config-snapshot/Caddyfile" /opt/vfic/Caddyfile
else
  RENDERED_TMP="$(mktemp)"
  sed "s/__WEB_UPSTREAM__/web-${COLOR}/g" "$BUNDLE/config-snapshot/Caddyfile.template" > "$RENDERED_TMP"
  printf '  rendered Caddyfile from template (upstream: web-%s)\n' "$COLOR" >&2
  put "$RENDERED_TMP" /opt/vfic/Caddyfile
fi
printf '  restore /opt/vfic/.env (mode 600)\n' >&2
if [ "$DRY_RUN" -eq 0 ]; then
  cat "$BUNDLE/env/opt-vfic.env" | ssh "${SSH_OPTS[@]}" "$HOST" 'umask 077; cat > /opt/vfic/.env && chmod 600 /opt/vfic/.env'
fi

# --- 2. pull images -----------------------------------------------------------
step "2/7" "docker compose pull (re-pulls from DockerHub)"
rmt "cd /opt/vfic && docker compose pull"

# --- 3. seed Caddy TLS + KB uploads volumes (best-effort, BEFORE first up) -----
step "3/7" "seed Caddy TLS + KB uploads volumes (best-effort)"
seed() {  # $1 = service  $2 = in-container mount  $3 = tarball
  if [ -f "$3" ]; then
    printf '  seed %s:%s <- %s\n' "$1" "$2" "$3" >&2
    if [ "$DRY_RUN" -eq 0 ]; then
      gzip -dc "$3" | ssh "${SSH_OPTS[@]}" "$HOST" \
        "cd /opt/vfic && docker compose run -T --rm --no-deps --entrypoint /bin/sh $1 -c 'tar xzf /dev/stdin -C $2'" \
        || printf '  WARN: seed failed for %s:%s (continuing — Caddy auto-issues certs; KB originals are optional)\n' "$1" "$2" >&2
    fi
  else
    printf '  skip %s:%s (no %s in bundle)\n' "$1" "$2" "$3" >&2
  fi
}
seed caddy /data            "$BUNDLE/caddy/caddy_data.tar.gz"
seed caddy /config          "$BUNDLE/caddy/caddy_config.tar.gz"
# worker-ingest, not `web`: the compose file has no plain web service, and the
# ingest worker mounts vfic_kb_uploads whichever colour is active.
seed worker-ingest /data/kb_uploads "$BUNDLE/kb_uploads/kb_uploads.tar.gz"

# --- 4. start datastores ------------------------------------------------------
step "4/7" "start postgres + redis (empty volumes init from restored .env)"
rmt "cd /opt/vfic && docker compose up -d postgres redis"
printf '  waiting for pg_isready ...\n' >&2
if [ "$DRY_RUN" -eq 0 ]; then
  ok=0
  for _ in $(seq 1 30); do
    if ssh "${SSH_OPTS[@]}" "$HOST" "cd /opt/vfic && docker compose exec -T postgres pg_isready -U vfic" >/dev/null 2>&1; then ok=1; break; fi
    sleep 2
  done
  [ "$ok" -eq 1 ] || { echo "postgres never became ready" >&2; exit 1; }
fi

# --- 5. load Postgres dump ----------------------------------------------------
step "5/7" "load Postgres dump"
if [ "$DRY_RUN" -eq 0 ]; then
  set +e
  gzip -dc "$BUNDLE/postgres/vfic_pg_dump.sql.gz" \
    | ssh "${SSH_OPTS[@]}" "$HOST" "cd /opt/vfic && docker compose exec -T postgres psql -v ON_ERROR_STOP=0 -U vfic -d vfic" \
    > "$BUNDLE/.restore-psql.log" 2>&1
  RC=$?
  set -e
  tail -15 "$BUNDLE/.restore-psql.log" >&2 || true
  [ "$RC" -eq 0 ] || { echo "psql load failed (rc=$RC) — see $BUNDLE/.restore-psql.log" >&2; exit 1; }
  printf '  dump loaded.\n' >&2
fi

# --- 6. bring up the full stack ------------------------------------------------
step "6/7" "docker compose up -d (full stack)"
rmt "cd /opt/vfic && docker compose up -d"

# --- 7. verify + reminders ----------------------------------------------------
step "7/7" "verify"
if [ "$DRY_RUN" -eq 0 ]; then
  printf '  (waiting 8s for healthchecks...)\n' >&2; sleep 8
  ssh "${SSH_OPTS[@]}" "$HOST" "cd /opt/vfic && docker compose ps --format 'table {{.Name}}\t{{.Service}}\t{{.Status}}'" >&2 || true
fi

echo >&2
echo "DONE. Manual steps:" >&2
echo "  • DNS: point bot.tingting.vip A-record -> new droplet IP (if not already)." >&2
echo "  • Zalo webhook is domain-based — no change needed." >&2
echo "  • Health:  curl -sk https://bot.tingting.vip/health   (expect {\"status\":\"ok\"})" >&2
echo "  • Admin:   admin@vfic.vn  (password: VFIC_BOOTSTRAP_ADMIN_PASSWORD in $BUNDLE/env/opt-vfic.env)" >&2
