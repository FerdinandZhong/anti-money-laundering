"""Tests for the customer-centric agent/MCP endpoints in api/main.py."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def _seed(conn):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO customers (customer_id, name) VALUES ('CUST-1','Test')")
    conn.execute("INSERT INTO accounts (account_id, customer_id) VALUES ('ACC-1','CUST-1')")
    conn.execute(
        "INSERT INTO alerts (alert_id, customer_id, account_id, risk_score, risk_band, status, created_at) "
        "VALUES ('ALERT-1','CUST-1','ACC-1',0.9,'CRITICAL','OPEN',?)", (now,))
    conn.commit()


def _client():
    import api.main as main
    return TestClient(main.app)


def test_suspicious_true_and_false(tmp_db_path):
    from common.db import get_connection
    _seed(get_connection())
    c = _client()
    r = c.get("/api/customers/CUST-1/suspicious").json()
    assert r["suspicious"] is True and r["highest_risk_score"] == 0.9
    assert c.get("/api/customers/NOBODY/suspicious").json()["suspicious"] is False


def test_case_status_read_only_no_case_creation(tmp_db_path):
    from common.db import get_connection
    _seed(get_connection())
    r = _client().get("/api/customers/CUST-1/case-status").json()
    assert r["processed"] is False
    # the read must not have created a case
    assert get_connection().execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


def test_case_status_processed(tmp_db_path):
    from common.db import get_connection
    conn = get_connection(); _seed(conn)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO cases (case_id, alert_id, customer_id, state, disposition, created_at, updated_at) "
        "VALUES ('CASE-1','ALERT-1','CUST-1','CLOSED','SUSPICIOUS',?,?)", (now, now))
    conn.execute("INSERT INTO annotations (annotation_id, case_id, disposition, adjudicator) "
                 "VALUES ('ANN-1','CASE-1','SUSPICIOUS','jsmith')")
    conn.commit()
    r = _client().get("/api/customers/CUST-1/case-status").json()
    assert r["processed"] is True and r["disposition"] == "SUSPICIOUS"
    assert r["annotations"][0]["adjudicator"] == "jsmith"


def test_transactions_sorted_desc(tmp_db_path, monkeypatch):
    from common.db import get_connection
    conn = get_connection(); _seed(conn)
    for tid, sc in (("T1", 0.2), ("T2", 0.95), ("T3", 0.5)):
        conn.execute("INSERT INTO transaction_scores (transaction_id, score) VALUES (?,?)", (tid, sc))
    conn.commit()
    import api.main as main
    monkeypatch.setattr(main.source, "customer_transactions",
                        lambda cid, limit=20: [{"transaction_id": t} for t in ("T1", "T2", "T3", "T4")])
    r = TestClient(main.app).get("/api/customers/CUST-1/transactions").json()
    assert [t["transaction_id"] for t in r["transactions"]] == ["T2", "T3", "T1", "T4"]


def test_investigate_is_only_writer(tmp_db_path, monkeypatch):
    from common.db import get_connection
    _seed(get_connection())
    import api.main as main
    monkeypatch.setattr(main.source, "get_accounts", lambda cid: [{"account_id": "ACC-1"}])
    monkeypatch.setattr(main, "run_investigation", lambda *a, **k: iter([
        {"type": "worker_done", "worker": "profile", "findings": "clean"},
        {"type": "token", "text": "Overall LOW risk."},
    ]))
    r = TestClient(main.app).post("/api/customers/CUST-1/investigate").json()
    assert r["case_id"] == "CASE-1" and "Overall LOW risk." in r["analysis"]
    row = get_connection().execute("SELECT analysis, analyzed_at FROM cases WHERE case_id='CASE-1'").fetchone()
    assert row["analysis"] and row["analyzed_at"]


def test_swagger_reachable_under_api(tmp_db_path):
    c = _client()
    assert c.get("/api/openapi.json").status_code == 200
    assert c.get("/api/docs").status_code == 200
