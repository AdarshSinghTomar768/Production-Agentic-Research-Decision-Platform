# Production Agentic Research & Decision Platform

Not another chatbot. A production-grade **multi-agent research pipeline** that turns a business
question into an evidence-cited decision memo — planned, researched in parallel, judged by an
LLM critic, gated behind human approval, and fully instrumented down to tokens and cents.

```
                 POST /v1/missions
                        │
                        ▼
                  GUARDRAIL ──► 422 on prompt injection
                        │
                  PLANNER AGENT          ResearchPlan (Pydantic)
                        │ (fan-out)
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   WEB AGENT       RAG AGENT        DATA AGENT
   (Tavily)        (Qdrant)         (HTTP APIs)
        │               │                │
        └──── evidence pool [ev-web-### | ev-rag-### | ev-data-###] ───┘
                                 │
                                 ▼
                          SYNTHESIZER ◄── critique feedback (≤ N revisions)
                                 │
                                 ▼
                          CRITIC / JUDGE ── FAIL ──► back to synthesizer
                                 │ PASS (threshold enforced in code)
                                 ▼
                    ⏸ interrupt() — durable pause in Postgres
                                 │
                   POST /v1/missions/{id}/decision
                     approved=true        approved=false (+feedback)
                        │                       │
                        ▼                       ▼
                    FINALIZE ◄────────── back to synthesizer
                        │
              cited FinalReport + full telemetry
```

## Stack

| Concern | Choice |
|---|---|
| Orchestration | LangGraph 1.x — fan-out/join, conditional revise-loop, `interrupt()` HITL |
| Durability | Postgres checkpointer → approval pauses survive restarts |
| LLM access | LiteLLM (`gemini/gemini-3.6-flash` default free tier; `groq/`, `openai/`, `ollama/` = env-only switch) |
| Embeddings | LiteLLM → `gemini/gemini-embedding-001` (3072-dim); deterministic hash fake for offline |
| Structured outputs | Pydantic v2 schemas + JSON-extraction & validation-repair retry loop (provider-agnostic) |
| Web research | Tavily API |
| RAG | Qdrant + LiteLLM embeddings, paragraph-aware chunker |
| Judge | LLM-as-a-judge over 5-dimension rubric; **pass/fail decided in code**, not by the model |
| Guardrails | Prompt-injection screening (input); citation verification strips phantom `[ev-*]` refs (output) |
| API | FastAPI, async SQLAlchemy, X-API-Key auth, background mission runner |
| Observability | Per-call token/cost/latency rows, per-node wall time, `/stats` scoreboard, printable eval tables |
| Evals | Golden-set suite with rubric scoring + pass-rate metrics |
| Testing | 33 backend tests, zero keys: deterministic FakeProvider, offline tools, MemorySaver |
| Web UI | React 19 + Vite + TypeScript, Tailwind v4; mission launcher, approval gate, report viewer, knowledge search, eval runner |
| Infra | Docker multi-stage ×2 (API + nginx-served UI), Compose (Postgres+Qdrant+API+Web), GitHub Actions |

## Quickstart A — zero-key demo (offline mode)

```bash
cp .env.example .env            # FAKE_LLM=true already default-safe
make install
make up                         # postgres + qdrant + api :8000 + web UI :8080
make seed                       # sample knowledge base into Qdrant
```

Open **http://localhost:8080** — dashboard, mission launcher, approval gate, reports.
Same flow via API:

```bash
curl -s -X POST localhost:8000/v1/missions \
  -H "X-API-Key: dev-key-change-me" -H "Content-Type: application/json" \
  -d '{"question":"Is Acme Corp a good target for an AI services campaign?"}'
```

## Quickstart B — real models (free tier)

Put in `.env`: `GEMINI_API_KEY=...` ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)),
optionally `TAVILY_API_KEY=...`. Then `docker compose up -d --build` (model names bake into the
UI bundle at build time). Everything else identical. Groq/OpenAI/Ollama: change `MODEL=` /
`JUDGE_MODEL=` only.

> Free-tier note: Gemini allows ~20 requests/day per model — one real mission uses ~5+ calls,
> a full real eval suite needs ~25+. Use fake mode (`--fake` / UI checkbox) for demos; quota
> resets daily.

## Web UI

A thin control plane over the same API — no business logic lives client-side:

- **Dashboard** — platform scoreboard (missions, completion rate, avg judge score, spend, node latency) + mission launcher with validation + recent-missions list
- **Mission detail** — live status polling, human-review panel with approve / reject-with-feedback, plan JSON, final report with citations & confidence, per-node usage/cost table
- **Knowledge** — semantic search over Qdrant + document ingest
- **Evals** — golden-set runner with per-case pass/fail and failure notes

Stack: React 19 · Vite · TypeScript · Tailwind v4 · React Router · Vitest + Testing Library
(32 component/API-client tests). Dev mode proxies `/api → localhost:8000`; production is an
nginx container that serves static assets and reverse-proxies `/api` to the `api` service.
The SPA authenticates with the same `X-API-Key` header (baked from `VITE_API_KEY` at build).

## The human-approval loop

```bash
MID=<mission_id from create>

curl -s localhost:8000/v1/missions/$MID -H "X-API-Key: $KEY"           # status
curl -s localhost:8000/v1/missions/$MID/review -H "X-API-Key: $KEY"    # draft + judge scores
curl -s -X POST localhost:8000/v1/missions/$MID/decision \
     -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"approved":false,"feedback":"Add pricing strategy."}'        # reject -> revise loop
curl -s localhost:8000/v1/missions/$MID/report -H "X-API-Key: $KEY"    # after approval
curl -s localhost:8000/v1/missions/$MID/usage -H "X-API-Key: $KEY"     # tokens/cost/latency
curl -s localhost:8000/v1/missions/stats      -H "X-API-Key: $KEY"     # platform scoreboard
```

