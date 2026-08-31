import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import uuid
import datetime
import xgboost as xgb

from common.config import get_config
from ml.feature_engineering import build_scored_df, FEATURE_COLS


def _risk_band(score: float) -> str:
    if score >= 0.9:
        return "CRITICAL"
    if score >= 0.7:
        return "HIGH"
    if score >= 0.5:
        return "MEDIUM"
    return "LOW"


def score_transactions(conn, model_path: str | None = None) -> int:
    """Score transactions. Returns count of new alerts created."""
    cfg = get_config()
    threshold = cfg["model"].get("decision_threshold", 0.5)
    model_version = "unknown"

    if model_path is None:
        row = conn.execute(
            "SELECT model_version FROM deployments WHERE status='CHAMPION' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("No CHAMPION deployment found. Train and deploy a model first.")
        model_version = row["model_version"]
        model_dir = os.path.join(PROJECT_ROOT, cfg["model"].get("model_dir", "models"))
        model_path = os.path.join(model_dir, f"aml_model_{model_version}.json")
    else:
        # Extract version from path
        basename = os.path.basename(model_path)
        if basename.startswith("aml_model_") and basename.endswith(".json"):
            model_version = basename[len("aml_model_"):-len(".json")]

    model = xgb.XGBClassifier()
    model.load_model(model_path)

    df = build_scored_df(conn)
    df["score"] = model.predict_proba(df[FEATURE_COLS])[:, 1]

    # Only flag accounts where from_account_id is set
    scored = df[df["from_account_id"].notna()].copy()

    grp = scored.groupby("from_account_id")
    account_max = grp["score"].max()
    account_above_thresh_pct = grp["score"].apply(lambda s: (s > threshold).mean())

    flagged = account_max[(account_max > 0.8) | (account_above_thresh_pct > 0.1)].index

    # Existing OPEN alerts
    existing = set(
        r[0] for r in conn.execute(
            "SELECT account_id FROM alerts WHERE status='OPEN' AND account_id IS NOT NULL"
        ).fetchall()
    )

    sla = (datetime.datetime.now() + datetime.timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%S")

    new_count = 0
    for acc_id in flagged:
        if acc_id in existing:
            continue
        max_score = float(account_max[acc_id])
        customer_id = scored[scored["from_account_id"] == acc_id]["customer_id"].iloc[0]
        if not customer_id:
            customer_id = None

        alert_id = f"ALERT-ML-{uuid.uuid4().hex[:10].upper()}"
        conn.execute(
            "INSERT INTO alerts (alert_id, customer_id, account_id, triggered_rules, risk_score, "
            "risk_band, reason_codes, model_version, status, sla_deadline) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)",
            (
                alert_id,
                customer_id,
                acc_id,
                '["ML_SCORE"]',
                round(max_score, 4),
                _risk_band(max_score),
                '["ML_SCORE"]',
                model_version,
                sla,
            ),
        )
        new_count += 1

    conn.commit()
    return new_count
