#!/usr/bin/env bash
# =============================================================================
# backup-droplet.sh — full backup of the bot.tingting.vip droplet into a zip.
#
# Captures everything that is NOT in git and dies when the droplet is deleted:
#   - /opt/vfic/.env            (all prod secrets, incl. the integration key)
#   - PostgreSQL dump           (the database)
#   - vfic_kb_uploads volume    (uploaded KB originals)
#   - vfic_caddy_data/config    (Let's Encrypt TLS certs + ACME state)
#   - config snapshot           (docker-compose.yml, Caddyfile.template,
#                                prod-env.sh, and the RENDERED /opt/vfic/Caddyfile)
#   - manifests                 (git HEAD, active colour, image tag, alembic
#                                revision, running images, volume sizes)
#
# Redis is intentionally NOT backed up: it holds the orphaned RQ job hashes
# that caused the prod OOM, and the scheduler re-registers its ticks on boot.
#
# Output: backups/vfic-droplet-backup-<TS>/  +  .zip  +  .zip.sha256
# Run from anywhere; resolves the repo root from this script's location.
# =============================================================================
set -euo pipefail

PROD_SERVER="${PROD_SERVER:-bot.tingting.vip}"
SSH_OPTS=(-o ConnectTimeout=15 -o ServerAliveInterval=30)
SCP_OPTS=(-q -o ConnectTimeout=15)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUPS_DIR="$REPO_ROOT/backups"
TS="$(date +%Y%m%d-%H%M%S)"
BUNDLE_NAME="vfic-droplet-backup-$TS"
BUNDLE="$BACKUPS_DIR/$BUNDLE_NAME"

log()  { printf '\033[1;34m[backup]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[backup error]\033[0m %s\n' "$*" >&2; exit 1; }

command -v zip    >/dev/null || die "zip not found."
command -v scp    >/dev/null || die "scp not found."
[ -d "$REPO_ROOT/.git" ]     || die "repo root not found at $REPO_ROOT — run from the repo."

# --- preflight ----------------------------------------------------------------
log "connecting to root@$PROD_SERVER ..."
ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" "test -f /opt/vfic/.env" \
  || die "cannot reach droplet or /opt/vfic/.env is missing. Is the droplet still up?"

# The prod compose file requires IMAGE_TAG for EVERY subcommand — `${IMAGE_TAG:?}`
# interpolates the whole file even for `ps`/`exec`/`run`, none of which use the
# app images — and `compose run` PULLS whatever tag it interpolates if that tag
# is not already on the droplet. So resolve the tag the active colour ACTUALLY
# runs (plain docker — no compose call, so no interpolation chicken-and-egg),
# falling back to PREV_TAG, then `unknown` (a placeholder that only satisfies
# interpolation for read-only ps/exec).
ACTIVE_COLOR_SNAPSHOT="$(ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
  "cat /opt/vfic/ACTIVE_COLOR 2>/dev/null || echo blue" | tr -d '[:space:]' || true)"
case "$ACTIVE_COLOR_SNAPSHOT" in
  blue|green) ;;
  *) die "unexpected /opt/vfic/ACTIVE_COLOR value '$ACTIVE_COLOR_SNAPSHOT' (expected blue|green)." ;;
esac

COMPOSE_TAG="$(ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
  "cid=\$(docker ps -q --filter name=web-$ACTIVE_COLOR_SNAPSHOT | head -1); \
   [ -n \"\$cid\" ] && docker inspect --format '{{.Config.Image}}' \"\$cid\" | sed 's/.*://'" \
  | tr -d '[:space:]' || true)"
if [ -z "$COMPOSE_TAG" ]; then
  COMPOSE_TAG="$(ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
    "cat /opt/vfic/PREV_TAG 2>/dev/null" | tr -d '[:space:]' || true)"
fi
[ -n "$COMPOSE_TAG" ] || COMPOSE_TAG=unknown

ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
  "cd /opt/vfic && IMAGE_TAG=$COMPOSE_TAG docker compose ps -q postgres >/dev/null" \
  || die "cannot reach droplet, /opt/vfic/.env missing, or stack down. Is the droplet still up?"

mkdir -p "$BUNDLE"/{env,postgres,kb_uploads,caddy,config-snapshot,manifests}

# --- 1. .env ------------------------------------------------------------------
log "fetching /opt/vfic/.env ..."
scp "${SCP_OPTS[@]}" "root@$PROD_SERVER:/opt/vfic/.env" "$BUNDLE/env/opt-vfic.env"
chmod 600 "$BUNDLE/env/opt-vfic.env"
[ -s "$BUNDLE/env/opt-vfic.env" ] || die "downloaded .env is empty."

