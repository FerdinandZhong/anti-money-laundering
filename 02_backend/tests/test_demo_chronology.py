from datetime import datetime


def test_corp_0294_is_a_replayable_structuring_story():
    from data_generation.generate_synthetic_data import (
        DEMO_ACCOUNT_ID,
        DEMO_CUSTOMER_ID,
        gen_accounts,
        gen_customers,
        gen_demo_customer_history,
        gen_structuring_transactions,
    )

    customers = gen_customers(2000)
    customer = next(c for c in customers if c["customer_id"] == DEMO_CUSTOMER_ID)
    assert customer["name"] == "Corp_0294 Pte. Ltd."
    assert customer["risk_rating"] == "LOW"
    assert customer["expected_monthly_turnover"] == 421390.0

    accounts = gen_accounts(customers, 1900)
    account = next(a for a in accounts if a["account_id"] == DEMO_ACCOUNT_ID)
    assert account["customer_id"] == DEMO_CUSTOMER_ID
    assert account["status"] == "ACTIVE"
    assert account["account_type"] == "CORPORATE"

    history = gen_demo_customer_history(accounts)
    baseline = [t for t in history if t["transaction_id"].startswith("TX-DEMO-BASE")]
    early = [t for t in history if t["transaction_id"].startswith("TX-DEMO-EARLY")]
    structuring = gen_structuring_transactions(accounts)

    assert len(baseline) == 24
    assert len(early) == 6
    assert len(structuring) == 72
    assert {t["from_account_id"] for t in history + structuring} == {DEMO_ACCOUNT_ID}
    assert all(t["is_suspicious"] == 0 for t in history)
    assert all(t["typology"] == "STRUCTURING" for t in structuring)

    now = datetime.now()
    baseline_days = [(now - datetime.fromisoformat(t["event_time"])).total_seconds() / 86400 for t in baseline]
    early_days = [(now - datetime.fromisoformat(t["event_time"])).total_seconds() / 86400 for t in early]
    structuring_days = [(now - datetime.fromisoformat(t["event_time"])).total_seconds() / 86400 for t in structuring]
    assert min(baseline_days) >= 19.9
    assert 4.0 <= min(early_days) <= max(early_days) <= 7.0
    assert 0 <= min(structuring_days) <= max(structuring_days) <= 3.1
