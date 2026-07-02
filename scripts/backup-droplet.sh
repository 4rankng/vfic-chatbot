#!/usr/bin/env bash
# =============================================================================
# backup-droplet.sh — full backup of the bot.tingting.vip droplet into a zip.
#
# Captures everything that is NOT in git and dies when the droplet is deleted:
#   - /opt/vfic/.env            (all prod secrets)
#   - PostgreSQL dump           (the database)
#   - vfic_kb_uploads volume    (uploaded KB originals)
#   - vfic_caddy_data/config    (Let's Encrypt TLS certs + ACME state)
#   - config snapshot           (docker-compose.yml, Caddyfile, prod-env.sh)
#   - manifests                 (git HEAD, running images, volume sizes)
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
ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
  "test -f /opt/vfic/.env && cd /opt/vfic && docker compose ps -q postgres >/dev/null" \
  || die "cannot reach droplet, /opt/vfic/.env missing, or stack down. Is the droplet still up?"

mkdir -p "$BUNDLE"/{env,postgres,kb_uploads,caddy,config-snapshot,manifests}

# --- 1. .env ------------------------------------------------------------------
log "fetching /opt/vfic/.env ..."
scp "${SCP_OPTS[@]}" "root@$PROD_SERVER:/opt/vfic/.env" "$BUNDLE/env/opt-vfic.env"
chmod 600 "$BUNDLE/env/opt-vfic.env"
[ -s "$BUNDLE/env/opt-vfic.env" ] || die "downloaded .env is empty."

# --- 2. Postgres dump (streamed over SSH, gzipped locally) --------------------
log "dumping PostgreSQL (streamed, gzipped locally — may take a minute) ..."
DUMP="$BUNDLE/postgres/vfic_pg_dump.sql.gz"
ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
  "cd /opt/vfic && docker compose exec -T postgres pg_dump -U vfic vfic" \
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
    "cd /opt/vfic && docker compose run -T --rm --no-deps --entrypoint /bin/sh $1 -c 'tar czf - -C $2 .'" \
    > "$3" || die "volume capture failed for $1:$2"
  tar tzf "$3" >/dev/null 2>&1 || die "tarball is corrupt: $3"
}
capture_volume caddy /data            "$BUNDLE/caddy/caddy_data.tar.gz"
capture_volume caddy /config          "$BUNDLE/caddy/caddy_config.tar.gz"
capture_volume web   /data/kb_uploads "$BUNDLE/kb_uploads/kb_uploads.tar.gz"

# --- 4. config snapshot (version-controlled deploy files, for self-containment) -
cp "$REPO_ROOT/backend/docker-compose.yml"  "$BUNDLE/config-snapshot/docker-compose.yml"
cp "$REPO_ROOT/backend/Caddyfile"           "$BUNDLE/config-snapshot/Caddyfile"
cp "$REPO_ROOT/backend/scripts/prod-env.sh" "$BUNDLE/config-snapshot/prod-env.sh"

# --- 5. manifests -------------------------------------------------------------
git -C "$REPO_ROOT" rev-parse HEAD > "$BUNDLE/manifests/git-head.txt"
ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" "cd /opt/vfic && docker compose images" \
  > "$BUNDLE/manifests/docker-images.txt" 2>&1 || true
ssh "${SSH_OPTS[@]}" "root@$PROD_SERVER" \
  "du -sh /var/lib/docker/volumes/vfic_* 2>/dev/null | sort -k2" \
  > "$BUNDLE/manifests/volume-sizes.txt" 2>&1 || true
cat > "$BUNDLE/manifests/backup-metadata.json" <<EOF
{
  "timestamp_utc_local": "$TS",
  "host": "$PROD_SERVER",
  "git_head": "$(git -C "$REPO_ROOT" rev-parse HEAD)",
  "postgres_dump": "postgres/vfic_pg_dump.sql.gz",
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
if [ -f "$REPO_ROOT/docs/DROPLET-BACKUP-RESTORE.md" ]; then
  cp "$REPO_ROOT/docs/DROPLET-BACKUP-RESTORE.md" "$BUNDLE/README-RESTORE.md"
else
  log "warn: docs/DROPLET-BACKUP-RESTORE.md missing — README-RESTORE.md omitted"
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
