import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import numpy as np
import pandas as pd

from ml.feature_engineering import build_feature_matrix

PSI_THRESHOLD = 0.2
MIN_ROWS = 50


def _psi(expected: np.ndarray, actual: np.ndarray, n_bins: int) -> float:
    """PSI between two 1-d arrays using equal-width bins from combined range."""
    combined = np.concatenate([expected, actual])
    bins = np.linspace(combined.min(), combined.max(), n_bins + 1)
    bins[0] -= 1e-9
    bins[-1] += 1e-9

    exp_counts, _ = np.histogram(expected, bins=bins)
    act_counts, _ = np.histogram(actual, bins=bins)

    exp_pct = exp_counts / max(len(expected), 1)
    act_pct = act_counts / max(len(actual), 1)

    # Avoid div/log of zero
    exp_pct = np.where(exp_pct == 0, 1e-6, exp_pct)
    act_pct = np.where(act_pct == 0, 1e-6, act_pct)

    psi_val = float(np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct)))
    return psi_val


def compute_psi(conn, feature: str = "amount_log", n_bins: int = 10) -> dict:
    """
    Compare feature distribution between reference (transactions older than 30 days)
    and current (last 30 days). Returns {"psi": float, "drift_detected": bool, "threshold": 0.2}.
    """
    X, _ = build_feature_matrix(conn)

    # Re-fetch event_time to split reference vs current
    tx_times = pd.read_sql_query(
        "SELECT transaction_id, event_time FROM transactions WHERE transaction_id IS NOT NULL",
        conn,
    )
    # build_feature_matrix does not preserve transaction_id in X; we split by index order
    # Instead, rebuild event_time series in same order as X
    # Simpler: just use a raw SQL split directly on the feature
    cutoff = (pd.Timestamp.now() - pd.Timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")

    tx_ref = pd.read_sql_query(
        f"SELECT t.amount, t.channel, t.counterparty_country, t.event_time, "
        f"c.risk_rating, c.account_age_days, c.expected_monthly_turnover "
        f"FROM transactions t "
        f"LEFT JOIN accounts a ON t.from_account_id = a.account_id "
        f"LEFT JOIN customers c ON a.customer_id = c.customer_id "
        f"WHERE t.transaction_id IS NOT NULL AND t.event_time < '{cutoff}'",
        conn,
    )
    tx_cur = pd.read_sql_query(
        f"SELECT t.amount, t.channel, t.counterparty_country, t.event_time, "
        f"c.risk_rating, c.account_age_days, c.expected_monthly_turnover "
        f"FROM transactions t "
        f"LEFT JOIN accounts a ON t.from_account_id = a.account_id "
        f"LEFT JOIN customers c ON a.customer_id = c.customer_id "
        f"WHERE t.transaction_id IS NOT NULL AND t.event_time >= '{cutoff}'",
        conn,
    )

    insufficient = {"psi": 0.0, "drift_detected": False, "threshold": PSI_THRESHOLD, "insufficient_data": True}
    if len(tx_ref) < MIN_ROWS or len(tx_cur) < MIN_ROWS:
        return insufficient

    def _derive(df: pd.DataFrame) -> pd.Series:
        if feature == "amount_log":
            return np.log1p(df["amount"])
        if feature == "hour_of_day":
            return pd.to_datetime(df["event_time"]).dt.hour.astype(float)
        if feature == "is_cross_border":
            return (~df["counterparty_country"].isin(["SG", None, ""])).astype(float)
        raise ValueError(f"Unknown feature: {feature}")

    ref_vals = _derive(tx_ref).dropna().values
    cur_vals = _derive(tx_cur).dropna().values

    if len(ref_vals) < MIN_ROWS or len(cur_vals) < MIN_ROWS:
        return insufficient

    psi_val = _psi(ref_vals, cur_vals, n_bins)
    return {
        "psi": round(psi_val, 4),
        "drift_detected": psi_val > PSI_THRESHOLD,
        "threshold": PSI_THRESHOLD,
    }


def get_drift_summary(conn) -> dict:
    """Run PSI for amount_log, hour_of_day, is_cross_border. Return dict of feature->psi_result."""
    return {
        feat: compute_psi(conn, feature=feat)
        for feat in ("amount_log", "hour_of_day", "is_cross_border")
    }
