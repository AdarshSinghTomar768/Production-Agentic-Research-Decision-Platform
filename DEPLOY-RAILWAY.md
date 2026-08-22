# Deploying to Railway

The stack maps to **5 Railway services** built from this one repo:

| Service | Source | Start command | Notes |
|---|---|---|---|
| `postgres` | Railway database template | — | managed; injects `DATABASE_URL` |
| `qdrant` | Docker image `qdrant/qdrant` | image default | attach a volume at `/qdrant/storage` |
| `api` | repo root (Dockerfile) | default (`uvicorn`) | `EXECUTION_MODE=workers` |
| `worker` | repo root, same build as api | `python -m app.worker` | scale 1–N |
| `web` | `frontend/` (Dockerfile) | default (nginx) | public domain goes here |

> Cost: signup includes a one-time $5 trial credit; the Hobby plan is $5/mo
> including usage. This stack typically lands around that number.

## 1. One-time setup

```bash
npm i -g @railway/cli
railway login            # opens browser
railway init             # in the repo root; name it, link to your GitHub repo
```

Push this repo to GitHub first — Railway builds from it.

## 2. Create infrastructure services

```bash
railway add --database postgres          # service: Postgres
railway add --image qdrant/qdrant -v qdrant-storage:/qdrant/storage
```

In the dashboard, open **Qdrant → Settings → Volumes** and confirm the mount
point is `/qdrant/storage`.

## 3. Create app services

- **api**: Dashboard → *New Service → GitHub Repo* → select this repo.
  Root directory `/`, Railway auto-detects the Dockerfile. No start override.
- **worker**: same flow again, but set **Start Command** to `python -m app.worker`
  (Settings → Deploy → Custom Start Command).
- **web**: same flow, but set **Root Directory** to `/frontend`.
  Under Settings → Build, add build arg `VITE_API_KEY=<your API_KEY>` —
  it's baked into the static bundle at build time.

## 4. Variables

Set once under **Variables → Shared Variables**, then reference them from
api/worker/web:

```
GEMINI_API_KEY=...
GROQ_API_KEY=...
TAVILY_API_KEY=...
API_KEY=<long random string>          # client auth; must match VITE_API_KEY
MODEL=gemini/gemini-3.6-flash
JUDGE_MODEL=gemini/gemini-3.6-flash
EMBEDDING_MODEL=gemini/gemini-embedding-001
VECTOR_SIZE=3072
EXECUTION_MODE=workers
LLM_FALLBACK_MODELS=groq/openai/gpt-oss-120b,groq/qwen/qwen3.6-27b,groq/openai/gpt-oss-20b
MAX_COMPLETION_TOKENS=3072
MAX_REPAIR_RETRIES=3
```

Per-service variables:

| Service | Variable |
|---|---|
| api, worker | `DATABASE_URL = {{Postgres.DATABASE_URL}}` (reference), `QDRANT_URL = http://qdrant.railway.internal:6333`, `EXECUTION_MODE = workers` |
| web | `API_UPSTREAM = api.railway.internal` (nginx proxy target) |

The backend normalizes `postgres://…` URLs to asyncpg automatically
(`app/config.py::_asyncpg_scheme`).

## 5. Networking

- **web** → Settings → Networking → Generate Domain (port `8080`). This URL is
  your app: UI + API via the `/api/*` proxy. Same-origin, so no CORS config.
- **api** → optionally generate a domain on port `8000` for direct Swagger
  access (`/docs`).
- Leave postgres/qdrant private-only.

Deployments trigger automatically on every push to the linked branch.

## 6. Seed the knowledge base

The seed script writes directly to Postgres + Qdrant, so expose both briefly:

1. Qdrant → Settings → Networking → Generate Domain (TCP proxy 6333);
   Postgres → Settings → Networking → Public Networking on.
2. From your laptop:

```bash
DATABASE_URL="<postgres PUBLIC url>" \
QDRANT_URL="https://<qdrant-domain>" \
uv run python scripts/seed_knowledge_base.py
```

3. Turn public networking back off on both.

## 7. Verify

- `https://<web-domain>/` renders the UI
- `https://<web-domain>/api/healthz` returns `{"status":"ok"}`
- Launch a mission in the UI; worker logs should claim the job
  (`railway logs --service worker`).
