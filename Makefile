.PHONY: dev bootstrap deploy deploy-backend deploy-frontend adminer seed backup restore backup-full restore-prod release-check

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

# bootstrap: one-command first run — .env, backend/.venv (Python 3.12 per
# backend/.python-version) and frontend/node_modules. The venv is built from
# backend/uv.lock, not re-resolved from pyproject ranges: `frontend/
# playwright.config.ts` points the e2e lane's BACKEND_PYTHON at this same
# .venv, so an unpinned resolve makes the tested backend unreproducible
# (TEST-19). Repeat runs are idempotent and pick up dependency changes.
bootstrap:
	@test -f backend/.env || { echo "backend/.env: created from .env.example — set real secrets before any deploy"; cp backend/.env.example backend/.env; }
	@if ! command -v python3.12 >/dev/null 2>&1; then \
		echo "WARNING: python3.12 not found — falling back to $$(command -v python3)."; \
		echo "         Production and CI run 3.12; install it (pyenv/mise) to match (OPS-13)."; \
	fi
	@if command -v uv >/dev/null 2>&1; then \
		echo "Syncing backend/.venv from backend/uv.lock (uv sync --frozen)..."; \
		cd backend && uv sync --all-extras --frozen; \
	else \
		echo "WARNING: uv not found — falling back to an UNPINNED pip resolve from"; \
		echo "         pyproject ranges. The e2e lane's BACKEND_PYTHON is this venv,"; \
		echo "         so what it installs is no longer reproducible from uv.lock."; \
		echo "         Install uv (https://docs.astral.sh/uv/) for a locked venv."; \
		test -d .venv || { python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv; }; \
		.venv/bin/python -m pip install --quiet --upgrade pip; \
		.venv/bin/python -m pip install --quiet -e ".[dev]"; \
	fi
	@test -d frontend/node_modules || { echo "Installing frontend deps (npm ci) ..."; cd frontend && npm ci; }
	@echo "bootstrap complete — run 'make dev'"

# Release must be committed and validated before any image is pushed or production is touched.
# Every gate runs on this machine — there is no CI in the loop.
# `make deploy` does NOT chain this target — run it explicitly before deploying.
# Heavy gates run as three concurrent lanes (backend | frontend | data); any lane
# failure fails the release and keeps its full log. Lane contents: docs/ops/deployment-guide.md §3.
release-check:
	@dirty="$$(git status --porcelain)"; \
	if [ -n "$$dirty" ]; then \
		echo "Release blocked: commit or stash all local changes first."; \
		echo "$$dirty" | sed 's/^/    /'; \
		exit 1; \
	fi
	@git diff --check
	@if command -v uv >/dev/null 2>&1; then (cd backend && uv lock --check); else echo "WARNING: uv not found — skipped uv lock --check"; fi
	@cd backend && test "$$(.venv/bin/python -m alembic heads | wc -l | tr -d ' ')" = 1
	@cd backend && HEAD_REV="$$(.venv/bin/python -m alembic heads | awk 'NR==1{print $$1}')" && \
		grep -qF "**HEAD:** \`$$HEAD_REV" ../docs/ops/deployment-guide.md || { \
			echo "Release blocked: docs/ops/deployment-guide.md's Alembic HEAD no longer matches alembic heads ($$HEAD_REV) — update section 4 (Alembic migration run)."; exit 1; }
	@if command -v node >/dev/null 2>&1; then node scripts/check-doc-links.mjs; \
		else echo "Release blocked: node not found — cannot verify that agent routing (AGENTS.md, standards/) still resolves."; exit 1; fi
	@tmp="$$(mktemp -d -t vfic-release.XXXXXX)"; \
	rc_be=0; rc_fe=0; rc_data=0; \
	( cd backend && uvx pyright app/graph && .venv/bin/ruff check . && .venv/bin/python -m pytest -q -m "not integration" --cov --cov-config=.coveragerc --cov-report=term-missing:skip-covered ) >"$$tmp/backend.log" 2>&1 & \
	be_pid=$$!; \
	( cd frontend && npm audit --omit=dev --audit-level=high && npm run lint && npm run typecheck && npm run registry:check && npm run test:unit:app:coverage:changed-surface -- --run && npm run build && npm run smoke:built ) >"$$tmp/frontend.log" 2>&1 & \
	fe_pid=$$!; \
	( cd backend && .venv/bin/python -m pytest "tests/integration/test_migration_roundtrip_walk.py::test_chain_reverses_to_base_and_reapplies" "tests/integration/test_migration_roundtrip_walk.py::test_reverse_chain_renders_offline" -p no:randomly -m integration && .venv/bin/python scripts/benchmark_rag.py --gold --min-pass-rate 0 --output "$$tmp/golden-raw.json" --gate-output "$$tmp/golden.json" && RELEASE_GATE_LATENCY_SLO_ENABLED=false .venv/bin/python scripts/release_gate_check.py --golden-results "$$tmp/golden.json" ) >"$$tmp/data.log" 2>&1 & \
	data_pid=$$!; \
	wait $$be_pid; rc_be=$$?; \
	wait $$fe_pid; rc_fe=$$?; \
	wait $$data_pid; rc_data=$$?; \
	echo "===== backend lane (exit $$rc_be) ====="; cat "$$tmp/backend.log"; \
	echo "===== frontend lane (exit $$rc_fe) ====="; cat "$$tmp/frontend.log"; \
	echo "===== data lane (exit $$rc_data) ====="; cat "$$tmp/data.log"; \
	if [ "$$rc_be" -ne 0 -o "$$rc_fe" -ne 0 -o "$$rc_data" -ne 0 ]; then \
		echo "!!!! RELEASE-CHECK FAILED — red lane(s):"; \
		[ "$$rc_be" -ne 0 ] && echo "!!!!   backend (exit $$rc_be) — full log kept at $$tmp/backend.log"; \
		[ "$$rc_fe" -ne 0 ] && echo "!!!!   frontend (exit $$rc_fe) — full log kept at $$tmp/frontend.log"; \
		[ "$$rc_data" -ne 0 ] && echo "!!!!   data (exit $$rc_data) — full log kept at $$tmp/data.log"; \
		echo "!!!! (logs are NOT deleted on failure — scroll up for the lane banner, or open the kept file)"; \
	else \
		rm -rf "$$tmp"; \
	fi; \
	test "$$rc_be" -eq 0 -a "$$rc_fe" -eq 0 -a "$$rc_data" -eq 0

