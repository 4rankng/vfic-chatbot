.PHONY: dev db push deploy adminer

PROD_SERVER := bot.tingting.vip
PROD_DIR    := /opt/vfic
IMAGE_NAME  := franknguyenvd/vfic-backend
GIT_SHA     := $(shell git rev-parse --short HEAD)
BUILDER     := bb

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
		sed -e 's#@postgres:#@localhost:#g' -e 's#redis://redis:6379#redis://localhost:6382#g' .env.example > .env; \
		echo "==> Created backend/.env from .env.example (localhost dev URLs). Set API keys to exercise the bot."; \
	fi
	@echo "==> Applying Alembic baseline (idempotent)..."
	@. .venv/bin/activate && alembic upgrade head || echo "  (alembic skipped — ensure backend/.venv exists: pip install -e .[dev])"
	@. .venv/bin/activate && python -m scripts.create_admin --email admin@vfic.dev --password admin123 --full-name "Dev Admin" --role admin 2>/dev/null || true
	@echo "==> Dev DB ready. Adminer: http://localhost:8081 (server: postgres, db: vfic, user/pass: vfic/vfic)"

# ---- Local dev: DB + backend (uvicorn) + frontend (vite) in ONE terminal. ----
# Ctrl+C stops both app servers (the DB containers stay running). Backend and
# frontend run on the host for fast hot-reload; Vite proxies /api, /realtime and
# /socket.io to the backend (see frontend/vite.config.ts), so just open the app.
dev: db
	@echo ""
	@echo "==> Starting backend (:8000) + frontend (:5173) — Ctrl+C stops both."
	@echo "    App : http://localhost:5173   Login: admin@vfic.dev / admin123"
	@bash -c 'trap "kill 0" INT TERM EXIT; (. .venv/bin/activate && exec uvicorn app.main:app --reload --port 8000) & (cd ../frontend && exec npm run dev) & wait'

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
		--build-arg BUILDKIT_INLINE_CACHE=1 \
		--push \
		.
	@echo "==> Push complete: $(IMAGE_NAME):latest ($(GIT_SHA))"

# ---- Deploy to prod. Assumes `push` already ran (root Makefile runs both). ----
deploy:
	@echo "==> Syncing compose + Caddyfile to $(PROD_SERVER):$(PROD_DIR)..."
	$(SSH) root@$(PROD_SERVER) "mkdir -p $(PROD_DIR)"
	$(SCP) docker-compose.yml Caddyfile root@$(PROD_SERVER):$(PROD_DIR)/
	@echo "==> Generating $(PROD_DIR)/.env if missing (infra secrets filled, API keys blank)..."
	$(SSH) root@$(PROD_SERVER) 'bash -s' < scripts/prod-env.sh
	@echo "==> Pulling images..."
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && docker compose pull"
	@echo "==> Tearing down n8n (big-bang) to free :80/:443..."
	-$(SSH) root@$(PROD_SERVER) "cd /opt/n8n-docker-caddy && docker compose down -v" 2>/dev/null || true
	@echo "==> Starting Postgres + Redis..."
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && docker compose up -d postgres redis"
	@echo "==> Waiting for Postgres healthy (retries transient SSH refusals)..."
	@ok=0; for i in 1 2 3 4 5; do \
		timeout 60 sh -c "$(SSH) root@$(PROD_SERVER) 'cd $(PROD_DIR) && until docker compose exec -T postgres pg_isready -U vfic >/dev/null 2>&1; do sleep 2; done'" && { ok=1; break; }; \
		echo "  SSH/pg_isready refused (attempt $$i/5), retrying in 4s..."; sleep 4; \
	done; [ $$ok -eq 1 ] || echo "  Postgres slow to come up"
	@echo "==> Applying Alembic baseline (retries transient SSH refusals)..."
	@ok=0; for i in 1 2 3 4 5; do \
		$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && docker compose run --rm web alembic upgrade head" && { ok=1; break; }; \
		echo "  alembic SSH refused (attempt $$i/5), retrying in 4s..."; sleep 4; \
	done; [ $$ok -eq 1 ]
	@echo "==> Creating bootstrap admin (idempotent)..."
	@$(SSH) root@$(PROD_SERVER) 'cd $(PROD_DIR) && docker compose run --rm web python -m scripts.create_admin --email "$$(grep "^VFIC_BOOTSTRAP_ADMIN_EMAIL=" .env | cut -d= -f2-)" --password "$$(grep "^VFIC_BOOTSTRAP_ADMIN_PASSWORD=" .env | cut -d= -f2-)" --full-name "VFIC Admin" --role admin' || true
	@echo "==> Bringing up full stack..."
	$(SSH) root@$(PROD_SERVER) "cd $(PROD_DIR) && docker compose up -d"
	@echo "==============================================================="
	@echo " Deploy done."
	@echo "   health : https://$(PROD_SERVER)/health"
	@echo "   adminer: make adminer"
	@echo " Next: fill API keys in $(PROD_DIR)/.env, then:"
	@echo "   ssh root@$(PROD_SERVER) 'cd $(PROD_DIR) && docker compose up -d --force-recreate web worker-chatbot worker-ingest scheduler'"
	@echo " Then flip the Zalo OA webhook -> https://$(PROD_SERVER)/webhooks/zalo"
	@echo "==============================================================="

# ---- Adminer over SSH tunnel (private; never public). ----
adminer:
	@echo "==> Opening Adminer over SSH tunnel -> http://localhost:18081"
	@echo "    Server: postgres   DB: vfic   user/pass from $(PROD_DIR)/.env"
	@echo "    Ctrl-C to close the tunnel."
	@ssh root@$(PROD_SERVER) "cd $(PROD_DIR) && docker compose start adminer" 2>/dev/null || true
	@(sleep 1 && (open http://localhost:18081 || xdg-open http://localhost:18081 || true)) &
	@ssh -N -L 18081:127.0.0.1:8081 root@$(PROD_SERVER)
