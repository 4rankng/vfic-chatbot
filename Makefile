# =============================================================================
# Nhân lực VFIC — Chatwoot build & deploy automation
# =============================================================================
# Centralized brand constants (single source of truth — edit here, then
# `make brand-apply` to bake into the static files, or `make deploy` which
# applies + builds + ships). Runtime/dynamic brand text also uses
# INSTALLATION_NAME=$(BRAND_NAME) via Chatwoot's replaceInstallationName().
# =============================================================================

# ---- Brand (centralized constant) ----
BRAND_NAME        := Nhân lực VFIC
SUPPORT_EMAIL     := frankng.sg@gmail.com
INSTALLATION_NAME := $(BRAND_NAME)
BRAND_URL         := https://tingting.vip
LOGO_LIGHT        := /light-logo.png
LOGO_DARK         := /dark-logo.png
LOGO_THUMBNAIL    := /vfic-icon-512.png

# ---- Image / registry ----
GH_OWNER          ?= 4rankng
IMAGE_NAME        ?= nhanluc-vfic-chatwoot
IMAGE             ?= ghcr.io/$(GH_OWNER)/$(IMAGE_NAME)
IMAGE_TAG         ?= latest-vfic

# ---- Deploy target (chat.tingting.vip) ----
VPS_HOST          ?= chat.tingting.vip
VPS_USER          ?= root
COMPOSE_DIR       ?= /opt/chatwoot
COMPOSE_FILE      ?= docker-compose.yml
SSH               ?= ssh -o ServerAliveInterval=30 $(VPS_USER)@$(VPS_HOST)
# buildx builder that supports linux/amd64 cross-build on this arm64 Mac.
BUILDER           ?= bb

CHATWOOT_DIR      := chatwoot

# Files touched by branding (used by brand-revert / brand-status).
BRAND_FILES       := $(shell cd $(CHATWOOT_DIR) && git ls-files \
		app/javascript/dashboard/i18n/locale/en \
		config/locales/en.yml \
		app/javascript/widget/i18n/locale/en.json \
		app/javascript/widget/i18n/locale/vi.json \
		app/views/super_admin/devise/sessions/new.html.erb \
		app/views/super_admin/application/_navigation.html.erb \
		app/views/installation/onboarding/index.html.erb \
		app/javascript/dashboard/components-next/year-in-review/ShareModal.vue \
		public/manifest.json \
		app/views/mailers/administrator_notifications/account_notification_mailer 2>/dev/null)

.PHONY: help brand-apply brand-revert brand-status build deploy deploy-pull restart smoke db-target install-deploy-config

help: ## Show this help
	@printf "Nhân lực VFIC Chatwoot — targets (centralized brand: '%s', logos: %s / %s, icon: %s)\n\n" "$(BRAND_NAME)" "$(LOGO_LIGHT)" "$(LOGO_DARK)" "$(LOGO_THUMBNAIL)"
	@printf "  \033[36m%-22s\033[0m %s\n" "brand-apply" "Bake BRAND_NAME into static files (idempotent)"
	@printf "  \033[36m%-22s\033[0m %s\n" "brand-revert" "Restore upstream Chatwoot defaults on branding files"
	@printf "  \033[36m%-22s\033[0m %s\n" "brand-status" "Show residual user-visible 'Chatwoot' strings"
	@printf "  \033[36m%-22s\033[0m %s\n" "build" "Trigger GHCR build (git push) or local docker build"
	@printf "  \033[36m%-22s\033[0m %s\n" "deploy" "Deploy branded image to $(VPS_HOST) (pull + restart + smoke)"
	@printf "  \033[36m%-22s\033[0m %s\n" "deploy-pull" "Pull image on VPS only (no restart)"
	@printf "  \033[36m%-22s\033[0m %s\n" "install-deploy-config" "Set InstallationConfig brand rows on the live DB"
	@printf "  \033[36m%-22s\033[0m %s\n" "smoke" "Post-deploy smoke check (unauthenticated subset)"
	@printf "  \033[36m%-22s\033[0m %s\n" "db-target" "Print the live DATABASE_URL target (Phase 0a)"

