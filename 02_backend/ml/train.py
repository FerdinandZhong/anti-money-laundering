import sys
import os

try:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except NameError:
    # __file__ is not defined in interactive environments (e.g. CML notebook sessions)
    PROJECT_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import json
import datetime
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import average_precision_score

from common.config import get_config
from ml.feature_engineering import build_feature_matrix


def train_model(conn) -> str:
    """Train model, save to models/, return model_version string."""
    cfg = get_config()["model"]

    X, y = build_feature_matrix(conn)
    print(f"Dataset: {len(X)} rows, {y.sum()} positives ({y.mean()*100:.1f}%)")

    # Split: train / val / test
    test_size = cfg.get("test_size", 0.2)
    val_size = cfg.get("val_size", 0.1)

    X_tv, X_test, y_tv, y_test = train_test_split(X, y, test_size=test_size, random_state=42, stratify=y)
    val_frac = val_size / (1.0 - test_size)
    X_train, X_val, y_train, y_val = train_test_split(X_tv, y_tv, test_size=val_frac, random_state=42, stratify=y_tv)

    neg = int((y_train == 0).sum())
    pos = int((y_train == 1).sum())
    scale_pos_weight = neg / max(pos, 1)

    model = xgb.XGBClassifier(
        max_depth=cfg.get("max_depth", 6),
        learning_rate=cfg.get("learning_rate", 0.1),
        n_estimators=cfg.get("n_estimators", 300),
        scale_pos_weight=scale_pos_weight,
        eval_metric="aucpr",
        early_stopping_rounds=20,
        use_label_encoder=False,
        random_state=42,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    # Evaluate
    scores_test = model.predict_proba(X_test)[:, 1]
    pr_auc = float(average_precision_score(y_test, scores_test))

    # recall/precision in top 2%
    top2_thresh = np.percentile(scores_test, 98)
    top2_mask = scores_test >= top2_thresh
    tp = int((y_test[top2_mask] == 1).sum())
    fn = int((y_test[~top2_mask] == 1).sum())
    fp = int((y_test[top2_mask] == 0).sum())
    recall_top2pct = tp / max(tp + fn, 1)
    precision_top2pct = tp / max(tp + fp, 1)

    metrics = {
        "pr_auc": round(pr_auc, 4),
        "recall_top2pct": round(recall_top2pct, 4),
        "precision_top2pct": round(precision_top2pct, 4),
        "best_iteration": int(model.best_iteration) if hasattr(model, "best_iteration") else cfg.get("n_estimators", 300),
    }
    print(f"Metrics: {metrics}")

    # Save model
    version = "v" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    model_dir = os.path.join(PROJECT_ROOT, cfg.get("model_dir", "models"))
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, f"aml_model_{version}.json")
    model.save_model(model_path)
    print(f"Saved: {model_path}")

    # Record model run
    run_id = f"RUN-{version}"
    conn.execute(
        "INSERT OR IGNORE INTO model_runs (run_id, model_version, status, metrics) VALUES (?, ?, ?, ?)",
        (run_id, version, "COMPLETE", json.dumps(metrics)),
    )
    conn.commit()

    return version


def promote(conn, version: str, model_dir: str) -> None:
    """Flip the CHAMPION deployment to this version. Asserts the artifact
    exists first — this is the seam that was missing: train_model() alone
    never touched `deployments`, so a direct CLI run left the CHAMPION
    pointer stale and scorer.py/get_model_explanation silently fell back to
    the newest artifact on disk instead of the one actually promoted.
    (agents/retraining.py already does its own canary-then-promote and does
    not call this — this is for direct `python -m ml.train` runs.)
    """
    model_path = os.path.join(model_dir, f"aml_model_{version}.json")
    assert os.path.exists(model_path), f"cannot promote {version}: artifact missing at {model_path}"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.execute(
        "UPDATE deployments SET status='RETIRED', rolled_back_at=? WHERE status='CHAMPION'",
        (now,),
    )
    conn.execute(
        "INSERT INTO deployments (deployment_id, model_version, environment, traffic_pct, status, deployed_at) "
        "VALUES (?, ?, 'production', 100.0, 'CHAMPION', ?)",
        (f"DEPLOY-{version}", version, now),
    )
    conn.commit()


if __name__ == "__main__":
    from common.db import get_connection
    conn = get_connection()
    version = train_model(conn)
    model_dir = os.path.join(PROJECT_ROOT, get_config()["model"].get("model_dir", "models"))
    promote(conn, version, model_dir)
    # Populate the alert queue with the freshly promoted champion. The CML job
    # chain has no separate scoring step, so fold it in here — otherwise the
    # dashboard shows no open alerts. Idempotent: score_transactions dedupes by
    # account (skips accounts that already have an OPEN alert).
    from ml.scorer import score_transactions
    created = score_transactions(conn)
    print(f"Scored transactions -> {created} new alert(s)")
    conn.close()
    print(f"Model saved + promoted to CHAMPION: {version}")