# Build & push BOTH GHCR images, then deploy to bot.tingting.vip.
#
# No release gates here: run `make release-check` first (step 1 of the
# documented flow — docs/ops/deployment-guide.md §3).
#
# This target runs `alembic upgrade head` on the production database, so a bad
# migration is only recoverable from a dump taken BEFORE the run. The backup
# therefore still hard-gates the cutover — but it no longer serializes in
# front of the image pushes: backup and both pushes run concurrently, and the
# recipe waits for all three (failing on any) before touching production.
# The commit this deploy ships. Resolved ONCE, when the Makefile is read, and
# passed to every lane below.
#
# Each `make` invocation re-evaluates its own `GIT_SHA := $(shell git rev-parse
# --short HEAD)`. So without this, a commit landing between the image-push lanes
# and the cutover step made the deploy target a SHA whose image was never built
# or pushed — the blue/green script then aborted at "image not found", after
# the pushes had already been tagged to the older commit. Pinning it here makes
# every lane agree on one SHA regardless of what happens to the worktree
# mid-flight.
DEPLOY_SHA := $(shell git rev-parse --short HEAD)

deploy:
	@echo "=== Deploying commit $(DEPLOY_SHA) ==="
	@tmp="$$(mktemp -d -t vfic-deploy.XXXXXX)"; \
	rc_backup=0; rc_fe=0; rc_be=0; \
	( $(MAKE) backup ) >"$$tmp/backup.log" 2>&1 & backup_pid=$$!; \
	( cd frontend && $(MAKE) push GIT_SHA=$(DEPLOY_SHA) ) >"$$tmp/fe-push.log" 2>&1 & fe_pid=$$!; \
	( cd backend && $(MAKE) push GIT_SHA=$(DEPLOY_SHA) ) >"$$tmp/be-push.log" 2>&1 & be_pid=$$!; \
	wait $$backup_pid; rc_backup=$$?; \
	wait $$fe_pid; rc_fe=$$?; \
	wait $$be_pid; rc_be=$$?; \
	for lane in backup fe-push be-push; do echo "--- $$lane:"; cat "$$tmp/$$lane.log"; done; \
	rm -rf "$$tmp"; \
	test "$$rc_backup" -eq 0 -a "$$rc_fe" -eq 0 -a "$$rc_be" -eq 0 || exit 1
	@echo "=== Deploying to production (blue/green cutover) ==="
	$(MAKE) -C backend deploy GIT_SHA=$(DEPLOY_SHA)
	@echo "=== Recreating production frontend ==="
	$(MAKE) -C backend deploy-restart-frontend GIT_SHA=$(DEPLOY_SHA)

# Adminer over an SSH tunnel -> http://localhost:18081 (no public exposure).
# Ctrl-C closes the tunnel.
adminer:
	$(MAKE) -C backend adminer

