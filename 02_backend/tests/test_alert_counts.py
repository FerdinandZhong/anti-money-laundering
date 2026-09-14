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


def test_open_queue_hides_legacy_duplicate_of_processed_snapshot(tmp_db_path):
    """A pre-fix duplicate must not remain visible as Open when its sibling
    account alert is already in Proposed for the same data cutoff."""
    from common.db import get_connection
    conn = get_connection()
    conn.execute("INSERT INTO customers (customer_id, name) VALUES ('C2', 'Test')")
    conn.execute("INSERT INTO accounts (account_id, customer_id) VALUES ('ACC-2', 'C2')")
    for aid, status in (("A-OPEN", "OPEN"), ("A-PROPOSED", "PROPOSED")):
        conn.execute(
            "INSERT INTO alerts (alert_id, customer_id, account_id, status, data_cutoff_at) "
            "VALUES (?, 'C2', 'ACC-2', ?, '2026-09-13T13:32:00')", (aid, status)
        )
    conn.commit()

    import api.main as main
    client = TestClient(main.app)
    open_queue = client.get("/api/alerts?status=OPEN").json()
    counts = client.get("/api/alerts/counts").json()["counts"]
    assert open_queue["alerts"] == [] and open_queue["total"] == 0
    assert counts["OPEN"] == 0 and counts["PROPOSED"] == 1
