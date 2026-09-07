import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    from api import main as api_main
    from common.db import get_connection

    def _override_get_db():
        conn = get_connection()
        try:
            yield conn
        finally:
            conn.close()

    api_main.app.dependency_overrides[api_main.get_db] = _override_get_db
    yield api_main, TestClient(api_main.app)
    api_main.app.dependency_overrides.clear()


def test_environment_shape(client, monkeypatch):
    api_main, test_client = client
    monkeypatch.setattr(api_main.source, "backend", lambda: "csv")
    monkeypatch.setattr(api_main.llm_client, "probe", lambda base_url, model, api_key: (True, "OK"))

    resp = test_client.get("/api/health/environment")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"source_backend", "source_ok", "active_model", "champion_artifact_present"}
    assert body["source_backend"] == "csv"
    assert body["source_ok"] is True
    assert set(body["active_model"].keys()) == {"alias", "reachable", "message"}
    assert body["active_model"]["reachable"] is True
    assert isinstance(body["champion_artifact_present"], bool)


def test_environment_reports_impala_forced_unreachable(client, monkeypatch):
    api_main, test_client = client

    def _boom():
        raise RuntimeError("source.backend=impala but Impala is unreachable")

    monkeypatch.setattr(api_main.source, "backend", _boom)
    monkeypatch.setattr(api_main.llm_client, "probe", lambda base_url, model, api_key: (False, "unreachable"))

    resp = test_client.get("/api/health/environment")
    body = resp.json()
    assert body["source_backend"] == "csv"
    assert body["source_ok"] is False
    assert body["active_model"]["reachable"] is False


def test_environment_champion_artifact_present_reflects_disk_state(client, monkeypatch, tmp_path):
    """CHAMPION row pointing at a version with no on-disk artifact ->
    champion_artifact_present False; write the file -> True."""
    api_main, test_client = client
    monkeypatch.setattr(api_main.source, "backend", lambda: "csv")
    monkeypatch.setattr(api_main.llm_client, "probe", lambda base_url, model, api_key: (True, "OK"))

    from common.db import get_connection
    conn = get_connection()
    conn.execute(
        "INSERT INTO deployments (deployment_id, model_version, status) VALUES (?, ?, 'CHAMPION')",
        ("DEPLOY-TEST", "vTEST123"),
    )
    conn.commit()
    conn.close()

    import common.config as config_mod
    orig_get_config = config_mod.get_config
    cfg = orig_get_config()
    monkeypatch.setitem(cfg, "model", {**cfg["model"], "model_dir": str(tmp_path)})
    monkeypatch.setattr(api_main, "PROJECT_ROOT", "")  # tmp_path is already absolute

    resp = test_client.get("/api/health/environment")
    assert resp.json()["champion_artifact_present"] is False

    (tmp_path / "aml_model_vTEST123.json").write_text("{}")
    resp = test_client.get("/api/health/environment")
    assert resp.json()["champion_artifact_present"] is True
