.PHONY: build help push

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

install: package.json ## install dependencies
	npm install

install-playwright-browsers: install ## install the playwright browsers (chromium, firefox, webkit)
	npx playwright install chromium

start-app: ## start the app locally
	npm run dev

start-demo: ## start the app locally in demo mode
	npm run dev:demo

start: start-app ## start the app locally

build: ## build the app
	npm run build

build-demo: ## build the app in demo mode
	npm run build:demo

test-app:
	npm run test:unit:app

test-unit: test-app

test: test-unit

lint:
	npm run lint
	npm run prettier

publish:
	npm publish

typecheck:
	npm run typecheck

doc-install:
	@(cd doc && npm install)

doc: doc-dev

doc-dev:
	@(cd doc && npm run dev)

doc-build:
	@(cd doc && npm run build)

doc-preview: doc-build
	@(cd doc && npm run preview)

doc-deploy:
	@(cd doc && npx gh-pages -b gh-pages -d dist -e doc -m "Deploy docs" --remove doc)

registry-build: ## build the shadcn registry
	npm run registry:build

registry-deploy: registry-build ## Deploy the shadcn registry (Automatically done by CI/CD pipeline)
	@(cd public/r && npx gh-pages -b gh-pages -d ./ -s atomic-crm.json -e r -m "Deploy registry" --remove r)

registry-gen: ## Generate the shadcn registry (ran automatically by a pre-commit hook)
	npm run registry:gen
	npx prettier --config ./.prettierrc.json --write "registry.json"

update-changelog: ## Update the changelog with the unreleased changes (ran automatically by a pre-commit hook)
	npm run update-changelog
	npx prettier --config ./.prettierrc.json --write "CHANGELOG.md"

storybook: ## start storybook
	npm run storybook

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

# ---- VFIC production image (DockerHub) ----
# Build & push the AMD64 frontend image. Tags immutable SHA + :latest; uses
# registry cache. Mirrors payroll/backend/Makefile `push`. The DockerHub account
# is already authed locally via the Docker Desktop keychain (no password here).
IMAGE_NAME := franknguyenvd/tinghire-fe
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
		--build-arg BUILDKIT_INLINE_CACHE=1 \
		--push \
		.
	@echo "Push complete: $(IMAGE_NAME):latest ($(GIT_SHA))"
