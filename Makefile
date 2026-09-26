.PHONY: dev bootstrap deploy deploy-backend deploy-frontend adminer seed backup restore backup-full restore-prod release-check openwiki

# Ports are owned by backend/Makefile (BACKEND_PORT / FRONTEND_PORT /
# ZALO_MOCK_PORT). This file only forwards the frontend one, so
# `make dev PORT=9000` keeps working: backend/Makefile never read `PORT`, which
# is why the old plumbing was dead (OPS-19). Forward all three to override:
#   make dev BACKEND_PORT=9001 FRONTEND_PORT=9001 ZALO_MOCK_PORT=8799
FRONTEND_PORT ?= 5173
PORT ?= $(FRONTEND_PORT)

# Local dev: frontend (vite) + backend (uvicorn --reload) on host, Postgres +
# Redis + Adminer in docker. Delegates to backend/ (payroll pattern).
dev: bootstrap
	@echo "=== Starting VFIC dev environment (frontend :$(PORT)) ==="
	$(MAKE) -C backend dev FRONTEND_PORT=$(PORT)

## bootstrap: one-command first run — .env, backend/.venv (Python 3.12 per
## backend/.python-version) and frontend/node_modules. The venv/npm installs are
## `test -d`-guarded; repeat runs only re-sync the editable install, which is
## idempotent and picks up dependency changes (OPS-18).
bootstrap:
	@test -f backend/.env || { echo "backend/.env: created from .env.example — set real secrets before any deploy"; cp backend/.env.example backend/.env; }
	@if ! command -v python3.12 >/dev/null 2>&1; then \
		echo "WARNING: python3.12 not found — falling back to $$(command -v python3)."; \
		echo "         Production and CI run 3.12; install it (pyenv/mise) to match (OPS-13)."; \
	fi
	@test -d backend/.venv || { echo "Creating backend/.venv ..."; python3.12 -m venv backend/.venv 2>/dev/null || python3 -m venv backend/.venv; }
	@backend/.venv/bin/python -m pip install --quiet --upgrade pip
	@backend/.venv/bin/python -m pip install --quiet -e "backend/[dev]"
	@test -d frontend/node_modules || { echo "Installing frontend deps (npm ci) ..."; cd frontend && npm ci; }
	@echo "bootstrap complete — run 'make dev'"

# Release must be committed and validated before any image is pushed or production is touched.
# Every gate runs on this machine — there is no CI in the loop.
release-check:
	@test -z "$$(git status --porcelain)" || { echo "Release blocked: commit or stash all local changes first."; exit 1; }
	@git diff --check
	@if command -v uv >/dev/null 2>&1; then (cd backend && uv lock --check); else echo "WARNING: uv not found — skipped uv lock --check"; fi
	@cd backend && test "$$(.venv/bin/python -m alembic heads | wc -l | tr -d ' ')" = 1
	@cd backend && HEAD_REV="$$(.venv/bin/python -m alembic heads | awk 'NR==1{print $$1}')" && \
		grep -qF "**HEAD:** \`$$HEAD_REV" ../docs/deployment-guide.md || { \
			echo "Release blocked: docs/deployment-guide.md's Alembic HEAD no longer matches alembic heads ($$HEAD_REV) — update section 4 (Alembic migration run)."; exit 1; }
	@docker compose -f backend/docker-compose.dev.yml up -d --wait postgres redis
	@cd backend && .venv/bin/ruff check . && .venv/bin/pytest -m "not integration" && .venv/bin/pytest -m integration tests/integration/test_harness_smoke.py && .venv/bin/pytest -m integration --durations=25
	@cd frontend && npm run lint && npm run typecheck && npm run test:unit:app -- --run && npm run test:unit:app:coverage:changed-surface -- --run && npm run build && npm run test:e2e:desktop && npm run test:e2e:mobile
	@tmp_raw="$$(mktemp -t release-gate-raw.XXXXXX.json)"; \
		tmp_gold="$$(mktemp -t release-gate-golden.XXXXXX.json)"; \
		(cd backend && .venv/bin/python scripts/benchmark_rag.py --gold --min-pass-rate 0 --output "$$tmp_raw"); \
		(cd backend && .venv/bin/python -c 'import json, sys; from pathlib import Path; raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); passed = raw.get("passed"); case_count = raw.get("case_count"); \
assert isinstance(passed, int) and not isinstance(passed, bool), "benchmark artifact missing integer passed"; \
assert isinstance(case_count, int) and not isinstance(case_count, bool) and case_count > 0, "benchmark artifact missing positive integer case_count"; \
assert 0 <= passed <= case_count, "benchmark artifact has invalid passed/case_count values"; \
Path(sys.argv[2]).write_text(json.dumps({"golden_pass_rate_pct": passed / case_count * 100.0}), encoding="utf-8")' "$$tmp_raw" "$$tmp_gold"); \
		(cd backend && .venv/bin/python scripts/release_gate_check.py --golden-results "$$tmp_gold"); \
		rc=$$?; \
		rm -f "$$tmp_raw" "$$tmp_gold"; \
		exit "$$rc"

