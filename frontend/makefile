.PHONY: build help push

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

install: package.json package-lock.json ## install dependencies reproducibly from the lockfile
	npm ci

install-playwright-browsers: install ## install the playwright browsers (chromium, firefox, webkit)
	npx playwright install chromium

start-app: ## start the app locally
	npm run dev

start: start-app ## start the app locally

build: ## build the app
	npm run build

test-app:
	npm run test:unit:app

test-unit: test-app

test: test-unit

lint:
	npm run lint
	npm run prettier

typecheck:
	npm run typecheck

registry-build: ## build the shadcn registry
	npm run registry:build

registry-gen: ## Generate the shadcn registry (ran automatically by a pre-commit hook)
	npm run registry:gen
	npx prettier --config ./.prettierrc.json --write "registry.json"

harness: ## run the agent harness interactively (pass REQUEST="..." to pre-fill)
	scripts/launch-harness.sh "$(REQUEST)"

clean-harness: ## clean up the agent harness session
	scripts/clean-harness.sh

watch: ## live monitor of the most recent agent session (agents, hooks, diagnosis)
	node scripts/harness-monitor.mjs --watch

monitor: ## one-shot summary of the most recent agent session (pass SESSION=<id> to pick one)
	@node scripts/harness-monitor.mjs $(if $(SESSION),--session $(SESSION),)

sessions: ## list known agent sessions, newest first
	@node scripts/harness-monitor.mjs --list

# ---- VFIC production image (GHCR) ----
# Build & push the AMD64 frontend image. Tags immutable SHA + :latest; uses
# registry cache. Mirrors backend/Makefile `push`. Auth comes from
# `gh auth token | docker login ghcr.io` (no password stored here).
IMAGE_NAME := ghcr.io/4rankng/tinghire-fe
GIT_SHA    := $(shell git rev-parse --short HEAD)
BUILDER    := bb

push:
	@docker buildx inspect $(BUILDER) >/dev/null 2>&1 || docker buildx create --name $(BUILDER) --driver docker-container --use
	@docker buildx use $(BUILDER)
	@docker buildx inspect --bootstrap >/dev/null
	@echo "Building & pushing AMD64 frontend image..."
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
	@echo "Push complete: $(IMAGE_NAME):latest ($(GIT_SHA))"