Interactive docs: http://localhost:8000/docs

## Evaluation suite

```bash
uv run python scripts/run_evals.py --fake     # offline; drop --fake for real models
```

Sample output (offline mode):

```
==========================================================================
                          EVALUATION RUN SUMMARY
==========================================================================
case               overall  pass  rev  evd llmcalls     cost$
--------------------------------------------------------------------------
case-acme-target      8.00  PASS    0    4        3    0.0000
...
mean_overall=8.0  pass_rate=1.0
tokens(in/out)=3465/1536  llm_cost=$0.0000  total_wall_ms=14  fake_llm=True
```

Artifacts land in `artifacts/eval-*.json`; runs persist to the `eval_runs` table when a DB is configured.

## Where the numbers live

| Metric | Source |
|---|---|
| Tokens & cost per LLM call | `usage_events` table ← every provider call |
| Wall-clock latency per agent node | `agent_runs` table ← graph telemetry reducer |
| Revision counts, judge score history | `missions.verdict_history_json` |
| Mission rollup | `GET /v1/missions/{id}/usage` |
| Global scoreboard (completion rate, avg judge score, avg node latency, total spend) | `GET /v1/missions/stats` |
| Eval pass-rate & rubric means | eval harness table + `eval_runs` |

## Project layout

```
app/
  agents/        planner · researcher(web/rag) · data_agent · synthesizer · critic
  graph/         state contract · builder (nodes+routing) · orchestrator (start/resume)
  llm/           litellm provider + repair loop · guardrails · usage accounting
  tools/         tavily · qdrant retriever · allowlisted http tool
  ingestion/     chunk → embed → upsert pipeline
  schemas/       all Pydantic contracts (plan/evidence/draft/verdict/report/API)
  db/            async engine · missions/agent_runs/usage_events/eval_runs models
  api/routes/    missions · knowledge · evals · health (+ fake-LLM eval override)
  evals/         golden_set.jsonl · harness + metrics rendering
frontend/        React/Vite UI · nginx runtime container · Vitest suites
scripts/         seed_knowledge_base.py · run_evals.py
tests/           e2e graph flows, guardrails, schemas, chunker, full API lifecycle
```

## Key design decisions

- **Judge advises, code decides** — model scores feed a deterministic policy
  (`CriticAgent._enforce_policy`): threshold + dimension floor + citation validity.
- **Citations are enforced twice**: output guardrail strips phantom ids;
  the critic re-checks before any verdict can pass.
- **Provider-agnostic structured outputs**: JSON extraction + schema-guided repair
  retries work on Gemini/Groq/Ollama alike — no native JSON-mode dependency.
- **Durable HITL**: approval state machine lives in the Postgres checkpointer,
  so a pending mission survives deploys; resume is one POST.
- **Telemetry as a state reducer**: parallel branches append disjoint usage rows
  via LangGraph's add-reducer — nothing double-counted, nothing lost.

## Performance & resilience optimizations

- **Out-of-process mission workers**: `EXECUTION_MODE=workers` moves graph
  execution out of the API into `python -m app.worker` consumers backed by a
  Postgres job queue (`mission_jobs` table) — time-boxed leases, `FOR UPDATE
  SKIP LOCKED` claims, and an expired-lease sweep that recovers jobs from
  crashed workers. Scale horizontally: `docker compose up -d --scale worker=N`.
- **Rate-limit-aware LLM routing**: `LLM_FALLBACK_MODELS` defines an ordered
  chain (e.g. `gemini/gemini-3.6-flash,groq/openai/gpt-oss-120b,...`). On 429s
  or transient errors the provider rotates models per attempt; backoff honors
  provider cooldown hints ("Please try again in 24.3s", Gemini `retryDelay`)
  because token buckets refill in wall-clock time even across different models,
  while non-quota blips (timeouts, resets) switch models instantly.
- **Prompt budgeting**: evidence bodies are capped (`PROMPT_EVIDENCE_MAX_CHARS`,
  full text stays in state/DB/UI), JSON payloads are compact, and revision
  passes send an id/title evidence index instead of re-sending every body —
  the synthesizer's largest call shrinks by ~40%. Combined with
  `MAX_COMPLETION_TOKENS`, requests stay under free-tier TPM ceilings
  (e.g. Groq's 8k tokens/min per model) so JSON outputs aren't truncated
  mid-object.
- **Checkpoint compression**: a zlib-wrapped LangGraph serializer shrinks
  persisted mission state ~3-5x for evidence-heavy graphs, cutting checkpointer
  I/O on every superstep; transparently reads legacy uncompressed blobs.
- **Tunable DB pool**: `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` size the async engine
  (Postgres only; SQLite dev paths skip pooling).

## Known trade-offs (deliberate)

- Missions default to `EXECUTION_MODE=inline` (background task in the API
  process — simplest for local dev; used by tests). Compose runs `workers`.
- Free-tier quota ceilings still apply: when Gemini's daily request cap is
  exhausted, missions ride the fallback chain (each model has its own bucket),
  but sustained load on free Groq tiers can still exhaust all buckets until
  windows refill. Upgrade a tier or add providers for heavy use.
- Schema init is `create_all`; migrations would be Alembic.
- Injection heuristics are a speed bump, not a fortress — real defense is schema-constrained agents + citation grounding.

## Commands

See `Makefile` / `AGENTS.md`: `make install · up · seed · test · lint · evals · dev`.
Frontend: `cd frontend && npm install && npm run dev` (or `npm test` for the Vitest suite).
