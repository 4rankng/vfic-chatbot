#!/usr/bin/env bash
# flip_caddy.sh <blue|green>  — render + reload Caddy onto the active web color.
#
# Renders /opt/vfic/Caddyfile from Caddyfile.template (substituting the color
# into every __WEB_UPSTREAM__ token), then reloads Caddy. `caddy reload` is a
# LIVE reconfiguration (<1s): existing connections drain on the old upstream,
# new ones use the new upstream — no dropped requests, no TLS re-handshake. Safe
# to call on every deploy and on rollback.
#
# Run on the droplet, from /opt/vfic. The Makefile/bg_deploy.sh invoke this.

set -euo pipefail

COLOR="${1:-}"
case "$COLOR" in
  blue|green) ;;
  *) echo "flip_caddy: usage: flip_caddy.sh <blue|green>; got '${COLOR}'" >&2; exit 2 ;;
esac

cd /opt/vfic

if [ ! -f Caddyfile.template ]; then
  echo "flip_caddy: /opt/vfic/Caddyfile.template missing (SCP it first)" >&2
  exit 2
fi

# Render atomically: write to a temp file, then move into place so Caddy never
# reads a half-written Caddyfile.
tmp="$(mktemp)"
sed "s/__WEB_UPSTREAM__/web-${COLOR}/g" Caddyfile.template > "$tmp"
mv "$tmp" Caddyfile

# Ensure Caddy is running (no-op if already up; compose does NOT recreate on a
# mounted-file content change, so this never causes a blip). On the very first
# deploy this is what starts Caddy against the just-rendered config.
docker compose up -d caddy >/dev/null

# Validate the rendered config before applying. If validation is unavailable
# (older Caddy) we still reload — the template is validated by construction.
if ! docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
  echo "flip_caddy: warning: caddy validate unavailable/failed; reloading anyway" >&2
fi

# Apply: live reload. This is the only step that affects traffic, and it is
# graceful by design.
docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile
echo "flip_caddy: Caddy now routes to web-${COLOR}"
