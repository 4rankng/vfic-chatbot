.PHONY: dev deploy deploy-backend deploy-frontend adminer seed backup restore backup-full restore-prod release-check

# Port shared by backend (uvicorn) and frontend (Vite) in local dev — both
# bind to the same number. Override on the CLI, e.g. `make dev PORT=9000`.
# The backend's `kill-port` target frees $(PORT) before binding so a stale
# process from a previous run can never block startup.
PORT ?= 5173

# Local dev: frontend (vite) + backend (uvicorn --reload) on host, Postgres +
# Redis + Adminer in docker. Delegates to backend/ (payroll pattern).
dev:
	@echo "=== Starting VFIC dev environment (port $(PORT)) ==="
	$(MAKE) -C backend dev PORT=$(PORT)

# Release must be committed and validated before any image is pushed or production is touched.
release-check:
	@test -z "$$(git status --porcelain)" || { echo "Release blocked: commit or stash all local changes first."; exit 1; }
	@git diff --check
	@cd backend && test "$$(.venv/bin/python -m alembic heads | wc -l | tr -d ' ')" = 1
	@cd backend && .venv/bin/ruff check . && .venv/bin/pytest
	@cd frontend && npm run lint && npm run typecheck && npm run test:unit:app -- --run && npm run build

# Build & push BOTH DockerHub images, then deploy to bot.tingting.vip.
deploy: release-check
	@echo "=== Building & pushing frontend ==="
	cd frontend && make push
	@echo "=== Building & pushing backend ==="
	cd backend && make push
	@echo "=== Deploying to production ==="
	$(MAKE) -C backend deploy
	@echo "=== Recreating production frontend ==="
	$(MAKE) -C backend deploy-restart-frontend

# Adminer over an SSH tunnel -> http://localhost:18081 (no public exposure).
# Ctrl-C closes the tunnel.
adminer:
	$(MAKE) -C backend adminer

# Fast-track: rebuild + push + rolling restart backend only (web + workers + scheduler).
# Skips frontend build and full-stack bootstrap (compose sync, migrations, etc.).
deploy-backend: release-check backup
	@echo "=== Deploying backend only ==="
	cd backend && make push
	$(MAKE) -C backend deploy-restart

# Fast-track: rebuild + push + rolling restart frontend only.
deploy-frontend: release-check
	@echo "=== Deploying frontend only ==="
	cd frontend && make push
	$(MAKE) -C backend deploy-restart-frontend

# Seed local dev database with realistic test data (truncate + re-insert).
# Requires: make db (Postgres running), alembic upgrade head already applied.
seed:
	@echo "=== Seeding local dev database ==="
	cd backend && .venv/bin/python -m scripts.seed_dev

# ─── Production DB backup / restore ────────────────────────────────────────────

PROD_SERVER := bot.tingting.vip
BACKUP_DIR  := $(HOME)/Library/CloudStorage/OneDrive-Personal/backup/vfic_db_backup

## backup: Dump production PostgreSQL DB → OneDrive (timestamped .sql.gz)
backup:
	@echo "=== Starting database backup from production ===" && \
	TIMESTAMP=$$(date +%Y-%m-%d_%H%M%S) && \
	BACKUP_FILE="vfic_pg_backup_$${TIMESTAMP}.sql" && \
	BACKUP_FILE_GZ="vfic_pg_backup_$${TIMESTAMP}.sql.gz" && \
	mkdir -p "$(BACKUP_DIR)" && \
	echo "Dumping PostgreSQL (vfic@vfic-postgres-1)..." && \
	ssh root@$(PROD_SERVER) \
		"docker exec vfic-postgres-1 pg_dump -U vfic vfic > /tmp/$${BACKUP_FILE}" && \
	echo "Compressing..." && \
	ssh root@$(PROD_SERVER) "gzip /tmp/$${BACKUP_FILE}" && \
	ssh root@$(PROD_SERVER) \
		"if [ ! -s /tmp/$${BACKUP_FILE_GZ} ]; then echo 'ERROR: Backup file is empty!'; exit 1; fi" && \
	echo "Downloading to local machine..." && \
	scp root@$(PROD_SERVER):/tmp/$${BACKUP_FILE_GZ} "$(BACKUP_DIR)/$${BACKUP_FILE_GZ}" && \
	ssh root@$(PROD_SERVER) "rm -f /tmp/$${BACKUP_FILE_GZ}" && \
	echo "Backup complete!" && \
	echo "  Saved to: $(BACKUP_DIR)/$${BACKUP_FILE_GZ}" && \
	echo "  Size: $$(du -h "$(BACKUP_DIR)/$${BACKUP_FILE_GZ}" | cut -f1)"