# Build & push BOTH GHCR images, then deploy to bot.tingting.vip.
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
## openwiki: refresh the generated OpenWiki evidence index (run at the end of a task).
## Reads OPENROUTER_API_KEY from the environment, falling back to backend/.env.
openwiki:
	@set -eu; \
		key="$${OPENROUTER_API_KEY:-}"; \
		if [ -z "$$key" ] && [ -f backend/.env ]; then \
			key="$$(sed -n 's/^OPENROUTER_API_KEY=//p' backend/.env | tail -1)"; \
		fi; \
		command -v openwiki >/dev/null 2>&1 || { \
			echo "OpenWiki blocked: 'openwiki' CLI not found — npm install -g openwiki@0.5.0 mermaid@11.16.0 jsdom@29.1.1"; exit 1; }; \
		test -n "$$key" || { \
			echo "OpenWiki blocked: no OpenRouter key. Export OPENROUTER_API_KEY or fill it in backend/.env."; exit 1; }; \
		OPENWIKI_PROVIDER=openrouter OPENWIKI_MODEL_ID="z-ai/glm-5.2" OPENROUTER_API_KEY="$$key" \
			openwiki code --update --print; \
		rm -f -- openwiki/.run.json

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

## backup: pg_dump the prod DB (custom format) and pull /opt/vfic/.env with it.
## The .env carries INTEGRATION_SETTINGS_ENCRYPTION_KEY: without it the dump
## alone cannot be decrypted by a restore (OPS-03). Keeps the newest $(BACKUP_KEEP)
## dumps; each vfic_env_*.env lives exactly as long as its dump pair (an env copy
## holds prod secrets, so an orphan whose dump was pruned is deleted, not kept).
BACKUP_KEEP := 10
backup:
	@echo "=== Starting database backup from production ===" && \
	TIMESTAMP=$$(date +%Y-%m-%d_%H%M%S) && \
	BACKUP_FILE="vfic_pg_backup_$${TIMESTAMP}.dump" && \
	ENV_FILE="vfic_env_$${TIMESTAMP}.env" && \
	mkdir -p "$(BACKUP_DIR)" && \
	echo "Dumping PostgreSQL (container resolved via compose, not a hardcoded name)..." && \
	ssh root@$(PROD_SERVER) \
		'cd /opt/vfic && PG=$$(docker compose ps -q postgres) && \
		 [ -n "$$PG" ] || { echo "ERROR: compose reports no postgres container"; exit 1; } && \
		 docker exec "$$PG" pg_dump -U vfic -Fc -Z6 > /tmp/vfic_pg.dump' && \
	ssh root@$(PROD_SERVER) \
		'test -s /tmp/vfic_pg.dump || { echo "ERROR: Backup file is empty!"; exit 1; }' && \
	echo "Downloading to local machine..." && \
	scp root@$(PROD_SERVER):/tmp/vfic_pg.dump "$(BACKUP_DIR)/$${BACKUP_FILE}" && \
	ssh root@$(PROD_SERVER) "rm -f /tmp/vfic_pg.dump" && \
	echo "Fetching /opt/vfic/.env (holds the integration-credential encryption key)..." && \
	scp root@$(PROD_SERVER):/opt/vfic/.env "$(BACKUP_DIR)/$${ENV_FILE}" && \
	chmod 600 "$(BACKUP_DIR)/$${ENV_FILE}" && \
	ssh root@$(PROD_SERVER) "chmod 600 /opt/vfic/.env" && \
	if ! grep -q "^INTEGRATION_SETTINGS_ENCRYPTION_KEY=..*" "$(BACKUP_DIR)/$${ENV_FILE}"; then \
		echo "WARNING: the backed-up .env has no INTEGRATION_SETTINGS_ENCRYPTION_KEY —"; \
		echo "         stored integration credentials will only decrypt while JWT_SECRET stays fixed." ; \
	fi && \
	echo "Pruning old dumps (keeping the newest $(BACKUP_KEEP))..." && \
	ls -1t "$(BACKUP_DIR)"/vfic_pg_backup_*.dump 2>/dev/null | tail -n +$$(($(BACKUP_KEEP) + 1)) | xargs -r rm -f && \
	echo "Pruning env copies whose dump pair is gone..." && \
	for env in "$(BACKUP_DIR)"/vfic_env_*.env; do \
		[ -e "$$env" ] || continue; \
		ts="$$(basename "$$env" | sed -e 's/^vfic_env_//' -e 's/\.env$$//')"; \
		if [ ! -f "$(BACKUP_DIR)/vfic_pg_backup_$$ts.dump" ] && [ ! -f "$(BACKUP_DIR)/vfic_pg_backup_$$ts.sql.gz" ]; then \
			echo "  removing orphaned $$(basename "$$env") (its dump was pruned)"; \
			rm -f "$$env"; \
		fi; \
	done && \
	echo "Backup complete!" && \
	echo "  Dump: $(BACKUP_DIR)/$${BACKUP_FILE}" && \
	echo "  Env:  $(BACKUP_DIR)/$${ENV_FILE}" && \
	echo "  Size: $$(du -h "$(BACKUP_DIR)/$${BACKUP_FILE}" | cut -f1)"

