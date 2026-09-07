import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import numpy as np
import pandas as pd

from common import source


FEATURE_COLS = [
    "amount_log",
    "is_round_amount",
    "is_swift",
    "is_cross_border",
    "customer_risk_high",
    "customer_risk_medium",
    "account_age_days",
    "expected_monthly_turnover_log",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "tx_count_24h",
    "tx_amount_sum_24h",
    "shared_device_flag",
]


def _load_human_labels() -> dict:
    """{transaction_id: label} analyst per-tx labels from the ops store.

    Returns {} when the ops DB is missing or the table is empty (cold start) —
    training then falls back to synthetic labels unchanged.
    """
    try:
        from common.db import get_connection
        conn = get_connection()
        try:
            rows = conn.execute("SELECT transaction_id, label FROM transaction_labels").fetchall()
            return {r["transaction_id"]: int(r["label"]) for r in rows}
        finally:
            conn.close()
    except Exception:
        return {}


def _apply_human_labels(y: pd.Series, transaction_ids: pd.Series, human: dict) -> pd.Series:
    """COALESCE(human_tx_label, synthetic): human label wins where present."""
    if not human:
        return y.astype(int)
    return transaction_ids.map(human).fillna(y).astype(int)


def build_feature_matrix(conn=None) -> tuple[pd.DataFrame, pd.Series]:
    """Return (X, y) where X has engineered features and y is the training label.

    Label = COALESCE(analyst per-tx label, synthetic is_suspicious): human
    decisions override the synthetic ground-truth where present. Source data
    comes from the source layer (Impala/CSV); `conn` is accepted for backward
    compatibility but unused.
    """
    tx = source.transactions_features_df(with_customer_id=False)

    tx = tx[tx["transaction_id"].notna()].copy()

    # Shared device flag: fingerprints that appear on >1 account
    dev = source.devices_df()
    fp_counts = dev.groupby("device_fingerprint")["account_id"].nunique()
    shared_fps = set(fp_counts[fp_counts > 1].index)
    # map account_id -> shared flag
    dev["shared"] = dev["device_fingerprint"].isin(shared_fps).astype(int)
    acc_shared = dev.groupby("account_id")["shared"].max().reset_index()
    acc_shared.columns = ["from_account_id", "shared_device_flag"]

    tx = tx.merge(acc_shared, on="from_account_id", how="left")

    # Basic features
    tx["amount_log"] = np.log1p(tx["amount"])
    tx["is_round_amount"] = (tx["amount"] % 1000 == 0).astype(int)
    tx["is_swift"] = (tx["channel"] == "SWIFT").astype(int)
    tx["is_cross_border"] = (~tx["counterparty_country"].isin(["SG", None, ""])).astype(int)
    tx["customer_risk_high"] = (tx["risk_rating"] == "HIGH").astype(int)
    tx["customer_risk_medium"] = (tx["risk_rating"] == "MEDIUM").astype(int)
    tx["account_age_days"] = tx["account_age_days"].fillna(365)
    tx["expected_monthly_turnover_log"] = np.log1p(tx["expected_monthly_turnover"].fillna(0))

    # Time features
    tx["event_dt"] = pd.to_datetime(tx["event_time"])
    tx["hour_of_day"] = tx["event_dt"].dt.hour
    tx["day_of_week"] = tx["event_dt"].dt.dayofweek
    tx["is_weekend"] = (tx["day_of_week"] >= 5).astype(int)

    # Velocity: 24h rolling per account
    tx = tx.sort_values(["from_account_id", "event_dt"])
    tx["tx_count_24h"] = 0.0
    tx["tx_amount_sum_24h"] = 0.0

    has_account = tx["from_account_id"].notna()
    for acc_id, grp in tx[has_account].groupby("from_account_id"):
        times = grp["event_dt"].values
        amounts = grp["amount"].values
        idx = grp.index
        counts = []
        sums = []
        for i, t in enumerate(times):
            window_start = t - np.timedelta64(24, "h")
            mask = (times[:i] >= window_start)
            counts.append(int(mask.sum()))
            sums.append(float(amounts[:i][mask].sum()))
        tx.loc[idx, "tx_count_24h"] = counts
        tx.loc[idx, "tx_amount_sum_24h"] = sums

    tx["tx_count_24h"] = tx["tx_count_24h"].fillna(0)
    tx["tx_amount_sum_24h"] = tx["tx_amount_sum_24h"].fillna(0)
    tx["shared_device_flag"] = tx["shared_device_flag"].fillna(0)

    tx = tx.dropna(subset=FEATURE_COLS)

    y = _apply_human_labels(tx["is_suspicious"], tx["transaction_id"], _load_human_labels())

    X = tx[FEATURE_COLS].reset_index(drop=True)
    y = y.reset_index(drop=True)
    return X, y