# Fast-track: rebuild + push + rolling restart backend only (web + workers + scheduler).
# Skips frontend build and full-stack bootstrap (compose sync, migrations, etc.).
# The backup still gates the restart — the cutover runs `alembic upgrade head`
# — but runs concurrently with the image push instead of serially before it.
deploy-backend:
	@echo "=== Backup + backend image push run concurrently ==="
	@tmp="$$(mktemp -d -t vfic-deploy.XXXXXX)"; \
	rc_backup=0; rc_be=0; \
	( $(MAKE) backup ) >"$$tmp/backup.log" 2>&1 & backup_pid=$$!; \
	( cd backend && make push ) >"$$tmp/be-push.log" 2>&1 & be_pid=$$!; \
	wait $$backup_pid; rc_backup=$$?; \
	wait $$be_pid; rc_be=$$?; \
	for lane in backup be-push; do echo "--- $$lane:"; cat "$$tmp/$$lane.log"; done; \
	rm -rf "$$tmp"; \
	test "$$rc_backup" -eq 0 -a "$$rc_be" -eq 0 || exit 1
	@echo "=== Deploying backend only (blue/green cutover) ==="
	$(MAKE) -C backend deploy-restart

# Fast-track: rebuild + push + rolling restart frontend only.
deploy-frontend:
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

# backup: pg_dump the prod DB (custom format) and pull /opt/vfic/.env with it.
# The .env carries INTEGRATION_SETTINGS_ENCRYPTION_KEY: without it the dump
# alone cannot be decrypted by a restore (OPS-03). Keeps the newest $(BACKUP_KEEP)
# dumps; each vfic_env_*.env lives exactly as long as its dump pair (an env copy
# holds prod secrets, so an orphan whose dump was pruned is deleted, not kept).
# The remote step resolves IMAGE_TAG from the running active-color web
# container before any compose call: /opt/vfic/.env has no IMAGE_TAG and the
# prod compose file guards it with `${IMAGE_TAG:?}` for EVERY subcommand, so a
# bare `docker compose ps` aborted on interpolation and the backup never ran
# (OPS-21). Same recipe as scripts/backup-droplet.sh.
BACKUP_KEEP := 10
backup:
	@echo "=== Starting database backup from production ===" && \
	TIMESTAMP=$$(date +%Y-%m-%d_%H%M%S) && \
	BACKUP_FILE="vfic_pg_backup_$${TIMESTAMP}.dump" && \
	ENV_FILE="vfic_env_$${TIMESTAMP}.env" && \
	mkdir -p "$(BACKUP_DIR)" && \
	echo "Dumping PostgreSQL (container resolved via compose, not a hardcoded name)..." && \
	ssh root@$(PROD_SERVER) \
		'cd /opt/vfic && COLOR="$$(tr -d "[:space:]" < ACTIVE_COLOR 2>/dev/null || echo blue)" && \
		 CID="$$(docker ps -q --filter name=web-$$COLOR | head -1)" && \
		 if [ -n "$$CID" ]; then TAG="$$(docker inspect --format "{{.Config.Image}}" "$$CID" | sed "s/.*://")"; \
		 else TAG="$$(cat PREV_TAG 2>/dev/null || echo unknown)"; fi && \
		 [ -n "$$TAG" ] || TAG=unknown; \
		 PG=$$(IMAGE_TAG="$$TAG" docker compose ps -q postgres); \
		 [ -n "$$PG" ] || { echo "ERROR: compose reports no postgres container"; exit 1; }; \
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

# restore: restore the newest bundle into the local dev DB, failing loudly.
# psql runs with ON_ERROR_STOP=1 so a partial load can never report success,
# and the password reset asks first (FORCE=1 skips the prompt) (OPS-20).
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
# docs/ops/droplet-backup-restore.md has the full runbook. Redis is intentionally
# not backed up (scheduler re-registers its ticks; avoids the orphaned-job OOM).

# backup-full: bundle /opt/vfic/.env + DB dump + KB uploads + Caddy TLS → backups/<ts>.zip
# (the script owns the backups/ path and creates it)
backup-full:
	bash scripts/backup-droplet.sh

# restore-prod: push a bundle onto a FRESH droplet (SSH, mirrors `deploy`).
# Usage: make restore-prod BUNDLE=backups/vfic-droplet-backup-<TS> [HOST=root@bot.tingting.vip]
restore-prod:
	@test -n "$(BUNDLE)" || { echo "Usage: make restore-prod BUNDLE=backups/vfic-droplet-backup-<TS> [HOST=root@bot.tingting.vip]"; exit 2; }
	bash scripts/restore-droplet.sh --bundle "$(BUNDLE)" --host "$(or $(HOST),root@bot.tingting.vip)"
