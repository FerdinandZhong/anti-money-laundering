from fastapi.testclient import TestClient


def test_counts_zero_filled_and_grouped(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    conn.execute("INSERT INTO customers (customer_id, name) VALUES ('C','Test')")
    for aid, st in [("A1", "OPEN"), ("A2", "OPEN"), ("A3", "PROPOSED")]:
        conn.execute("INSERT INTO alerts (alert_id, customer_id, status) VALUES (?,?,?)", (aid, "C", st))
    conn.commit()
    import api.main as main
    r = TestClient(main.app).get("/api/alerts/counts")
    assert r.status_code == 200
    counts = r.json()["counts"]
    assert counts["OPEN"] == 2
    assert counts["PROPOSED"] == 1
    assert counts["PENDING"] == 0 and counts["CLOSED"] == 0  # zero-filled
