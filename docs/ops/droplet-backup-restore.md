# VFIC droplet backup & restore

Backup/restore for the production droplet **`bot.tingting.vip`** — for the
"delete the droplet now, spin it up again later" scenario.

The app code is in git (`git@github.com:4rankng/vfic-chatbot.git`, `main`) and
the Docker images (`ghcr.io/4rankng/tinghire-{be,fe}`) are on GHCR, so
**only stateful data + secrets** need to be bundled.

## What the bundle contains

`bash scripts/backup-droplet.sh` captures:

| Path | What |
|---|---|
| `env/opt-vfic.env` | `/opt/vfic/.env` (mode 600) — **all prod secrets**: DB/Redis passwords, JWT secret, `INTEGRATION_SETTINGS_ENCRYPTION_KEY` (or the `JWT_SECRET` legacy fallback), Zalo token, LLM/Resend keys, `VFIC_BOOTSTRAP_ADMIN_PASSWORD` |
| `postgres/vfic_pg_dump.sql.gz` | full `pg_dump` of the `vfic` database, streamed over SSH and gzipped locally; integrity-checked (`gunzip -t` + dump-header check) before the backup continues |
| `kb_uploads/kb_uploads.tar.gz` | uploaded KB originals (PDFs/docs), captured through the `worker-ingest` service — there is no plain `web` service to use |
| `caddy/caddy_data.tar.gz` | Let's Encrypt TLS certs for `bot.tingting.vip` |
| `caddy/caddy_config.tar.gz` | Caddy ACME account state |
| `config-snapshot/docker-compose.yml` | the shipped compose file |
| `config-snapshot/Caddyfile.template` | the tracked edge template |
| `config-snapshot/Caddyfile` | the **rendered** `/opt/vfic/Caddyfile` captured live — it carries the active colour; refused if it still contains `__WEB_UPSTREAM__` or names no `web-<colour>` upstream |
| `config-snapshot/prod-env.sh` | the env generator, for self-containment |
| `manifests/` | `git-head.txt`, `docker-images.txt`, `volume-sizes.txt`, `active-color.txt`, `image-tag.txt` (the tag the active colour is *running*), `alembic-version.txt` (the dump's schema revision, when readable), `backup-metadata.json` |
| `restore.sh` / `README-RESTORE.md` | self-contained restore script + this doc |

Output: `backups/vfic-droplet-backup-<YYYYMMDD-HHMMSS>/` plus `.zip` and
`.zip.sha256` under the gitignored `backups/` dir.

**Redis is intentionally NOT backed up.** It holds the orphaned RQ job hashes
that caused the prod OOM; the scheduler cleanly re-registers its ticks on a
fresh start.

### Refusal gates (the script aborts rather than ship a bad bundle)

Droplet unreachable or `/opt/vfic/.env` missing · downloaded `.env` empty ·
`.env` carries neither `INTEGRATION_SETTINGS_ENCRYPTION_KEY` nor `JWT_SECRET`
(a bundle whose rows would be undecryptable) — with a `JWT_SECRET`-only
fallback warned · corrupt gzip / wrong `pg_dump` header · corrupt volume
tarball · missing config-snapshot source · rendered Caddyfile missing, empty,
still templated, or colour-less.

## Back up (before deleting the droplet)

From the repo root, on the Mac that has SSH access to the droplet:

```bash
make backup-full          # = bash scripts/backup-droplet.sh
```

> `backups/` is **local-only and gitignored** — it is not in OneDrive. If this
> Mac is the only copy, drag the `.zip` (and `.sha256`) to external/cloud
> storage yourself for redundancy.

## Restore (on a fresh droplet)

### Prerequisites (one-time, on the new droplet)

1. **Create a fresh Ubuntu droplet** (DigitalOcean or any provider). 2 vCPU / 4 GB
   matches the old box.
2. **Point DNS**: `bot.tingting.vip` A-record → new droplet public IP. Wait for
   DNS to propagate (`dig +short bot.tingting.vip`).
3. **SSH access**: ensure `ssh root@bot.tingting.vip` works from this Mac (add
   your key via the provider console / `ssh-copy-id`).
4. **Install Docker** on the droplet (the restore script checks for it and aborts
   with this command if missing):
   ```bash
   ssh root@bot.tingting.vip 'curl -fsSL https://get.docker.com | sh'
   ```

### Run the restore

```bash
# unzip the bundle (if you only have the .zip)
unzip backups/vfic-droplet-backup-<TS>.zip -d backups/

# preview first (no changes made)
bash scripts/restore-droplet.sh --bundle backups/vfic-droplet-backup-<TS> --dry-run

# do it for real (HOST defaults to root@bot.tingting.vip)
make restore-prod BUNDLE=backups/vfic-droplet-backup-<TS>
```

`--tag <git-sha>` overrides the pinned tag; without it the tag comes from the
bundle. Pre-run checks: the bundle must contain `env/opt-vfic.env`,
`postgres/vfic_pg_dump.sql.gz`, `config-snapshot/docker-compose.yml`, and an
edge config (the rendered `Caddyfile`, or `Caddyfile.template` to render here);
the active colour is read from `manifests/active-color.txt` (validated
`blue|green`); the bundle `.env` must carry a sealing key (same gates as
backup).

### What `restore-droplet.sh` does, on the new droplet

1. **Preflight**: SSH ok, Docker + compose plugin installed, ports 80/443 free
   (warns — with the n8n teardown hint — if something already listens).
2. **Recreates `/opt/vfic/`**: `docker-compose.yml`, the `Caddyfile.template`
   (when the bundle carries one), and the **rendered** `Caddyfile` the bundle
   captured — a template-only bundle is rendered on the Mac with the same
   `__WEB_UPSTREAM__` substitution `flip_caddy.sh` performs, using the recorded
   colour. Restores `.env` (mode 600) and writes `ACTIVE_COLOR` /
   `PREV_COLOR` / `PREV_TAG` (the other colour + the same tag become the
   trivial rollback target). Does **not** run `prod-env.sh` — we want the saved
   secrets, not new randoms.
3. **`docker compose pull` at the tag recorded in the bundle** — precedence:
   `--tag`, then `manifests/image-tag.txt`, then the `tinghire-be` tag parsed
   from `manifests/docker-images.txt`. If none resolves, or it is `latest`, the
   restore **fails closed**: `latest` is re-pushed on every deploy, i.e. new
   code against the dumped schema.
4. **Seeds** the Caddy TLS + config volumes and KB uploads from the tarballs
   (best-effort; Caddy re-issues certs if the seed fails).
5. **Starts `postgres` + `redis`** (fresh volumes); the empty pgdata auto-inits
   the `vfic` db/user with the password from the restored `.env` (so the app's
   `DATABASE_URL` still matches).
6. **Loads the SQL dump** via `psql` (output kept at
   `<bundle>/.restore-psql.log`; a failed load aborts).
7. **Migrates + asserts schema compatibility**: `widen_alembic_version`, then
   `alembic upgrade head` (a no-op at head, forward-migrates when the image is
   slightly newer), then asserts the restored `alembic_version` equals the
   pinned image's head — a dump the image doesn't know aborts before the stack
   boots. Skips `create_admin` — the dump already has admins.
8. **Brings up the full stack** and **verifies**: the running web container's
   tag equals the pinned tag, `web-<colour> /health` returns 200, and every
   sealed `integration_settings` row decrypts (`verify_integration_secrets.py`
   is piped over stdin into the pinned image, so images predating the script
   are covered; it prints counts and row keys, never secrets).

Manual steps after the script returns:

- **DNS**: point the `bot.tingting.vip` A-record → new droplet IP (if not
  already done in the prerequisites).
- **Zalo webhook needs no change** — it is registered against the domain
  `https://bot.tingting.vip/webhooks/zalo/chatbot`, which follows the DNS.
- **Health**: `curl -sk https://bot.tingting.vip/health` → expect
  `{"status":"ok"}`.
- **Log in** at `https://bot.tingting.vip` as **`admin@vfic.vn`** (password:
  `VFIC_BOOTSTRAP_ADMIN_PASSWORD` in the bundle's `env/opt-vfic.env`).

## The sealing key is DR-critical

Every `integration_settings` row is AES-GCM-sealed under a key derived from
`INTEGRATION_SETTINGS_ENCRYPTION_KEY` (`JWT_SECRET` is only the legacy/dev
fallback). A dump restored without the matching key yields rows that raise
`InvalidTag`, get skipped with a warning, and fall back to env values — the
stack looks healthy while the stored credentials are gone. Both scripts gate on
key presence, the restore verifies sealed rows actually decrypt, and a value
sealed under the fallback reopens only under that same secret (rotating
`JWT_SECRET` re-breaks every sealed row). Store the key in a password manager
separate from the droplet and the backup files, and never rotate it without
re-sealing stored credentials.

## How it works / gotchas

- **`IMAGE_TAG` is required by every prod compose command** — `${IMAGE_TAG:?}`
  interpolates the whole file even for `ps`/`exec`/`run`, and `compose run`
  *pulls* an interpolated tag that isn't already on the droplet. The backup
  therefore resolves the tag the active colour is actually running (plain
  `docker inspect`, falling back to `PREV_TAG`), never asking compose for a tag
  that would trigger a pull.
- **Volume name double-prefix:** the compose project is `vfic` (from
  `/opt/vfic`) and the volume names in compose already start with `vfic_`, so
  the real Docker volumes are `vfic_vfic_*`. Both scripts sidestep this by
  using `docker compose run --no-deps` (which maps volumes by service
  definition) instead of hardcoding names.
- **Postgres password consistency:** `pg_dump` doesn't carry the role password,
  but the restored `.env` sets the same `POSTGRES_PASSWORD` at first-init, so
  the password the app uses still matches the database.
- **Caddy certs:** restoring the cert volumes is best-effort. If it fails, Caddy
  re-issues automatically on first start (mind Let's Encrypt's 5-dup-cert/week
  rate limit).
- **Redis:** starts empty by design (see top of this doc).
