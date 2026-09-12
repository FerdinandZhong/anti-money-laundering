import numpy as np
import pandas as pd
import pytest
import json


def test_risk_band_boundaries():
    from ml.scorer import _risk_band

    assert _risk_band(0.95) == "CRITICAL"
    assert _risk_band(0.9) == "CRITICAL"
    assert _risk_band(0.89) == "HIGH"
    assert _risk_band(0.7) == "HIGH"
    assert _risk_band(0.69) == "MEDIUM"
    assert _risk_band(0.5) == "MEDIUM"
    assert _risk_band(0.49) == "LOW"


def test_legacy_priority_recovers_only_verifiable_queue_arithmetic():
    from ml.priority import display_priority, recover_legacy_queue_position

    # Saved alerts from the 20-account demo batch. The weighted account inputs
    # were not saved, but their display priorities still encode queue position.
    for account_id, saved_score, expected_percentile in (
        ("ACC-NETWORK-001", 0.9154, 0.85),
        ("ACC-0000294", 0.9406, 0.95),
    ):
        breakdown = recover_legacy_queue_position(account_id, saved_score)
        assert breakdown is not None
        assert breakdown["daily_queue_percentile"] == expected_percentile
        assert breakdown["account_evidence_score"] is None
        assert breakdown["signals"] == []
        assert sum(breakdown[k] for k in (
            "base_priority", "rank_contribution", "jitter_contribution"
        )) == pytest.approx(saved_score, abs=0.000051)
        assert display_priority(account_id, expected_percentile) == pytest.approx(saved_score, abs=0.000051)

    assert recover_legacy_queue_position("ACC-NETWORK-001", 0.91) is None
    assert recover_legacy_queue_position("ACC-NETWORK-001", 0.96) is None
    assert recover_legacy_queue_position(None, 0.9154) is None


@pytest.fixture
def synthetic_scored_df():
    """20 accounts, each with a handful of transactions, model score encoded as
    a deterministic per-account probability so the flag/aggregate/band logic in
    score_transactions has real signal to work with — no live model or source
    layer needed."""
    from ml.feature_engineering import FEATURE_COLS

    rows = []
    rng = np.random.default_rng(42)
    for i in range(20):
        acc_id = f"ACC-{i:03d}"
        # first 4 accounts are clearly suspicious (near-1 model score)
        base_score = 0.97 if i < 4 else rng.uniform(0.0, 0.3)
        for j in range(5):
            row = {"transaction_id": f"TX-{i:03d}-{j}", "from_account_id": acc_id,
                   "customer_id": f"CUST-{i:03d}", "tx_count_24h": 3.0 if i < 4 else 0.0,
                   "tx_amount_sum_24h": 60_000.0 if i < 4 else 100.0,
                   "shared_device_flag": 1 if i < 4 else 0,
                   "is_cross_border": 1 if i < 4 else 0,
                   "event_time": f"2026-09-{8 + j:02d}T12:00:00"}
            for col in FEATURE_COLS:
                row.setdefault(col, 0.0)
            row["_base_score"] = base_score
            rows.append(row)
    return pd.DataFrame(rows)


def _seed_customers_and_accounts(conn, synthetic_scored_df):
    """alerts.customer_id/account_id are FK-constrained; seed the referenced
    rows so INSERT INTO alerts doesn't fail under PRAGMA foreign_keys=ON."""
    for _, row in synthetic_scored_df[["customer_id", "from_account_id"]].drop_duplicates().iterrows():
        conn.execute("INSERT OR IGNORE INTO customers (customer_id, name) VALUES (?, ?)",
                     (row["customer_id"], row["customer_id"]))
        conn.execute("INSERT OR IGNORE INTO accounts (account_id, customer_id) VALUES (?, ?)",
                     (row["from_account_id"], row["customer_id"]))
    conn.commit()


