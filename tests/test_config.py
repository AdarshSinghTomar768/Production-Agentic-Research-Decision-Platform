"""Config portability: PaaS-style DATABASE_URL scheme normalization."""

from app.config import Settings


def test_plain_postgres_url_gets_asyncpg_driver():
    s = Settings(database_url="postgres://u:p@host:5432/dbname")
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/dbname"


def test_postgresql_url_normalized_too():
    s = Settings(database_url="postgresql://u:p@host:5432/dbname")
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/dbname"


def test_driver_tagged_url_untouched():
    url = "postgresql+asyncpg://platform:platform@localhost:5433/platform"
    assert Settings(database_url=url).database_url == url


def test_sqlite_url_untouched():
    url = "sqlite+aiosqlite:///./dev.db"
    assert Settings(database_url=url).database_url == url
