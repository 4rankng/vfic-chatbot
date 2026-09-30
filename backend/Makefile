.PHONY: dev db push deploy deploy-restart deploy-restart-frontend rollback deploy-status deploy-breaking adminer profile-backfill-run profile-backfill-status profile-backfill-logs

BACKEND_PORT  ?= 8000
FRONTEND_PORT ?= 5173
ZALO_MOCK_PORT ?= 8788
PROD_SERVER   := bot.tingting.vip
PROD_DIR      := /opt/vfic
IMAGE_NAME    := ghcr.io/4rankng/tinghire-be
GIT_SHA       := $(shell git rev-parse --short HEAD)
IMAGE_TAG     ?= $(GIT_SHA)
BUILDER       := bb
PY            := ./.venv/bin/python

# /opt/vfic/.env carries no IMAGE_TAG (scripts/prod-env.sh never writes it),
# but the prod compose file demands one for EVERY subcommand: `${IMAGE_TAG:?}`
# interpolates the whole file even for `ps`/`start`/`logs`, none of which touch
# an app image, so a read-only command aborts on the guard before it runs. It
# also cannot be satisfied by auto-loading .env. So resolve the tag the active
# web color ACTUALLY runs — plain `docker`, no compose call, so there is no
# interpolation chicken-and-egg — falling back to PREV_TAG and finally to
# `unknown`, a placeholder that only satisfies interpolation. Same recipe as
# scripts/backup-droplet.sh (OPS-21). `cd` first so the state-file reads are
# never relative to the caller's cwd.
RESOLVE_IMAGE_TAG = cd $(PROD_DIR) && COLOR="$$(tr -d "[:space:]" < ACTIVE_COLOR 2>/dev/null || echo blue)" && CID="$$(docker ps -q --filter name=web-$$COLOR | head -1)" && if [ -n "$$CID" ]; then TAG="$$(docker inspect --format "{{.Config.Image}}" "$$CID" | sed "s/.*://")"; else TAG="$$(cat PREV_TAG 2>/dev/null || echo unknown)"; fi; [ -n "$$TAG" ] || TAG=unknown; export IMAGE_TAG="$$TAG"

# Deploy opens ~9 sequential SSH sessions. Reuse ONE master connection
# (ControlMaster) so a single transient refusal ("ssh: connect to host ...
# Connection refused") on the droplet can't abort the deploy mid-step, and
# ControlPersist keeps that socket warm across commands without re-handshaking.
SSH_MUX     := -o ControlMaster=auto -o ControlPath=/tmp/vfic-deploy-%r@%h:%p -o ControlPersist=600
SSH         := ssh $(SSH_MUX)
SCP         := scp $(SSH_MUX)

# ---- Local dev DB: Postgres+pgvector, Redis, Adminer in docker (+ migrate + seed). ----
db:
	@echo "==> Starting dev stack (postgres + redis + adminer)..."
	docker compose -f docker-compose.dev.yml up -d
	@echo "==> Waiting for Postgres..."
	@timeout 60 sh -c 'until [ "$$(docker inspect --format "{{.State.Health.Status}}" "$$(docker compose -f docker-compose.dev.yml ps -q postgres)" 2>/dev/null)" = healthy ]; do sleep 1; done' || echo "  Postgres slow to start"
	@if [ ! -f .env ]; then \
		sed -e 's#@postgres:#@localhost:5443:#g' -e 's#redis://redis:6379#redis://localhost:6382#g' .env.example > .env; \
		echo "==> Created backend/.env from .env.example (localhost dev URLs). Set API keys to exercise the bot."; \
	fi
	@echo "==> Applying Alembic baseline (idempotent)..."
	@$(PY) -m scripts.widen_alembic_version || echo "  (widen skipped — ensure backend/.venv exists: pip install -e .[dev])"
	@$(PY) -m alembic upgrade head || echo "  (alembic skipped — ensure backend/.venv exists: pip install -e .[dev])"
	@$(PY) -m scripts.create_admin --email admin@vfic.dev --password admin123 --full-name "Dev Admin" --role admin 2>/dev/null || true
	@echo "==> Dev DB ready. Adminer: http://localhost:8082 (server: postgres, db: vfic, user/pass: vfic/vfic)"

# ---- Kill any process bound to $(1) (a port number). ----
# Runs before `dev` so a stale uvicorn / vite from a previous Ctrl-C, crash or
# a stray `npm run dev` on another terminal can never block startup. lsof works
# on macOS and Linux; safe to run when the port is already free (no-op).
# Uses a bash while-read loop (not xargs -r) so it works with BSD xargs on macOS.
define kill-port
	@echo "==> Freeing port $(1) (if occupied)..."
	@bash -c 'lsof -ti :$(1) 2>/dev/null | while read pid; do kill -9 "$$pid" 2>/dev/null || true; done; exit 0'
