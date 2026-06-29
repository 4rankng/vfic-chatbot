.PHONY: dev deploy deploy-backend deploy-frontend adminer

# Local dev: frontend (vite) + backend (uvicorn --reload) on host, Postgres +
# Redis + Adminer in docker. Delegates to backend/ (payroll pattern).
dev:
	@echo "=== Starting VFIC dev environment ==="
	$(MAKE) -C backend dev

# Build & push BOTH DockerHub images, then deploy to bot.tingting.vip.
deploy:
	@echo "=== Building & pushing frontend ==="
	cd frontend && make push
	@echo "=== Building & pushing backend ==="
	cd backend && make push
	@echo "=== Deploying to production ==="
	$(MAKE) -C backend deploy

# Adminer over an SSH tunnel -> http://localhost:18081 (no public exposure).
# Ctrl-C closes the tunnel.
adminer:
	$(MAKE) -C backend adminer

# Fast-track: rebuild + push + rolling restart backend only (web + workers + scheduler).
# Skips frontend build and full-stack bootstrap (compose sync, migrations, etc.).
deploy-backend:
	@echo "=== Deploying backend only ==="
	cd backend && make push
	$(MAKE) -C backend deploy-restart

# Fast-track: rebuild + push + rolling restart frontend only.
deploy-frontend:
	@echo "=== Deploying frontend only ==="
	cd frontend && make push
	$(MAKE) -C backend deploy-restart-frontend
