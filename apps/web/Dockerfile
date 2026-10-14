# syntax=docker/dockerfile:1

# --------------------------------------------------------------------------- #
#  builder — installs the npm workspace and produces the static bundle.
# --------------------------------------------------------------------------- #
FROM node:24-alpine AS builder

ARG NPM_REGISTRY=https://registry.npmjs.org

WORKDIR /app

# Manifests first: `npm ci` is cached until a dependency actually changes.
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
RUN npm ci --registry "$NPM_REGISTRY"

COPY apps/web apps/web
RUN npm run build --workspace @line-rca/web

# --------------------------------------------------------------------------- #
#  runtime — nginx serves the bundle and reverse-proxies the API, so the browser
#  stays on a single origin and the SSE stream needs no CORS handling.
#
#  The unprivileged variant is used so the container does not run as root: it listens
#  on 8080 as a non-root user, which is also why the template below binds 8080.
# --------------------------------------------------------------------------- #
FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime

# The official image runs envsubst over /etc/nginx/templates/*.template, which is how the
# upstream stays configurable without shipping a machine-specific config. Only ${API_UPSTREAM}
# is substituted; nginx's own $variables are untouched.
ENV API_UPSTREAM=http://api:8000

COPY apps/web/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/apps/web/dist /usr/share/nginx/html

EXPOSE 8080
