"""Central configuration. All knobs live in environment / .env (see .env.example)."""

import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Fields exported into process env on load — LiteLLM reads provider keys
# directly from the environment (GEMINI_API_KEY, OPENAI_API_KEY, ...).
_ENV_EXPORTS: dict[str, str] = {
    "gemini_api_key": "GEMINI_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "groq_api_key": "GROQ_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "ollama_api_base": "OLLAMA_API_BASE",
    "tavily_api_key": "TAVILY_API_KEY",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- App ---
    app_name: str = "Agentic Research & Decision Platform"
    environment: str = "development"
    api_key: str = "dev-key-change-me"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Execution ---
    # inline: missions run as background tasks inside the API process (dev/tests).
    # workers: API only enqueues; dedicated worker processes execute (scale-out).
    execution_mode: str = "inline"  # inline | workers

    # --- LLM ---
    fake_llm: bool = False  # deterministic offline provider (tests/CI)
    model: str = "gemini/gemini-2.5-flash"
    judge_model: str = "gemini/gemini-2.5-flash"
    # Fallbacks tried (in order) when the primary model hits rate limits /
    # transient provider errors. Comma-separated LiteLLM model strings;
    # empty -> single-model behavior.
    llm_fallback_models: str = ""
    llm_retry_backoff_seconds: float = 2.0  # exponential base between attempts
    # Evidence bodies are truncated to this many chars when rendered into LLM
    # prompts (synthesizer). Full text stays in state/DB/UI; this only keeps
    # prompt requests small enough for tight provider TPM budgets.
    prompt_evidence_max_chars: int = 500

    @property
    def fallback_model_list(self) -> list[str]:
        return [m.strip() for m in self.llm_fallback_models.split(",") if m.strip()]

    @field_validator("database_url", mode="after")
    @classmethod
    def _asyncpg_scheme(cls, url: str) -> str:
        """PaaS databases hand out postgres:// URLs; the async engine needs
        postgresql+asyncpg://. Leave driver-tagged or non-postgres URLs alone."""
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
    embedding_model: str = "gemini/text-embedding-004"
    temperature: float = 0.2
    max_completion_tokens: int = 4096
    llm_timeout_seconds: float = 90.0
    max_repair_retries: int = 2  # JSON validation repair attempts per call

    # --- Graph policy ---
    max_revisions: int = 2
    judge_pass_threshold: float = 7.0
    judge_dimension_floor: float = 5.0
    max_evidence_per_agent: int = 6

    # --- Provider keys ---
    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_api_base: str | None = None
    tavily_api_key: str | None = None

    # --- Infrastructure ---
    # Accepts plain postgres:// / postgresql:// URLs (Railway, Heroku, Render
    # hand those out) and normalizes them for the asyncpg driver.
    database_url: str = "postgresql+asyncpg://platform:platform@localhost:5433/platform"
    db_echo: bool = False
    db_pool_size: int = 10       # postgres only; sqlite ignores pool sizing
    db_max_overflow: int = 20
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "knowledge_base"
    vector_size: int = 768  # gemini/text-embedding-004=768, openai/text-embedding-3-small=1536

    # --- Mission queue (execution_mode=workers) ---
    job_lease_seconds: int = 900      # claim lease; expired leases are requeued
    worker_concurrency: int = 4       # jobs one worker process runs in parallel

    # --- Tool tuning ---
    web_results_per_query: int = 5
    rag_top_k: int = 5
    rag_score_threshold: float = 0.3
    http_tool_timeout_seconds: float = 15.0

    def model_post_init(self, __context) -> None:
        for field, env_name in _ENV_EXPORTS.items():
            value = getattr(self, field)
            if value:
                os.environ.setdefault(env_name, str(value))
        # Avoid a network fetch of the pricing map on every completion_cost call.
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

    @property
    def llm_configured(self) -> bool:
        """True if at least one real provider credential is present."""
        return any(
            (self.gemini_api_key, self.openai_api_key, self.groq_api_key,
             self.anthropic_api_key, self.ollama_api_base)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
