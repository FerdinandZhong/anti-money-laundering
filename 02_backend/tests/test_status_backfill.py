def test_backfill_remaps_legacy_closed_alerts(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    conn.execute("INSERT INTO customers (customer_id, name) VALUES ('C1','Test')")
    # a closed case whose alert is still OPEN (legacy state before Task 1 existed)
    conn.execute("INSERT INTO alerts (alert_id, customer_id, status) VALUES ('A1','C1','OPEN')")
    conn.execute("INSERT INTO cases (case_id, alert_id, customer_id, state, disposition, created_at, updated_at) "
                 "VALUES ('K1','A1','C1','CLOSED','SUSPICIOUS','t','t')")
    # an untouched open alert with no case
    conn.execute("INSERT INTO alerts (alert_id, customer_id, status) VALUES ('A2','C1','OPEN')")
    conn.commit(); conn.close()

    conn2 = get_connection()  # backfill runs on connect
    assert conn2.execute("SELECT status FROM alerts WHERE alert_id='A1'").fetchone()["status"] == "PROPOSED"
    assert conn2.execute("SELECT status FROM alerts WHERE alert_id='A2'").fetchone()["status"] == "OPEN"


def test_backfill_is_idempotent(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    conn.execute("INSERT INTO customers (customer_id, name) VALUES ('C1','Test')")
    conn.execute("INSERT INTO alerts (alert_id, customer_id, status) VALUES ('A1','C1','OPEN')")
    conn.execute("INSERT INTO cases (case_id, alert_id, customer_id, state, disposition, created_at, updated_at) "
                 "VALUES ('K1','A1','C1','CLOSED','FALSE_POSITIVE','t','t')")
    conn.commit(); conn.close()
    s1 = get_connection().execute("SELECT status FROM alerts WHERE alert_id='A1'").fetchone()["status"]
    s2 = get_connection().execute("SELECT status FROM alerts WHERE alert_id='A1'").fetchone()["status"]
    assert s1 == s2 == "CLOSED"