# Every integration_settings row is sealed with AES-GCM under a key derived from
# INTEGRATION_SETTINGS_ENCRYPTION_KEY (JWT_SECRET is only the legacy/dev
# fallback). Without that key the restored rows raise InvalidTag, the service
# skips them with a warning and callers silently fall back to env values — so a
# bundle missing it restores a database of undecryptable credentials. Refuse to
# produce one instead.
env_value() { sed -n "s/^$1=//p" "$BUNDLE/env/opt-vfic.env" | tail -1; }
if [ -z "$(env_value INTEGRATION_SETTINGS_ENCRYPTION_KEY)" ]; then
  [ -n "$(env_value JWT_SECRET)" ] \
    || die "restored .env carries neither INTEGRATION_SETTINGS_ENCRYPTION_KEY nor JWT_SECRET — every stored integration credential would be undecryptable."
  log "warn: no INTEGRATION_SETTINGS_ENCRYPTION_KEY in .env; the JWT_SECRET fallback seals the rows, so rotating JWT_SECRET re-breaks them."
fi

# --- 2. Postgres dump (streamed over SSH, gzipped locally) --------------------
log "dumping PostgreSQL (streamed, gzipped locally — may take a minute) ..."
DUMP="$BUNDLE/postgres/vfic_pg_dump.sql.gz"
ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
  "cd /opt/vfic && IMAGE_TAG=$COMPOSE_TAG docker compose exec -T postgres pg_dump -U vfic vfic" \
  | gzip -c > "$DUMP"
gunzip -t "$DUMP" || die "pg_dump gzip is corrupt."
gzip -dc "$DUMP" | sed -n '1,3p' | grep -q 'PostgreSQL database dump' \
  || die "dump does not start with the expected pg_dump header — refusing to ship a bad backup."
log "  dump ok ($(du -h "$DUMP" | cut -f1))."

# --- 3. volume tarballs (docker compose run => correct mapping, no name hacks) -
# Captures run as one-off containers mounting the SAME volumes as the live
# services, so we never hardcode the (double-prefixed) vfic_vfic_* volume names.
capture_volume() {  # $1 = service  $2 = in-container mount path  $3 = outfile
  log "capturing volume: $1 → $2"
  ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
    "cd /opt/vfic && IMAGE_TAG=$COMPOSE_TAG docker compose run -T --rm --no-deps --entrypoint /bin/sh $1 -c 'tar czf - -C $2 .'" \
    > "$3" || die "volume capture failed for $1:$2"
  tar tzf "$3" >/dev/null 2>&1 || die "tarball is corrupt: $3"
}
capture_volume caddy /data            "$BUNDLE/caddy/caddy_data.tar.gz"
capture_volume caddy /config          "$BUNDLE/caddy/caddy_config.tar.gz"
# There is no plain `web` service — only web-blue/web-green. worker-ingest
# mounts vfic_kb_uploads and exists regardless of the active colour, so the
# capture cannot depend on which colour happens to serve.
capture_volume worker-ingest /data/kb_uploads "$BUNDLE/kb_uploads/kb_uploads.tar.gz"

# --- 4. config snapshot (the deploy files, for self-containment) --------------
# The edge config is RENDERED on the droplet: `backend/Caddyfile.template` is the
# tracked source and `scripts/flip_caddy.sh` substitutes __WEB_UPSTREAM__ into
# `/opt/vfic/Caddyfile` at cutover. Snapshot BOTH — the live rendered Caddyfile
# (it is the real edge config and carries the active colour) and the template
# (so the droplet can re-render later) — and refuse to ship a partial snapshot.
snapshot_file() {  # $1 = source path  $2 = bundle destination
  [ -f "$1" ] || die "config snapshot source missing: $1 — refusing a partial bundle."
  cp "$1" "$2"
}
snapshot_file "$REPO_ROOT/backend/docker-compose.yml"  "$BUNDLE/config-snapshot/docker-compose.yml"
snapshot_file "$REPO_ROOT/backend/Caddyfile.template"  "$BUNDLE/config-snapshot/Caddyfile.template"
snapshot_file "$REPO_ROOT/backend/scripts/prod-env.sh" "$BUNDLE/config-snapshot/prod-env.sh"

log "fetching the rendered /opt/vfic/Caddyfile ..."
scp "${SCP_OPTS[@]}" "root@$PROD_SERVER:/opt/vfic/Caddyfile" "$BUNDLE/config-snapshot/Caddyfile" \
  || die "cannot fetch /opt/vfic/Caddyfile — has the droplet ever been deployed?"
[ -s "$BUNDLE/config-snapshot/Caddyfile" ] || die "fetched /opt/vfic/Caddyfile is empty."
if grep -q '__WEB_UPSTREAM__' "$BUNDLE/config-snapshot/Caddyfile"; then
  die "rendered /opt/vfic/Caddyfile still contains __WEB_UPSTREAM__ (never flipped) — refusing a broken edge config."
fi
grep -qE 'web-(blue|green)' "$BUNDLE/config-snapshot/Caddyfile" \
  || die "rendered /opt/vfic/Caddyfile names no web-<colour> upstream — refusing an unusable edge config."

