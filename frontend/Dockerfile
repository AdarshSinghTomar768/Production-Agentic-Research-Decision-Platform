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
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
