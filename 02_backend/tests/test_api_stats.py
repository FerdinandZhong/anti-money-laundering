import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    """TestClient wired to a temp ops DB via FastAPI dependency override, and a
    stubbed source layer so the test never touches Impala or data/raw CSVs."""
    from api import main as api_main
    from common.db import get_connection

    monkeypatch.setattr(api_main.source, "count_suspicious", lambda: 42)
    monkeypatch.setattr(api_main.source, "count_transactions", lambda: 1000)

    def _override_get_db():
        conn = get_connection()
        try:
            yield conn
        finally:
            conn.close()

    api_main.app.dependency_overrides[api_main.get_db] = _override_get_db
    yield TestClient(api_main.app)
    api_main.app.dependency_overrides.clear()


def test_stats_shape_and_keys(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "total_alerts", "open_alerts", "critical_alerts", "total_cases",
        "total_annotations", "suspicious_labelled", "human_labelled", "total_labelled",
    }
    for key in body:
        assert isinstance(body[key], int), f"{key} should be int, got {type(body[key])}"


def test_stats_reflects_source_layer_counts(client):
    resp = client.get("/api/stats")
    body = resp.json()
    assert body["suspicious_labelled"] == 42
    assert body["total_labelled"] == 1000


def test_stats_on_empty_db_is_all_zero_counts(client):
    resp = client.get("/api/stats")
    body = resp.json()
    assert body["total_alerts"] == 0
    assert body["total_cases"] == 0
    assert body["total_annotations"] == 0
    assert body["human_labelled"] == 0