def test_score_transactions_flags_only_suspicious_accounts(monkeypatch, db_conn, synthetic_scored_df):
    """End-to-end through score_transactions with a stubbed model + source layer:
    only the 4 seeded-suspicious accounts clear the candidate floor (the other
    16 score too low), so exactly those 4 get distinct, banded alert rows."""
    from ml import scorer

    _seed_customers_and_accounts(db_conn, synthetic_scored_df)
    monkeypatch.setattr(scorer, "build_scored_df", lambda conn: synthetic_scored_df)

    class _FakeModel:
        def load_model(self, path):
            pass

        def predict_proba(self, X):
            # X is the FEATURE_COLS slice; re-derive the per-row base score by
            # index position (aligned 1:1 with synthetic_scored_df).
            base = synthetic_scored_df["_base_score"].to_numpy()
            return np.column_stack([1 - base, base])

    monkeypatch.setattr(scorer.xgb, "XGBClassifier", lambda: _FakeModel())

    created = scorer.score_transactions(db_conn, model_path="aml_model_vtest.json")
    assert created == 4

    rows = db_conn.execute(
        "SELECT account_id, risk_band, risk_score, top_features, scoring_run_at, data_cutoff_at, "
        "window_start_at, pattern_start_at, latest_contributing_at "
        "FROM alerts WHERE alert_id LIKE 'ALERT-ML-%'"
    ).fetchall()
    assert len(rows) == 4
    flagged_accounts = {r["account_id"] for r in rows}
    assert flagged_accounts == {"ACC-000", "ACC-001", "ACC-002", "ACC-003"}

    scores = [r["risk_score"] for r in rows]
    assert len(set(scores)) == 4, f"expected distinct scores per account, got {scores}"
    for s in scores:
        assert 0.63 <= s <= 0.96

    for row in rows:
        assert all(row[field] for field in (
            "scoring_run_at", "data_cutoff_at", "window_start_at",
            "pattern_start_at", "latest_contributing_at",
        )), "every new alert must carry an explicit detection chronology"
        assert row["window_start_at"] <= row["data_cutoff_at"]
        assert row["window_start_at"] <= row["pattern_start_at"]
        assert row["pattern_start_at"] <= row["latest_contributing_at"]
        breakdown = json.loads(row["top_features"])["score_breakdown"]
        assert breakdown["display_priority_score"] == pytest.approx(row["risk_score"])
        assert len(breakdown["signals"]) == 6
        assert sum(s["weight"] for s in breakdown["signals"]) == pytest.approx(1.0)

    tx_scores = db_conn.execute("SELECT COUNT(*), COUNT(DISTINCT score) FROM transaction_scores").fetchone()
    assert tx_scores[0] == len(synthetic_scored_df)


def test_score_transactions_dedupes_existing_open_alerts(monkeypatch, db_conn, synthetic_scored_df):
    from ml import scorer

    _seed_customers_and_accounts(db_conn, synthetic_scored_df)
    monkeypatch.setattr(scorer, "build_scored_df", lambda conn: synthetic_scored_df)

    class _FakeModel:
        def load_model(self, path):
            pass

        def predict_proba(self, X):
            base = synthetic_scored_df["_base_score"].to_numpy()
            return np.column_stack([1 - base, base])

    monkeypatch.setattr(scorer.xgb, "XGBClassifier", lambda: _FakeModel())

    first = scorer.score_transactions(db_conn, model_path="aml_model_vtest.json")
    second = scorer.score_transactions(db_conn, model_path="aml_model_vtest.json")

    assert first == 4
    assert second == 0, "re-running scoring must not duplicate alerts for already-OPEN accounts"


def test_score_transactions_caps_queue_at_target_alerts(monkeypatch, db_conn):
    """When far more than TARGET_ALERTS accounts are suspicious, the queue is
    capped at the TARGET_ALERTS highest-composite accounts (top-N), not every
    account above a fixed threshold."""
    import numpy as np
    import pandas as pd
    from ml import scorer
    from ml.feature_engineering import FEATURE_COLS

    n_accounts = scorer.TARGET_ALERTS + 15  # comfortably more candidates than the cap
    rows = []
    for i in range(n_accounts):
        acc_id = f"ACC-{i:03d}"
        for j in range(5):
            row = {"transaction_id": f"TX-{i:03d}-{j}", "from_account_id": acc_id,
                   "customer_id": f"CUST-{i:03d}", "tx_count_24h": 3.0,
                   "tx_amount_sum_24h": 60_000.0, "shared_device_flag": 1, "is_cross_border": 1}
            for col in FEATURE_COLS:
                row.setdefault(col, 0.0)
            # every account clearly suspicious, but with a slightly different score
            # so the composite ranking is well-defined
            row["_base_score"] = 0.90 + (i % 10) * 0.005
            rows.append(row)
    df = pd.DataFrame(rows)

    _seed_customers_and_accounts(db_conn, df)
    monkeypatch.setattr(scorer, "build_scored_df", lambda conn: df)

    class _FakeModel:
        def load_model(self, path):
            pass

        def predict_proba(self, X):
            base = df["_base_score"].to_numpy()
            return np.column_stack([1 - base, base])

    monkeypatch.setattr(scorer.xgb, "XGBClassifier", lambda: _FakeModel())

    created = scorer.score_transactions(db_conn, model_path="aml_model_vtest.json")
    assert created == scorer.TARGET_ALERTS, f"expected top-{scorer.TARGET_ALERTS}, got {created}"

    total = db_conn.execute("SELECT COUNT(*) FROM alerts WHERE alert_id LIKE 'ALERT-ML-%'").fetchone()[0]
    assert total == scorer.TARGET_ALERTS
