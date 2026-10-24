# VFIC CRM frontend — build the react-admin bundle, serve as static via nginx.
# Caddy (edge) reverse-proxies non-API paths here; /api, /webhooks, /realtime go
# to the `web` (FastAPI) service. apiBaseUrl defaults to same-origin (empty), so
# the bundle needs no deploy-time env injection.
FROM node:22-alpine AS build
WORKDIR /app
ENV CI=1
COPY package.json package-lock.json ./
# decode-uri-component resolves to the vendored CJS build via a `file:` override
# (CHAT-2); npm ci needs that directory on disk before installing.
COPY vendor ./vendor
RUN npm ci
# npm ci drops the file: override link for decode-uri-component (lock
# stub has no resolved version) — recreate it so rolldown can resolve
# query-string's import inside the image build. See CHAT-2 vendoring.
RUN rm -f node_modules/decode-uri-component && ln -s /app/vendor/decode-uri-component node_modules/decode-uri-component
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