endef

define kill-ingest-workers
	@echo "==> Stopping stale ingest workers for this checkout (if any)..."
	@bash -c 'root="$$(pwd)"; pgrep -f "rq worker ingest" 2>/dev/null | while read pid; do cwd="$$(lsof -a -d cwd -p "$$pid" -Fn 2>/dev/null | sed -n "s/^n//p")"; [ "$$cwd" = "$$root" ] && kill "$$pid" 2>/dev/null || true; done; exit 0'
endef

define kill-chatbot-workers
	@echo "==> Stopping stale chatbot workers for this checkout (if any)..."
	@bash -c 'root="$$(pwd)"; pgrep -f "rq worker webhook_high" 2>/dev/null | while read pid; do cwd="$$(lsof -a -d cwd -p "$$pid" -Fn 2>/dev/null | sed -n "s/^n//p")"; [ "$$cwd" = "$$root" ] && kill "$$pid" 2>/dev/null || true; done; exit 0'
endef

# ---- Local dev: DB + backend (uvicorn) + workers + frontend + zalo mock in ONE terminal. ----
# Each server has its own port (BACKEND_PORT / FRONTEND_PORT / ZALO_MOCK_PORT);
# `kill-port` frees them before binding, and the kill-workers macros remove
# orphaned RQ workers from previous runs. BACKEND_PORT is exported into the
# vite subprocess so its dev-server proxy target tracks it (see
# frontend/vite.config.ts) — override all together, e.g. `make dev BACKEND_PORT=8001`.
# ZALO_BOT_API_BASE + ZALO_BOT_TOKEN are exported so the backend routes all
# outbound Zalo calls to the local mock (no real Zalo traffic).
# Ctrl+C stops the app servers + workers + mock from this run (the DB containers stay running).
dev: db
	$(call kill-port,$(BACKEND_PORT))
	$(call kill-port,$(FRONTEND_PORT))
	$(call kill-port,$(ZALO_MOCK_PORT))
	$(call kill-ingest-workers)
	$(call kill-chatbot-workers)
	@echo ""
	@echo "==> Starting backend (:$(BACKEND_PORT)) + workers + frontend (:$(FRONTEND_PORT)) + zalo mock (:$(ZALO_MOCK_PORT)) — Ctrl+C stops all."
	@echo "    App : http://localhost:$(FRONTEND_PORT)   Login: admin@vfic.dev / admin123"
	@echo "    Mock: http://localhost:$(ZALO_MOCK_PORT)   (Zalo traffic → localhost, not real Zalo)"
	@bash -c 'trap "kill 0" INT TERM EXIT; \
		export BACKEND_PORT="$(BACKEND_PORT)"; \
		export ZALO_BOT_API_BASE="http://localhost:$(ZALO_MOCK_PORT)"; \
		export ZALO_BOT_TOKEN="dev-mock-token"; \
		REDIS_URL="$$(grep "^REDIS_URL=" .env | cut -d= -f2-)"; \
		(exec $(PY) -m uvicorn app.main:app --reload --port $(BACKEND_PORT)) & \
		(exec $(PY) -m rq.cli worker ingest --worker-class rq.SimpleWorker --url "$$REDIS_URL") & \
		(exec $(PY) -m rq.cli worker webhook_high recovery persistence_low --worker-class rq.SimpleWorker --url "$$REDIS_URL") & \
		(exec $(PY) -m mock_servers.zalo_mock --port $(ZALO_MOCK_PORT)) & \
		(cd ../frontend && exec npm run dev -- --port $(FRONTEND_PORT) --strictPort) & wait'

# ---- Build & push the AMD64 backend image to DockerHub. ----
push:
	@docker buildx inspect $(BUILDER) >/dev/null 2>&1 || docker buildx create --name $(BUILDER) --driver docker-container --use
	@docker buildx use $(BUILDER)
	@docker buildx inspect --bootstrap >/dev/null
	@echo "==> Building & pushing AMD64 backend image..."
	docker buildx build \
		--platform linux/amd64 \
		--tag $(IMAGE_NAME):latest \
		--tag $(IMAGE_NAME):$(GIT_SHA) \
		--cache-from type=registry,ref=$(IMAGE_NAME):latest \
		--cache-from type=registry,ref=$(IMAGE_NAME):buildcache \
		--cache-to type=registry,ref=$(IMAGE_NAME):buildcache,mode=max \
		--build-arg BUILDKIT_INLINE_CACHE=1 \
		--push \
		.
	@echo "==> Push complete: $(IMAGE_NAME):latest ($(GIT_SHA))"

