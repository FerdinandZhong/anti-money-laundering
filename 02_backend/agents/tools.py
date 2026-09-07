import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import json
from typing import Callable

from ml import drift_monitor
from common import source


# ---------------------------------------------------------------------------
# Individual tool implementations
# ---------------------------------------------------------------------------

def get_alert_detail(conn, alert_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)
    ).fetchone()
    if row is None:
        return {"error": f"Alert {alert_id} not found"}
    result = dict(row)
    case = conn.execute(
        "SELECT * FROM cases WHERE alert_id = ?", (alert_id,)
    ).fetchone()
    if case:
        result["case"] = dict(case)
    return result


def get_customer_profile(conn, customer_id: str) -> dict:
    # Source data via the source layer (Impala/CSV); `conn` unused.
    result = source.get_customer(customer_id)
    if result is None:
        return {"error": f"Customer {customer_id} not found"}
    result["accounts"] = source.get_accounts(customer_id)
    return result


def get_transaction_history(conn, account_id: str, limit: int = 50) -> list[dict]:
    return source.account_transactions(account_id, limit)


def get_network_graph(conn, account_id: str) -> dict:
    fp_list = source.device_fingerprints(account_id)
    if not fp_list:
        return {"nodes": [{"id": account_id, "type": "account"}], "edges": []}

    linked = source.accounts_by_fingerprints(fp_list)
    nodes = [{"id": account_id, "type": "account", "is_root": True}]
    edges = []
    for aid in linked:
        if aid != account_id:
            nodes.append({"id": aid, "type": "account"})
            edges.append({"source": account_id, "target": aid, "relation": "shared_device"})

    return {"nodes": nodes, "edges": edges}


def get_device_overlap(conn, account_id: str) -> list[dict]:
    fp_list = source.device_fingerprints(account_id)
    if not fp_list:
        return []
    return source.devices_by_fingerprints(fp_list, account_id)


def get_model_explanation(conn, transaction_id: str) -> list[dict]:
    """Return top-5 features by importance from the champion model.

    On genuine absence (no CHAMPION row, or its artifact missing on disk),
    returns an explicit "no explanation available" — never silently
    substitutes another model version. The Pattern worker prompt is told to
    respect this rather than narrate around it (see workers.py _PROMPTS['pattern']).
    """
    from common.config import get_config

    cfg = get_config()
    row = conn.execute(
        "SELECT model_version FROM deployments WHERE status='CHAMPION' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return [{"error": "no explanation available: no CHAMPION deployment found"}]

    model_version = row["model_version"]
    model_dir = os.path.join(PROJECT_ROOT, cfg["model"].get("model_dir", "models"))
    model_path = os.path.join(model_dir, f"aml_model_{model_version}.json")
    if not os.path.exists(model_path):
        return [{"error": f"no explanation available: CHAMPION artifact missing for {model_version}"}]

    try:
        import xgboost as xgb
        from ml.feature_engineering import FEATURE_COLS

        model = xgb.XGBClassifier()
        model.load_model(model_path)

        importances = model.feature_importances_
        ranked = sorted(zip(FEATURE_COLS, importances), key=lambda x: x[1], reverse=True)
        return [{"feature": f, "importance": round(float(i), 6)} for f, i in ranked[:5]]
    except Exception as e:
        return [{"error": f"no explanation available: {e}"}]


def get_drift_summary_tool(conn) -> dict:
    return drift_monitor.get_drift_summary(conn)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOLS: dict[str, Callable] = {
    "get_alert_detail": get_alert_detail,
    "get_customer_profile": get_customer_profile,
    "get_transaction_history": get_transaction_history,
    "get_network_graph": get_network_graph,
    "get_device_overlap": get_device_overlap,
    "get_model_explanation": get_model_explanation,
    "get_drift_summary": get_drift_summary_tool,
}
