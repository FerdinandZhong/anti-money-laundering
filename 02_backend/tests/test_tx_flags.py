from common.tx_flags import derive_tx_flags


def _tx(**kw):
    base = {"amount": 100.0, "event_time": "2026-07-09T14:00:00", "counterparty_country": "SG",
            "counterparty_name": "Shop", "direction": "OUTBOUND"}
    base.update(kw); return base


def test_near_threshold_fires_just_under_50k():
    flags = derive_tx_flags(_tx(amount=48201.0), [])
    assert any(f["key"] == "near_threshold" for f in flags)


def test_near_threshold_silent_for_small_amount():
    flags = derive_tx_flags(_tx(amount=60.0), [])
    assert not any(f["key"] == "near_threshold" for f in flags)


def test_off_hours_fires_at_3am():
    flags = derive_tx_flags(_tx(event_time="2026-07-09T03:21:00"), [])
    assert any(f["key"] == "off_hours" for f in flags)


def test_cross_border_fires_for_non_sg():
    flags = derive_tx_flags(_tx(counterparty_country="MY"), [])
    assert any(f["key"] == "cross_border" for f in flags)


def test_repeat_counterparty_needs_more_than_one():
    others = [_tx(counterparty_name="Recip_A"), _tx(counterparty_name="Recip_A")]
    flags = derive_tx_flags(_tx(counterparty_name="Recip_A"), others)
    assert any(f["key"] == "repeat_counterparty" for f in flags)


def test_clean_small_domestic_daytime_row_has_no_flags():
    assert derive_tx_flags(_tx(amount=60.0, event_time="2026-07-09T12:13:00",
                               counterparty_country="SG", counterparty_name="Grab"), []) == []


def test_detail_includes_network_and_flags(tmp_db_path, monkeypatch):
    from fastapi.testclient import TestClient
    from common.db import get_connection
    import api.main as main

    conn = get_connection()
    conn.execute("INSERT INTO customers (customer_id, name) VALUES ('CUST-1','Test')")
    conn.execute("INSERT INTO accounts (account_id, customer_id) VALUES ('ACC-1','CUST-1')")
    conn.execute("INSERT INTO alerts (alert_id, customer_id, account_id, risk_score, risk_band, status, created_at) "
                 "VALUES ('ALERT-1','CUST-1','ACC-1',0.9,'CRITICAL','OPEN','t')")
    conn.commit()

    monkeypatch.setattr(main.source, "get_customer", lambda c: {"name": "X", "risk_rating": "LOW"})
    monkeypatch.setattr(main.source, "customer_transactions", lambda c, limit=20: [
        {"transaction_id": "T1", "event_time": "2026-07-09T03:21:00", "direction": "OUTBOUND",
         "amount": 48201.0, "channel": "FAST", "counterparty_name": "R", "counterparty_country": "MY"}])
    monkeypatch.setattr(main.source, "get_accounts", lambda c: [{"account_id": "ACC-1"}])
    monkeypatch.setattr(main.source, "device_fingerprints", lambda a: [])
    monkeypatch.setattr(main.source, "accounts_by_fingerprints", lambda f: [])
    monkeypatch.setattr(main.source, "account_transactions", lambda a, limit=200: [])

    r = TestClient(main.app).get("/api/alerts/ALERT-1/detail")
    body = r.json()
    assert "network" in body and body["network"]["nodes"][0]["is_root"] is True
    flags = {f["key"] for f in body["transactions"][0]["flags"]}
    assert "near_threshold" in flags and "off_hours" in flags and "cross_border" in flags
