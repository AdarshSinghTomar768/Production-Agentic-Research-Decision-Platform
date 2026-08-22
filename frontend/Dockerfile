# syntax=docker/dockerfile:1

# ---------- builder ----------
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci
COPY . .
# Baked into the static bundle; the SPA sends it as X-API-Key.
ARG VITE_API_KEY=dev-key-change-me
ENV VITE_API_KEY=$VITE_API_KEY
RUN npm run build

# ---------- runtime ----------
# Unprivileged nginx: runs as uid 101, listens on 8080.
FROM nginxinc/nginx-unprivileged:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
# The entrypoint renders templates/*.template with envsubst, so the API
# upstream is configurable per platform (compose: "api", Railway:
# "api.railway.internal"). Only uppercase env vars are substituted; nginx's
# own $host/$uri survive untouched.
COPY default.conf.template /etc/nginx/templates/default.conf.template
ENV API_UPSTREAM=api
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
