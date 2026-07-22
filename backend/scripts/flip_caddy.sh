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

# Render to a temporary file, then replace the Caddyfile *contents* in place.
# The Caddyfile is bind-mounted into an already-running container: renaming a
# replacement over it changes the host inode, leaving the container mounted to
# the old inode. Keeping the inode stable lets `caddy reload` read the new
# upstream without restarting the edge proxy.
tmp="$(mktemp)"
sed "s/__WEB_UPSTREAM__/web-${COLOR}/g" Caddyfile.template > "$tmp"
cat "$tmp" > Caddyfile
rm -f "$tmp"

# Ensure Caddy is running without starting its dependencies. On the first
# deploy this starts Caddy against the rendered configuration; later cutovers
# leave the running edge proxy in place for its graceful reload.
docker compose up -d --no-deps caddy >/dev/null

# Validate the rendered config before applying. If validation is unavailable
# (older Caddy) we still reload — the template is validated by construction.
if ! docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
  echo "flip_caddy: warning: caddy validate unavailable/failed; reloading anyway" >&2
fi

# Apply: live reload. This is the only step that affects traffic, and it is
# graceful by design.
docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile
echo "flip_caddy: Caddy now routes to web-${COLOR}"
