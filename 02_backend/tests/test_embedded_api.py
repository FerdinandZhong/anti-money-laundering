import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_get_embedded_lists_both_servers(tmp_db_path):
    import api.main as main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    r = c.get("/api/config/embedded")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["servers"]}
    assert names == {"iceberg-mcp", "workbench-mcp"}
    ice = next(s for s in r.json()["servers"] if s["name"] == "iceberg-mcp")
    assert ice["configured"] is False


def test_put_then_get_masks_secrets(tmp_db_path):
    import api.main as main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    r = c.put("/api/config/embedded/iceberg-mcp", json={"enabled": True, "params": {
        "impala_host": "h", "impala_port": "443", "impala_user": "u",
        "impala_password": "secret", "impala_database": "db"}})
    assert r.status_code == 200
    ice = next(s for s in c.get("/api/config/embedded").json()["servers"]
               if s["name"] == "iceberg-mcp")
    assert ice["configured"] is True
    assert ice["params"]["impala_password"] == "•••"
    assert ice["params"]["impala_host"] == "h"


def test_put_masked_secret_keeps_stored_value(tmp_db_path):
    import api.main as main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    c.put("/api/config/embedded/iceberg-mcp", json={"enabled": True, "params": {
        "impala_host": "h", "impala_user": "u",
        "impala_password": "secret", "impala_database": "db"}})
    # resubmit with the mask — password must survive
    c.put("/api/config/embedded/iceberg-mcp", json={"enabled": True, "params": {
        "impala_host": "h2", "impala_user": "u",
        "impala_password": "•••", "impala_database": "db"}})
    from common.db import get_connection
    conn = get_connection()
    row = conn.execute("SELECT params FROM tool_config WHERE name='iceberg-mcp'").fetchone()
    conn.close()
    stored = json.loads(row["params"])
    assert stored["impala_password"] == "secret"
    assert stored["impala_host"] == "h2"


def test_put_unknown_server_404(tmp_db_path):
    import api.main as main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    assert c.put("/api/config/embedded/nope", json={"params": {}}).status_code == 404


def test_test_endpoint_uses_probe(tmp_db_path, monkeypatch):
    import api.main as main
    from fastapi.testclient import TestClient
    from common import mcp_client
    monkeypatch.setattr(mcp_client, "probe_embedded",
                        lambda name, params: (True, [{"name": "execute_query"}]))
    c = TestClient(main.app)
    r = c.post("/api/config/embedded/iceberg-mcp/test", json={"params": {
        "impala_host": "h", "impala_user": "u",
        "impala_password": "p", "impala_database": "db"}})
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["count"] == 1