def build_scored_df(conn=None) -> "pd.DataFrame":
    """Return full dataframe with FEATURE_COLS + from_account_id + customer_id, for scoring.

    Source data comes from the source layer (Impala/CSV); `conn` is accepted for
    backward compatibility but unused.
    """
    tx = source.transactions_features_df(with_customer_id=True)

    tx = tx[tx["transaction_id"].notna()].copy()

    dev = source.devices_df()
    fp_counts = dev.groupby("device_fingerprint")["account_id"].nunique()
    shared_fps = set(fp_counts[fp_counts > 1].index)
    dev["shared"] = dev["device_fingerprint"].isin(shared_fps).astype(int)
    acc_shared = dev.groupby("account_id")["shared"].max().reset_index()
    acc_shared.columns = ["from_account_id", "shared_device_flag"]

    tx = tx.merge(acc_shared, on="from_account_id", how="left")

    tx["amount_log"] = np.log1p(tx["amount"])
    tx["is_round_amount"] = (tx["amount"] % 1000 == 0).astype(int)
    tx["is_swift"] = (tx["channel"] == "SWIFT").astype(int)
    tx["is_cross_border"] = (~tx["counterparty_country"].isin(["SG", None, ""])).astype(int)
    tx["customer_risk_high"] = (tx["risk_rating"] == "HIGH").astype(int)
    tx["customer_risk_medium"] = (tx["risk_rating"] == "MEDIUM").astype(int)
    tx["account_age_days"] = tx["account_age_days"].fillna(365)
    tx["expected_monthly_turnover_log"] = np.log1p(tx["expected_monthly_turnover"].fillna(0))

    tx["event_dt"] = pd.to_datetime(tx["event_time"])
    tx["hour_of_day"] = tx["event_dt"].dt.hour
    tx["day_of_week"] = tx["event_dt"].dt.dayofweek
    tx["is_weekend"] = (tx["day_of_week"] >= 5).astype(int)

    tx = tx.sort_values(["from_account_id", "event_dt"])
    tx["tx_count_24h"] = 0.0
    tx["tx_amount_sum_24h"] = 0.0

    has_account = tx["from_account_id"].notna()
    for acc_id, grp in tx[has_account].groupby("from_account_id"):
        times = grp["event_dt"].values
        amounts = grp["amount"].values
        idx = grp.index
        counts = []
        sums = []
        for i, t in enumerate(times):
            window_start = t - np.timedelta64(24, "h")
            mask = (times[:i] >= window_start)
            counts.append(int(mask.sum()))
            sums.append(float(amounts[:i][mask].sum()))
        tx.loc[idx, "tx_count_24h"] = counts
        tx.loc[idx, "tx_amount_sum_24h"] = sums

    tx["tx_count_24h"] = tx["tx_count_24h"].fillna(0)
    tx["tx_amount_sum_24h"] = tx["tx_amount_sum_24h"].fillna(0)
    tx["shared_device_flag"] = tx["shared_device_flag"].fillna(0)

    tx = tx.dropna(subset=FEATURE_COLS)
    return tx.reset_index(drop=True)


if __name__ == "__main__":
    # Self-check: analyst labels must override the synthetic label (COALESCE).
    tids = pd.Series(["a", "b", "c"])
    synth = pd.Series([0, 0, 1])
    out = _apply_human_labels(synth, tids, {"a": 1, "c": 0})
    assert list(out) == [1, 0, 0], f"override broken: {list(out)}"
    # empty human labels → synthetic unchanged
    assert list(_apply_human_labels(synth, tids, {})) == [0, 0, 1]
    print("feature_engineering: human-label override OK", list(out))
