# VFIC CRM frontend — build the react-admin bundle, serve as static via nginx.
# Caddy (edge) reverse-proxies non-API paths here; /api, /webhooks, /realtime go
# to the `web` (FastAPI) service. apiBaseUrl defaults to same-origin (empty), so
# the bundle needs no deploy-time env injection.
FROM node:22-alpine AS build
WORKDIR /app
ENV CI=1
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