## restore: Restore latest backup from OneDrive to local dev DB
restore:
	@echo "=== Starting DB restore ===" && \
	echo "Ensuring local Postgres is running..." && \
	cd backend && docker compose -f docker-compose.dev.yml up -d --wait postgres 2>/dev/null || \
		docker compose -f docker-compose.dev.yml up -d postgres && \
	echo "Waiting for Postgres to be ready..." && \
	until docker exec backend-postgres-1 pg_isready -U vfic >/dev/null 2>&1; do sleep 1; done && \
	LATEST=$$(ls -t "$(BACKUP_DIR)"/vfic_pg_backup_*.sql.gz 2>/dev/null | head -1) && \
	if [ -z "$$LATEST" ]; then echo "ERROR: No backup files found in $(BACKUP_DIR)"; exit 1; fi && \
	echo "Using backup: $$LATEST" && \
	echo "Size: $$(du -h "$$LATEST" | cut -f1)" && \
	echo "Decompressing..." && \
	gunzip -k -f "$$LATEST" && \
	SQL_FILE="$${LATEST%.gz}" && \
	echo "Terminating active connections and recreating database..." && \
	docker exec backend-postgres-1 psql -U vfic -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'vfic' AND pid <> pg_backend_pid();" && \
	docker exec backend-postgres-1 psql -U vfic -d postgres -c "DROP DATABASE IF EXISTS vfic;" && \
	docker exec backend-postgres-1 psql -U vfic -d postgres -c "CREATE DATABASE vfic;" && \
	echo "Restoring backup into local database..." && \
	docker exec -i backend-postgres-1 psql -U vfic -d vfic < "$$SQL_FILE" && \
	rm -f "$$SQL_FILE" && \
	echo "Running Alembic stamp (mark DB as at head)..." && \
	.venv/bin/python -m alembic stamp head 2>/dev/null || true && \
	echo "Resetting all user passwords to admin123..." && \
	.venv/bin/python -m scripts.reset_passwords --password admin123 && \
	echo "Creating admin user if missing..." && \
	( .venv/bin/python -m scripts.create_admin --only-if-no-admins --email admin@vfic.dev --password admin123 --full-name "Dev Admin" --role admin 2>/dev/null || true ) && \
	echo "Restore complete!" && \
	echo "  All users reset to password: admin123"

# ─── Full droplet backup / restore (delete + spin up later) ────────────────────
# docs/DROPLET-BACKUP-RESTORE.md has the full runbook. Redis is intentionally
# not backed up (scheduler re-registers its ticks; avoids the orphaned-job OOM).
BACKUPS_DIR := $(CURDIR)/backups

## backup-full: bundle /opt/vfic/.env + DB dump + KB uploads + Caddy TLS → backups/<ts>.zip
backup-full:
	@mkdir -p "$(BACKUPS_DIR)"
	bash scripts/backup-droplet.sh

## restore-prod: push a bundle onto a FRESH droplet (SSH, mirrors `deploy`).
## Usage: make restore-prod BUNDLE=backups/vfic-droplet-backup-<TS> [HOST=root@bot.tingting.vip]
restore-prod:
	@test -n "$(BUNDLE)" || { echo "Usage: make restore-prod BUNDLE=backups/vfic-droplet-backup-<TS> [HOST=root@bot.tingting.vip]"; exit 2; }
	bash scripts/restore-droplet.sh --bundle "$(BUNDLE)" --host "$(or $(HOST),root@bot.tingting.vip)"
