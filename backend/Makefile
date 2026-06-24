.PHONY: dev push deploy adminer

PROD_SERVER := bot.tingting.vip
PROD_DIR    := /opt/vfic
IMAGE_NAME  := franknguyenvd/vfic-backend
GIT_SHA     := $(shell git rev-parse --short HEAD)
BUILDER     := bb

# ---- Local dev: DB/Redis/Adminer in docker, backend + frontend on host (hot-reload). ----
dev:
	@echo "==> Starting dev stack (postgres + redis + adminer)..."
	docker compose -f docker-compose.dev.yml up -d
	@echo "==> Waiting for Postgres..."
	@timeout 60 sh -c 'until docker compose -f docker-compose.dev.yml exec -T postgres pg_isready -U vfic >/dev/null 2>&1; do sleep 1; done' || echo "  Postgres slow to start"
	@if [ ! -f .env ]; then \
		sed -e 's#@postgres:#@localhost:#g' -e 's#redis://redis:#redis://localhost:#g' .env.example > .env; \
		echo "==> Created backend/.env from .env.example (localhost dev URLs). Set API keys to exercise the bot."; \
	fi
	@echo "==> Applying Alembic baseline (idempotent)..."
	@. .venv/bin/activate && alembic upgrade head || echo "  (alembic skipped — ensure backend/.venv exists: pip install -e .[dev])"
	@. .venv/bin/activate && python -m scripts.create_admin --email admin@vfic.dev --password admin123 --full-name "Dev Admin" --role admin 2>/dev/null || true
	@echo ""
	@echo "==> Dev DB ready. Start the app on the host:"
	@echo "    frontend : cd ../frontend && npm run dev        -> http://localhost:5173"
	@echo "    backend  : . .venv/bin/activate && uvicorn app.main:app --reload  -> http://localhost:8000"
	@echo "    adminer  : http://localhost:8081  (server: postgres, db: vfic, user/pass: vfic/vfic)"

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
	ssh root@$(PROD_SERVER) "mkdir -p $(PROD_DIR)"
	scp docker-compose.yml Caddyfile root@$(PROD_SERVER):$(PROD_DIR)/
	@echo "==> Generating $(PROD_DIR)/.env if missing (infra secrets filled, API keys blank)..."
	ssh root@$(PROD_SERVER) 'bash -s' < scripts/prod-env.sh
	@echo "==> Pulling images..."
	ssh root@$(PROD_SERVER) "cd $(PROD_DIR) && docker compose pull"
	@echo "==> Tearing down n8n (big-bang) to free :80/:443..."
	-ssh root@$(PROD_SERVER) "cd /opt/n8n-docker-caddy && docker compose down -v" 2>/dev/null || true
	@echo "==> Starting Postgres + Redis..."
	ssh root@$(PROD_SERVER) "cd $(PROD_DIR) && docker compose up -d postgres redis"
	@echo "==> Waiting for Postgres healthy..."
	@timeout 90 sh -c "ssh root@$(PROD_SERVER) 'cd $(PROD_DIR) && until docker compose exec -T postgres pg_isready -U vfic >/dev/null 2>&1; do sleep 2; done'" || echo "  Postgres slow to come up"
	@echo "==> Applying Alembic baseline..."
	ssh root@$(PROD_SERVER) "cd $(PROD_DIR) && docker compose run --rm web alembic upgrade head"
	@echo "==> Creating bootstrap admin (idempotent)..."
	@ssh root@$(PROD_SERVER) 'cd $(PROD_DIR) && docker compose run --rm web python -m scripts.create_admin --email "$$(grep "^VFIC_BOOTSTRAP_ADMIN_EMAIL=" .env | cut -d= -f2-)" --password "$$(grep "^VFIC_BOOTSTRAP_ADMIN_PASSWORD=" .env | cut -d= -f2-)" --full-name "VFIC Admin" --role admin' || true
	@echo "==> Bringing up full stack..."
	ssh root@$(PROD_SERVER) "cd $(PROD_DIR) && docker compose up -d"
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