# -----------------------------------------------------------------------------
# Branding — the centralized BRAND_NAME is applied to static surfaces here.
# -----------------------------------------------------------------------------
brand-apply: ## Bake BRAND_NAME into Chatwoot static files (idempotent)
	BRAND_NAME='$(BRAND_NAME)' SUPPORT_EMAIL='$(SUPPORT_EMAIL)' \
	BRAND_URL='$(BRAND_URL)' LOGO_LIGHT='$(LOGO_LIGHT)' LOGO_DARK='$(LOGO_DARK)' LOGO_THUMBNAIL='$(LOGO_THUMBNAIL)' \
	bash scripts/brand-apply.sh

brand-revert: ## Restore upstream Chatwoot defaults on branding files (clean rebase)
	cd $(CHATWOOT_DIR) && git checkout -- \
		app/javascript/dashboard/i18n/locale/en \
		config/locales/en.yml \
		app/javascript/widget/i18n/locale/en.json \
		app/javascript/widget/i18n/locale/vi.json \
		app/views/super_admin/devise/sessions/new.html.erb \
		app/views/super_admin/application/_navigation.html.erb \
		app/views/installation/onboarding/index.html.erb \
		app/javascript/dashboard/components-next/year-in-review/ShareModal.vue \
		public/manifest.json \
		app/views/mailers/administrator_notifications/account_notification_mailer

brand-status: ## Show any residual user-visible 'Chatwoot' brand strings (allowlisted identifiers OK)
	@cd $(CHATWOOT_DIR) && echo "Residual user-visible 'Chatwoot' (should be empty modulo identifiers/URLs):" && \
	grep -rni 'chatwoot' \
		app/javascript/dashboard/i18n/locale/en/ \
		config/locales/en.yml \
		app/javascript/widget/i18n/locale/en.json \
		app/javascript/widget/i18n/locale/vi.json \
		app/views/super_admin/devise/sessions/new.html.erb \
		app/views/super_admin/application/_navigation.html.erb \
		app/views/installation/onboarding/index.html.erb \
		app/javascript/dashboard/components-next/year-in-review/ShareModal.vue \
		public/manifest.json \
		app/views/mailers/administrator_notifications/account_notification_mailer/ 2>/dev/null \
		| grep -vE '(chatwootConfig|chatwootWebChannel|chatwootPubsubToken|chatwootSettings|chatwootSDK|\$$chatwoot|chatwoot:ready|chatwoot:error|@chatwoot/|module Chatwoot|_chatwoot_session|ChatwootApp|Chatwoot\.config|Chatwoot::|chatwoot\.help|chatwoot\.com|latestChatwootVersion)' \
		|| echo "  (clean — no user-visible 'Chatwoot' residuals)"

# -----------------------------------------------------------------------------
# Build — the image is built OFF-VPS (the 2GB VPS cannot build it:
# chatwoot/docker/Dockerfile pins NODE_OPTIONS=--max-old-space-size=4096).
# Primary path: GitHub Actions on push under chatwoot/** -> GHCR.
# -----------------------------------------------------------------------------
build: ## Build the linux/amd64 image locally and load into docker (off-VPS cross-build via QEMU)
	@echo "==> Building linux/amd64 image $(IMAGE):$(IMAGE_TAG) (builder=$(BUILDER))"
	docker buildx build --platform linux/amd64 --builder $(BUILDER) \
		-f $(CHATWOOT_DIR)/docker/Dockerfile \
		--build-arg RAILS_ENV=production \
		--build-arg EXECJS_RUNTIME=Disabled \
		--build-arg BUNDLE_WITHOUT=development:test \
		-t $(IMAGE):$(IMAGE_TAG) --load $(CHATWOOT_DIR)/

