"""Shared fixtures. Environment must be pinned BEFORE app modules load."""

import os
import tempfile
from pathlib import Path

_TEST_DB = Path(tempfile.gettempdir()) / "platform_test.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()

os.environ.update(
    FAKE_LLM="true",
    API_KEY="test-key",
    DATABASE_URL=f"sqlite+aiosqlite:///{_TEST_DB}",
    LOG_LEVEL="WARNING",
)

import pytest  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from app.config import Settings  # noqa: E402
from app.graph.builder import Services, make_services  # noqa: E402
from app.graph.runner import MissionOrchestrator  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    return Settings(fake_llm=True)


@pytest.fixture
def services(settings: Settings) -> Services:
    return make_services(settings)


@pytest.fixture
def orchestrator(services: Services) -> MissionOrchestrator:
    return MissionOrchestrator(services, MemorySaver())


QUESTION = "Is Acme Corp a good target for an AI services campaign?"
