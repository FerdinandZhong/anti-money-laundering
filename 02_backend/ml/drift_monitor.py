import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import numpy as np
import pandas as pd

from common import source

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


def compute_psi(conn=None, feature: str = "amount_log", n_bins: int = 10) -> dict:
    """
    Compare feature distribution between reference (transactions older than 30 days)
    and current (last 30 days). Returns {"psi": float, "drift_detected": bool, "threshold": 0.2}.

    Source data comes from the source layer (Impala/CSV); `conn` is unused.
    """
    df = source.transactions_features_df()
    df = df[df["transaction_id"].notna()]

    # Split reference vs current on ISO event_time (string compare, same as before).
    cutoff = (pd.Timestamp.now() - pd.Timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    tx_ref = df[df["event_time"] < cutoff]
    tx_cur = df[df["event_time"] >= cutoff]

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
