# AGENTS.md

Guidance for AI coding agents working in this repository.

## Commands

| Task | Command |
|---|---|
| Install | `uv sync --all-groups` |
| Run all tests | `uv run pytest -q` |
| Lint | `uv run ruff check app tests scripts` |
| Format/fix | `uv run ruff format . && uv run ruff check --fix app tests scripts` |
| Full stack (Postgres+Qdrant+API) | `docker compose up -d --build` → http://localhost:8000/docs |
| Local API dev server | `uv run uvicorn app.main:app --reload --port 8000` |
| Seed knowledge base | `uv run python scripts/seed_knowledge_base.py` |
| Run eval suite | `uv run python scripts/run_evals.py --fake` |

## Hard rules

1. **Tests and CI must never touch real APIs or require API keys.** Use
   `FAKE_LLM=true` (deterministic `FakeProvider` + offline tools +
   `MemorySaver`). The judge fake supports a `<<FORCE_FAIL>>` control token.
2. **Every agent output is a Pydantic model** from `app/schemas`. Never parse
   LLM output ad hoc; extend the schema instead.
3. **Citations are policy, not convention**: reports may only cite
   `ev-{web|rag|data}-NNN` ids that exist in the evidence pool
   (`app/llm/guardrails.verify_citations`, enforced again by `critic.py`).
4. **Pass/fail is decided in code** (`CriticAgent._enforce_policy`), never by
   the judge model alone.
5. Run `ruff check` before declaring any task done; keep it green.

## Architecture map (where to change what)

- `app/graph/builder.py` — LangGraph wiring: nodes, fan-out, critic loop,
  `interrupt()`-based human approval. Routing policy lives here.
- `app/graph/state.py` — the `MissionState` contract. Telemetry keys use an
  add-reducer; parallel branches write disjoint evidence keys.
- `app/agents/*` — one file per agent; each returns `(schema_object, AgentUsage)`.
- `app/llm/provider.py` — LiteLLM wrapper with JSON-extraction + repair-retry;
  `FakeProvider` for offline mode.
- `app/db/models.py` — persistence (`missions`, `agent_runs`, `usage_events`,
  `eval_runs`). Usage/cost endpoints aggregate from these tables.
- `app/api/routes/` — FastAPI routers; mission dispatch lives in
  `routes/missions.py::_dispatch` — `EXECUTION_MODE=inline` runs the graph in a
  background task (default, used by tests), `workers` enqueues into the
  `mission_jobs` table for out-of-process workers.
- `app/queue.py` + `app/worker/main.py` — Postgres-backed job queue (lease +
  expired-lease requeue) and `python -m app.worker` consumers; scale with
  `docker compose up -d --scale worker=N` (SKIP LOCKED claims).
- `app/evals/harness.py` — golden-set runner + metrics rendering.

## Conventions

- Python 3.11, async everywhere at the I/O layer; no blocking calls in nodes.
- Model strings carry the provider (`gemini/gemini-2.5-flash`,
  `groq/...`, `ollama/...`) — provider switching is config-only.
- New env knobs go in `app/config.py` AND `.env.example`.
- Evidence ids: `make_evidence_id(source, seq)`; sequence restarts per agent.
