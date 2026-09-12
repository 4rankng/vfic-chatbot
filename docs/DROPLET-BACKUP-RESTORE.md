# VFIC droplet backup & restore

Backup/restore for the production droplet **`bot.tingting.vip`** — for the
"delete the droplet now, spin it up again later" scenario.

The app code is in git (`git@github.com:4rankng/ChatBotN8N.git`, `main`) and the
Docker images (`ghcr.io/4rankng/tinghire-{be,fe}`) are on GHCR, so
**only stateful data + secrets** need to be bundled.

## What the bundle contains

| Path | What |
|---|---|
| `env/opt-vfic.env` | `/opt/vfic/.env` — **all prod secrets** (DB/Redis passwords, JWT secret, Zalo token + webhook secret, MiniMax/Gemini/OpenRouter/Resend keys, bootstrap admin password) |
| `postgres/vfic_pg_dump.sql.gz` | full `pg_dump` of the `vfic` database |
| `kb_uploads/kb_uploads.tar.gz` | uploaded KB originals (PDFs/docs) |
| `caddy/caddy_data.tar.gz` | Let's Encrypt TLS certs for `bot.tingting.vip` |
| `caddy/caddy_config.tar.gz` | Caddy ACME account state |
| `config-snapshot/` | `docker-compose.yml`, `Caddyfile`, `prod-env.sh` (copies of the version-controlled deploy files) |
| `manifests/` | git HEAD, running images, volume sizes, metadata |
| `restore.sh` / `README-RESTORE.md` | self-contained restore script + this doc |

**Redis is intentionally NOT backed up.** It holds the orphaned RQ job hashes
that caused the prod OOM; the scheduler cleanly re-registers its ticks on a
fresh start.

## Back up (before deleting the droplet)

From the repo root, on the Mac that has SSH access to the droplet:

```bash
make backup-full          # = bash scripts/backup-droplet.sh
```

Produces (under the gitignored `backups/` dir):

```
backups/vfic-droplet-backup-<YYYYMMDD-HHMMSS>/
backups/vfic-droplet-backup-<YYYYMMDD-HHMMSS>.zip
backups/vfic-droplet-backup-<YYYYMMDD-HHMMSS>.zip.sha256
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
make restore-prod BUNDLE=backups/vfic-droplet-backup-<TS>   # add DRY_RUN via the script:
bash scripts/restore-droplet.sh --bundle backups/vfic-droplet-backup-<TS> --dry-run

# do it for real
make restore-prod BUNDLE=backups/vfic-droplet-backup-<TS>
```

What `restore-droplet.sh` does, on the new droplet:

1. preflight: SSH ok, Docker+compose installed, ports 80/443 free
2. recreates `/opt/vfic/` with `docker-compose.yml`, `Caddyfile`, and the
   **restored** `.env` (mode 600) — does **not** run `prod-env.sh` (we want the
   saved secrets, not new randoms)
3. `docker compose pull` (re-pulls images from DockerHub)
4. seeds the Caddy TLS + KB uploads volumes from the tarballs (best-effort)
5. starts `postgres` + `redis`; the empty pgdata auto-inits the `vfic` db/user
   with the password from the restored `.env` (so the app's `DATABASE_URL` still
   matches)
6. loads the SQL dump via `psql`
7. `docker compose up -d` (full stack); skips `alembic upgrade head` and
   `create_admin` — the dump already has schema@head + admins

### After restore

- `curl -sk https://bot.tingting.vip/health` → expect `{"status":"ok"}`
- Log in at `https://bot.tingting.vip` as **`admin@vfic.vn`** (password:
  `VFIC_BOOTSTRAP_ADMIN_PASSWORD` in the bundle's `env/opt-vfic.env`)
- **Zalo webhook needs no change** — it is registered against the domain
  `https://bot.tingting.vip/webhooks/zalo/chatbot`, which follows the DNS.

## How it works / gotchas

- **Volume name double-prefix:** the compose project is `vfic` (from `/opt/vfic`)
  and the volume names in compose already start with `vfic_`, so the real Docker
  volumes are `vfic_vfic_*`. Both scripts sidestep this by using
  `docker compose run` (which maps volumes by service definition) instead of
  hardcoding names.
- **Postgres password consistency:** `pg_dump` doesn't carry the role password,
  but the restored `.env` sets the same `POSTGRES_PASSWORD` at first-init, so the
  password the app uses still matches the database.
- **Caddy certs:** restoring the cert volumes is best-effort. If it fails, Caddy
  re-issues automatically on first start (mind Let's Encrypt's 5-dup-cert/week
  rate limit).
- **Redis:** starts empty by design (see top of this doc).