# -----------------------------------------------------------------------------
# Deploy to chat.tingting.vip
# =============================================================================
# Order: brand-apply -> (image already built & pushed to GHCR) -> pull on VPS ->
#        pin image tag -> restart WITHOUT wiping volumes -> smoke check.
# !!! NEVER run `docker compose down -v` — it wipes the Redis volume, clears the
#     CHATWOOT_INSTALLATION_ONBOARDING key, and locks ALL recruiters out.
#     Recovery: see .omc/runbooks/HANDOFF_vps_steps.md -> "Recovery".
deploy: brand-apply build ## Build amd64 -> ship over SSH -> restart -> smoke (NO registry / NO GH Actions)
	@echo "==> [1/4] Shipping $(IMAGE):$(IMAGE_TAG) to $(VPS_HOST) via docker save | ssh load"
	docker save $(IMAGE):$(IMAGE_TAG) | gzip | $(SSH) "gunzip | docker load"
	@echo "==> [2/4] Pinning image in $(COMPOSE_FILE) on VPS (rails + sidekiq; redis untouched)"
	$(SSH) "cd $(COMPOSE_DIR) && \
		sed -i 's|image:.*chatwoot.*|image: $(IMAGE):$(IMAGE_TAG)|' $(COMPOSE_FILE) && \
		grep -n 'image:' $(COMPOSE_FILE)"
	@echo "==> [3/4] Rolling restart (brief 502 window). NEVER down -v (wipes Redis -> lockout)."
	$(SSH) "cd $(COMPOSE_DIR) && docker compose -f $(COMPOSE_FILE) up -d"
	@echo "==> [4/4] Smoke check"
	@$(MAKE) --no-print-directory smoke

deploy-pull: ## Only pull the image on the VPS (no restart) — dry-run helper
	$(SSH) "docker pull $(IMAGE):$(IMAGE_TAG) && docker image ls $(IMAGE)"

# Apply runtime brand config (InstallationConfig rows) on the live DB via the
# Rails console on the VPS. Idempotent (upserts). Run once after first deploy.
install-deploy-config: ## Set InstallationConfig brand rows on the live chatwoot DB
	$(SSH) "cd $(COMPOSE_DIR) && docker compose -f $(COMPOSE_FILE) exec -T rails bundle exec rails runner \"
		brand = '$(BRAND_NAME)'; \
		cfg = { 'BRAND_NAME' => brand, 'BRAND_URL' => '$(BRAND_URL)', \
		        'WIDGET_BRAND_URL' => '$(BRAND_URL)', 'INSTALLATION_NAME' => brand, \
		        'LOGO' => '$(LOGO_LIGHT)', 'LOGO_DARK' => '$(LOGO_DARK)', \
		        'LOGO_THUMBNAIL' => '$(LOGO_THUMBNAIL)', 'DISPLAY_MANIFEST' => 'true', \
		        'TERMS_URL' => '$(BRAND_URL)/terms', 'PRIVACY_URL' => '$(BRAND_URL)/privacy' }; \
		cfg.each { |k,v| ::InstallationConfig.find_or_create_by!(name: k).update!(value: v) }; \
		puts 'InstallationConfig updated:'; cfg.each { |k,v| puts \"  #{k} = #{v}\" }
	\""

# -----------------------------------------------------------------------------
# Smoke checks (see .omc/runbooks/HANDOFF_vps_steps.md for the full checklist).
# The authenticated dashboard probe needs a recruiter cookie — run manually.
# -----------------------------------------------------------------------------
smoke: ## Post-deploy smoke check (unauthenticated subset)
	@echo "-- curl /app/login (expect 200) --"
	@curl -sI https://$(VPS_HOST)/app/login | head -1 || true
	@echo "-- ENABLE_ACCOUNT_SIGNUP (expect \"false\") --"
	-$(SSH) "cd $(COMPOSE_DIR) && docker compose -f $(COMPOSE_FILE) exec -T rails bundle exec rails runner 'puts GlobalConfig.get(\"ENABLE_ACCOUNT_SIGNUP\").inspect'"
	@echo "-- onboarding key (expect nil) --"
	-$(SSH) "cd $(COMPOSE_DIR) && docker compose -f $(COMPOSE_FILE) exec -T rails bundle exec rails runner 'puts Redis::Alfred.get(Redis::Alfred::CHATWOOT_INSTALLATION_ONBOARDING).inspect'"
	@echo "  (also run manually: authenticated dashboard probe must be 200, not 302 -> /installation/onboarding)"

# Confirm which DB the live install uses (Phase 0a) — Supabase pooler expected.
db-target: ## Print the live DATABASE_URL target (Phase 0a check)
	-$(SSH) "cd $(COMPOSE_DIR) && docker compose -f $(COMPOSE_FILE) exec -T rails bundle exec rails runner 'puts ActiveRecord::Base.connection_db_config.url.sub(/:[^:@]+@/, :REDACTED@)'"
