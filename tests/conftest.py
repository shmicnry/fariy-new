import pytest


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    # Unit tests must never call the operator's real local/cloud model or credential store.
    monkeypatch.setenv("FAIRY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAIRY_OLLAMA_MODEL", "")
    for name in ("FAIRY_CLOUD_BASE_URL", "FAIRY_CLOUD_MODEL", "FAIRY_CLOUD_API_KEY"):
        monkeypatch.delenv(name, raising=False)