## restore: restore the newest bundle into the local dev DB, failing loudly.
## psql runs with ON_ERROR_STOP=1 so a partial load can never report success,
## and the password reset asks first (FORCE=1 skips the prompt) (OPS-20).
restore:
	@set -euo pipefail && \
	echo "=== Starting DB restore ===" && \
	cd backend && docker compose -f docker-compose.dev.yml up -d postgres && \
	PG="$$(docker compose -f docker-compose.dev.yml ps -q postgres)" && \
	[ -n "$$PG" ] || { echo "ERROR: compose reports no postgres container"; exit 1; } && \
	until docker exec "$$PG" pg_isready -U vfic >/dev/null 2>&1; do sleep 1; done && \
	LATEST_DUMP=$$(ls -t "$(BACKUP_DIR)"/vfic_pg_backup_*.dump 2>/dev/null | head -1) && \
	LATEST_SQL=$$(ls -t "$(BACKUP_DIR)"/vfic_pg_backup_*.sql.gz 2>/dev/null | head -1) && \
	if [ -n "$$LATEST_DUMP" ]; then SRC="$$LATEST_DUMP"; elif [ -n "$$LATEST_SQL" ]; then SRC="$$LATEST_SQL"; else echo "ERROR: No backup found in $(BACKUP_DIR)"; exit 1; fi && \
	echo "Using backup: $$SRC ($$(du -h "$$SRC" | cut -f1))" && \
	BACKUP_ENV="$(BACKUP_DIR)/vfic_env_$$(basename "$$SRC" | sed -e 's/^vfic_pg_backup_//' -e 's/\.dump$$//' -e 's/\.sql\.gz$$//').env" && \
	BKEY="$$(sed -n 's/^INTEGRATION_SETTINGS_ENCRYPTION_KEY=//p' "$$BACKUP_ENV" 2>/dev/null | tail -1)" && \
	BKEY="$${BKEY:-$$(sed -n 's/^JWT_SECRET=//p' "$$BACKUP_ENV" 2>/dev/null | tail -1)}" && \
	LKEY="$$(sed -n 's/^INTEGRATION_SETTINGS_ENCRYPTION_KEY=//p' .env | tail -1)" && \
	LKEY="$${LKEY:-$$(sed -n 's/^JWT_SECRET=//p' .env | tail -1)}" && \
	if [ ! -f "$$BACKUP_ENV" ]; then \
		echo "WARNING: $$BACKUP_ENV not found (backup predates the .env snapshot) —"; \
		echo "         sealed integration credentials may be undecryptable after this restore."; \
	elif [ "$$BKEY" != "$$LKEY" ]; then \
		if [ "$(ALLOW_KEY_MISMATCH)" != "1" ]; then \
			echo "ERROR: the backup's sealing key differs from backend/.env — after the restore every"; \
			echo "       integration_settings row raises InvalidTag and the service silently falls back"; \
			echo "       to env values (credentials look configured but are not)."; \
			echo "       Fix: copy INTEGRATION_SETTINGS_ENCRYPTION_KEY from $$BACKUP_ENV into backend/.env,"; \
			echo "       or acknowledge explicitly:  make restore ALLOW_KEY_MISMATCH=1"; \
			exit 1; \
		else \
			echo "WARNING (ALLOW_KEY_MISMATCH=1): sealed integration rows will NOT decrypt in dev."; \
		fi; \
	fi && \
	TMP="$$(mktemp -d -t vfic-restore.XXXXXX)" && \
	trap 'rm -rf "$$TMP"' EXIT && \
	echo "Terminating active connections and recreating database..." && \
	docker exec "$$PG" psql -U vfic -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'vfic' AND pid <> pg_backend_pid();" && \
	docker exec "$$PG" psql -U vfic -d postgres -c "DROP DATABASE IF EXISTS vfic;" && \
	docker exec "$$PG" psql -U vfic -d postgres -c "CREATE DATABASE vfic;" && \
	echo "Restoring backup into local database..." && \
	case "$$SRC" in \
		*.dump) docker exec -i "$$PG" pg_restore --exit-on-error -U vfic -d vfic < "$$SRC" ;; \
		*.gz)   gunzip -c "$$SRC" > "$$TMP/dump.sql" && \
		        docker exec -i "$$PG" psql -v ON_ERROR_STOP=1 -U vfic -d vfic < "$$TMP/dump.sql" ;; \
	esac && \
	echo "Running Alembic stamp (mark DB as at head)..." && \
	.venv/bin/python -m alembic stamp head && \
	if [ "$${FORCE:-0}" = "1" ]; then RESET=1; else \
		printf "Reset ALL local user passwords to admin123? [y/N] "; read -r answer; \
		case "$$answer" in y|Y|yes|YES) RESET=1 ;; *) RESET=0 ;; esac; \
	fi && \
	if [ "$$RESET" = "1" ]; then \
		echo "Resetting all user passwords to admin123..." && \
		.venv/bin/python -m scripts.reset_passwords --password admin123 && \
		.venv/bin/python -m scripts.create_admin --only-if-no-admins --email admin@vfic.dev --password admin123 --full-name "Dev Admin" --role admin && \
		echo "  All users reset to password: admin123"; \
	else echo "Password reset skipped (FORCE=1 resets without asking)."; fi && \
	echo "Verifying sealed integration settings decrypt..." && \
	if [ "$(ALLOW_KEY_MISMATCH)" = "1" ]; then echo "  skipped (ALLOW_KEY_MISMATCH=1)."; \
	else .venv/bin/python -m scripts.verify_integration_secrets; fi && \
	echo "Restore complete!"

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
