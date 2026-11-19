import os

import pytest


def pytest_configure(config):
    if not os.getenv("FAIRY_TEST_POSTGRES_URL"):
        raise pytest.UsageError(
            "FAIRY_TEST_POSTGRES_URL must point to a disposable PostgreSQL database"
        )


@pytest.fixture(scope="session", autouse=True)
def cleanup_postgres_schemas():
    yield
    from tests.db import cleanup_schemas

    cleanup_schemas()


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    # Unit tests must never call the operator's real local/cloud model or credential store.
    monkeypatch.setenv("FAIRY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAIRY_OLLAMA_MODEL", "")
    monkeypatch.setenv("FAIRY_EMBEDDING_MODEL", "")
    for name in ("FAIRY_CLOUD_BASE_URL", "FAIRY_CLOUD_MODEL", "FAIRY_CLOUD_API_KEY"):
        monkeypatch.delenv(name, raising=False)
