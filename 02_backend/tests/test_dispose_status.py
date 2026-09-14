from datetime import datetime, timezone
from fastapi.testclient import TestClient


def _seed(conn):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO customers (customer_id, name) VALUES ('CUST-1','Test')")
    conn.execute("INSERT INTO accounts (account_id, customer_id) VALUES ('ACC-1','CUST-1')")
    conn.execute(
        "INSERT INTO alerts (alert_id, customer_id, account_id, risk_score, risk_band, status, created_at) "
        "VALUES ('ALERT-1','CUST-1','ACC-1',0.9,'CRITICAL','OPEN',?)", (now,))
    conn.execute(
        "INSERT INTO cases (case_id, alert_id, customer_id, state, priority, created_at, updated_at) "
        "VALUES ('CASE-1','ALERT-1','CUST-1','ALERT_CREATED','CRITICAL',?,?)", (now, now))
    conn.commit()


def test_suspicious_moves_alert_to_proposed(tmp_db_path):
    from common.db import get_connection
    conn = get_connection(); _seed(conn)
    import api.main as main
    client = TestClient(main.app)
    r = client.post("/api/cases/CASE-1/dispose", json={"disposition": "SUSPICIOUS", "adjudicator": "jsmith"})
    assert r.status_code == 200
    status = get_connection().execute("SELECT status FROM alerts WHERE alert_id='ALERT-1'").fetchone()["status"]
    assert status == "PROPOSED"


def test_false_positive_closes_alert(tmp_db_path):
    from common.db import get_connection
    conn = get_connection(); _seed(conn)
    import api.main as main
    client = TestClient(main.app)
    client.post("/api/cases/CASE-1/dispose", json={"disposition": "FALSE_POSITIVE"})
    status = get_connection().execute("SELECT status FROM alerts WHERE alert_id='ALERT-1'").fetchone()["status"]
    assert status == "CLOSED"


def test_disposition_removes_same_snapshot_duplicate_from_open(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    _seed(conn)
    conn.execute(
        "INSERT INTO alerts (alert_id, customer_id, account_id, risk_score, risk_band, status, data_cutoff_at) "
        "VALUES ('ALERT-1-DUP','CUST-1','ACC-1',0.9,'CRITICAL','OPEN','2026-09-13T13:32:00')"
    )
    conn.execute("UPDATE alerts SET data_cutoff_at='2026-09-13T13:32:00' WHERE alert_id='ALERT-1'")
    conn.commit()
    import api.main as main
    client = TestClient(main.app)

    response = client.post("/api/cases/CASE-1/dispose", json={"disposition": "SUSPICIOUS"})
    assert response.status_code == 200
    statuses = [r["status"] for r in get_connection().execute(
        "SELECT status FROM alerts WHERE account_id='ACC-1' ORDER BY alert_id"
    ).fetchall()]
    assert statuses == ["PROPOSED", "PROPOSED"]