# ---- Blue/green deploy to prod. Assumes `push` already ran (root Makefile runs both). ----
# Syncs compose + Caddy template + deploy scripts, ensures .env + bootstrap admin,
# then hands off to scripts/bg_deploy.sh (zero-downtime: smoke-gated Caddy flip).
deploy:
	@echo "==> Syncing compose + Caddy template + deploy scripts to $(PROD_SERVER):$(PROD_DIR)..."
	$(SSH) root@$(PROD_SERVER) "mkdir -p $(PROD_DIR)/scripts"
	$(SCP) docker-compose.yml Caddyfile.template root@$(PROD_SERVER):$(PROD_DIR)/
	$(SCP) scripts/bg_deploy.sh scripts/bg_rollback.sh scripts/flip_caddy.sh ../scripts/ops-alerts.sh root@$(PROD_SERVER):$(PROD_DIR)/scripts/
	@echo "==> Generating $(PROD_DIR)/.env if missing (infra secrets filled, API keys blank)..."
	$(SSH) root@$(PROD_SERVER) 'bash -s' < scripts/prod-env.sh
	@echo "==> Creating bootstrap admin (idempotent)..."
	-$(SSH) root@$(PROD_SERVER) 'cd $(PROD_DIR) && IMAGE_TAG=$(IMAGE_TAG) docker compose run --rm web-blue python -m scripts.create_admin --only-if-no-admins --email "$$(grep "^VFIC_BOOTSTRAP_ADMIN_EMAIL=" .env | cut -d= -f2-)" --password "$$(grep "^VFIC_BOOTSTRAP_ADMIN_PASSWORD=" .env | cut -d= -f2-)" --full-name "VFIC Admin" --role admin'
	@echo "==> Running blue/green deploy (smoke-gated Caddy flip)..."
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && IMAGE_TAG=$(IMAGE_TAG) bash scripts/bg_deploy.sh"

# ---- Blue/green fast-track: re-deploy backend only (no compose sync / bootstrap). ----
# Used by root Makefile's deploy-backend after push. Re-syncs compose + deploy
# scripts, then runs the same smoke-gated flip.
deploy-restart:
	@echo "==> Syncing compose + deploy scripts to $(PROD_SERVER)..."
	$(SSH) root@$(PROD_SERVER) "mkdir -p $(PROD_DIR)/scripts"
	$(SCP) docker-compose.yml root@$(PROD_SERVER):$(PROD_DIR)/
	$(SCP) scripts/bg_deploy.sh scripts/bg_rollback.sh scripts/flip_caddy.sh ../scripts/ops-alerts.sh root@$(PROD_SERVER):$(PROD_DIR)/scripts/
	@echo "==> Running blue/green deploy (smoke-gated Caddy flip)..."
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && IMAGE_TAG=$(IMAGE_TAG) bash scripts/bg_deploy.sh"

# ---- Flip traffic back to the previous color/tag (~1s, no rebuild, reversible). ----
rollback:
	@echo "==> Rolling back to previous color/tag on $(PROD_SERVER)..."
	$(SSH) root@$(PROD_SERVER) "mkdir -p $(PROD_DIR)/scripts"
	$(SCP) scripts/bg_rollback.sh scripts/flip_caddy.sh root@$(PROD_SERVER):$(PROD_DIR)/scripts/
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && bash scripts/bg_rollback.sh"

# ---- Show active color, previous color/tag, and container health on prod. ----
# `docker compose ps` interpolates the whole file, so the tag is resolved
# first (RESOLVE_IMAGE_TAG) or the `${IMAGE_TAG:?}` guard aborts the command.
deploy-status:
	@echo "==> $(PROD_SERVER) blue/green status"
	$(SSH) root@$(PROD_SERVER) '$(RESOLVE_IMAGE_TAG) && echo "ACTIVE_COLOR=$$(cat ACTIVE_COLOR 2>/dev/null || echo inaugural)  PREV=$$(cat PREV_COLOR 2>/dev/null || echo none)@$$(cat PREV_TAG 2>/dev/null || echo none)" && docker compose ps'

# ---- Observable OA profile backfill maintenance job. ----
# Each status/logs call is its own SSH session, so each resolves the tag
# itself; the backfill is a profile-gated one-shot container, never a gate.
profile-backfill-run:
	$(SSH) root@$(PROD_SERVER) '$(RESOLVE_IMAGE_TAG) && docker compose --profile maintenance up -d --no-deps --force-recreate oa-profile-backfill'