# --- 5. manifests -------------------------------------------------------------
git -C "$REPO_ROOT" rev-parse HEAD > "$BUNDLE/manifests/git-head.txt"
ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
  "cd /opt/vfic && IMAGE_TAG=$COMPOSE_TAG docker compose images" \
  > "$BUNDLE/manifests/docker-images.txt" 2>&1 || true
ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
  "du -sh /var/lib/docker/volumes/vfic_* 2>/dev/null | sort -k2" \
  > "$BUNDLE/manifests/volume-sizes.txt" 2>&1 || true

# Which colour Caddy routes to, and the tag that colour is RUNNING (both resolved
# in preflight). Restore pins IMAGE_TAG to this tag: a bare `docker compose up`
# resolves `${IMAGE_TAG:-latest}`, and `latest` is re-pushed on every deploy —
# i.e. new code against the dumped schema.
printf '%s\n' "$ACTIVE_COLOR_SNAPSHOT" > "$BUNDLE/manifests/active-color.txt"
if [ "$COMPOSE_TAG" != "unknown" ]; then
  printf '%s\n' "$COMPOSE_TAG" > "$BUNDLE/manifests/image-tag.txt"
  log "  active colour: $ACTIVE_COLOR_SNAPSHOT   running image tag: $COMPOSE_TAG"
else
  log "warn: could not read web-$ACTIVE_COLOR_SNAPSHOT's running image tag; restore will fall back to parsing manifests/docker-images.txt."
fi

# The revision the dump's schema sits at. Restore asserts the restored DB reaches
# the pinned image's head before it declares success.
ALEMBIC_REV_SNAPSHOT="$(ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
  "cd /opt/vfic && IMAGE_TAG=$COMPOSE_TAG docker compose exec -T postgres psql -U vfic -d vfic -tAc \"select version_num from alembic_version\" | tr -d '[:space:]'" \
  2>/dev/null || true)"
if [ -n "$ALEMBIC_REV_SNAPSHOT" ]; then
  printf '%s\n' "$ALEMBIC_REV_SNAPSHOT" > "$BUNDLE/manifests/alembic-version.txt"
else
  log "warn: could not read the droplet's alembic_version; restore will read it from the restored dump."
fi

cat > "$BUNDLE/manifests/backup-metadata.json" <<EOF
{
  "timestamp_utc_local": "$TS",
  "host": "$PROD_SERVER",
  "git_head": "$(git -C "$REPO_ROOT" rev-parse HEAD)",
  "postgres_dump": "postgres/vfic_pg_dump.sql.gz",
  "active_color": "$ACTIVE_COLOR_SNAPSHOT",
  "image_tag": "$COMPOSE_TAG",
  "alembic_revision": "$ALEMBIC_REV_SNAPSHOT",
  "integration_settings_key_present": $([ -n "$(env_value INTEGRATION_SETTINGS_ENCRYPTION_KEY)" ] && echo true || echo false),
  "volumes_captured": ["vfic_kb_uploads", "vfic_caddy_data", "vfic_caddy_config"],
  "volumes_skipped": ["vfic_pgdata (restored via pg_dump)", "vfic_redisdata (restored fresh)"],
  "sha256": "see companion .zip.sha256 file"
}
EOF

# --- 6. embed restore script + runbook so the bundle is self-contained --------
if [ -f "$REPO_ROOT/scripts/restore-droplet.sh" ]; then
  cp "$REPO_ROOT/scripts/restore-droplet.sh" "$BUNDLE/restore.sh"
else
  log "warn: scripts/restore-droplet.sh missing — bundle restore.sh omitted"
fi
if [ -f "$REPO_ROOT/docs/ops/droplet-backup-restore.md" ]; then
  cp "$REPO_ROOT/docs/ops/droplet-backup-restore.md" "$BUNDLE/README-RESTORE.md"
else
  log "warn: docs/ops/droplet-backup-restore.md missing — README-RESTORE.md omitted"
fi

# --- 7. zip + checksum --------------------------------------------------------
( cd "$BACKUPS_DIR" && zip -qr "$BUNDLE_NAME.zip" "$BUNDLE_NAME" )
ZIP="$BACKUPS_DIR/$BUNDLE_NAME.zip"
SHASUM="$(shasum -a 256 "$ZIP" | awk '{print $1}')"
printf '%s  %s\n' "$SHASUM" "$BUNDLE_NAME.zip" > "$ZIP.sha256"

# --- report -------------------------------------------------------------------
log "backup complete."
echo >&2
printf '  bundle dir : %s\n' "$BUNDLE"            >&2
printf '  zip        : %s\n' "$ZIP"               >&2
printf '  zip size   : %s\n' "$(du -h "$ZIP" | cut -f1)"   >&2
printf '  sha256     : %s\n' "$SHASUM"            >&2
printf '  files      : %s\n' "$(find "$BUNDLE" -type f | wc -l | tr -d ' ')" >&2
echo >&2
log "backups/ is gitignored and LOCAL ONLY. Copy the .zip (+.sha256) to external/cloud storage for redundancy."