profile-backfill-status:
	$(SSH) root@$(PROD_SERVER) '$(RESOLVE_IMAGE_TAG) && docker compose --profile maintenance ps -a oa-profile-backfill && CID="$$(docker compose --profile maintenance ps -aq oa-profile-backfill)" && if [ -n "$$CID" ]; then docker inspect --format "status={{.State.Status}} exit={{.State.ExitCode}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}" "$$CID"; fi'

profile-backfill-logs:
	$(SSH) root@$(PROD_SERVER) '$(RESOLVE_IMAGE_TAG) && docker compose --profile maintenance logs --tail=100 oa-profile-backfill'

# ---- Breaking-migration path (brief downtime; NOT blue/green). ----
# Use ONLY for a non-additive migration that old+new code cannot both run against.
# Drains both web colors, migrates, brings up web-blue on the new schema, flips.
# The pull and `up` lists below must name EVERY ${IMAGE_TAG} service: on this
# path nothing drains the old code, so anything omitted keeps running a
# previous release against the schema the migration just changed.
# worker-maintenance (the outbound dispatcher that pushes bot replies to Zalo)
# and metrics-watch were both missing and survived on stale code (OPS-22);
# backend/tests/test_deployment_makefile.py pins the coverage.
deploy-breaking:
	@echo "==> WARNING: deploy-breaking accepts brief downtime (non-additive migration)."
	$(SSH) root@$(PROD_SERVER) "mkdir -p $(PROD_DIR)/scripts"
	$(SCP) docker-compose.yml Caddyfile.template root@$(PROD_SERVER):$(PROD_DIR)/
	$(SCP) scripts/flip_caddy.sh root@$(PROD_SERVER):$(PROD_DIR)/scripts/
	$(SSH) root@$(PROD_SERVER) 'bash -s' < scripts/prod-env.sh
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && IMAGE_TAG=$(IMAGE_TAG) docker compose pull web-blue worker-chatbot worker-persistence worker-ingest worker-category worker-followup scheduler worker-maintenance metrics-watch frontend"
	@echo "==> Stopping web colors (downtime starts)..."
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && docker compose stop web-blue web-green 2>/dev/null || true"
	@echo "==> Applying non-additive migration..."
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && IMAGE_TAG=$(IMAGE_TAG) docker compose run --rm web-blue sh -c 'python -m scripts.widen_alembic_version && alembic upgrade head'"
	@echo "==> Bringing up web-blue + workers on the new schema (downtime ends)..."
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && IMAGE_TAG=$(IMAGE_TAG) docker compose up -d --force-recreate web-blue worker-chatbot worker-persistence worker-ingest worker-category worker-followup scheduler worker-maintenance metrics-watch frontend"
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && IMAGE_TAG=$(IMAGE_TAG) bash scripts/flip_caddy.sh blue && echo blue > ACTIVE_COLOR"

# ---- Adminer over SSH tunnel (private; never public). ----
adminer:
	@echo "==> Opening Adminer over SSH tunnel -> http://localhost:18081"
	@echo "    Server: postgres   DB: vfic   user/pass from $(PROD_DIR)/.env"
	@echo "    Ctrl-C to close the tunnel."
	@ssh root@$(PROD_SERVER) '$(RESOLVE_IMAGE_TAG) && docker compose start adminer' 2>/dev/null || true
	# Tunnel is blocking, so background it, poll until adminer actually serves
	# over the tunnel, then open the browser — avoids the ERR_CONNECTION_REFUSED
	# race where `open` fired before ssh had bound the local forward.
	@ssh -N -L 18081:127.0.0.1:8081 root@$(PROD_SERVER) & pid=$$!; \
		ok=0; \
		for i in $$(seq 1 15); do \
			if curl -sf -o /dev/null http://localhost:18081; then ok=1; break; fi; \
			sleep 1; \
		done; \
		[ $$ok -eq 1 ] || echo "  adminer not responding yet — refresh http://localhost:18081 shortly, or 'docker compose logs adminer' on prod"; \
		(open http://localhost:18081 || xdg-open http://localhost:18081 || true); \
		wait $$pid

# ---- Fast-track: pull + rolling restart frontend container only. ----
deploy-restart-frontend:
	@echo "==> Pulling frontend image on $(PROD_SERVER)..."
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && IMAGE_TAG=$(IMAGE_TAG) docker compose pull frontend"
	@echo "==> Recreating frontend container..."
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && IMAGE_TAG=$(IMAGE_TAG) docker compose up -d --force-recreate frontend"
	@echo "==> Frontend deploy done."
