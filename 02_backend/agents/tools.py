import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import json
from typing import Callable

from ml import drift_monitor


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
    row = conn.execute(
        "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if row is None:
        return {"error": f"Customer {customer_id} not found"}
    result = dict(row)
    accounts = conn.execute(
        "SELECT * FROM accounts WHERE customer_id = ?", (customer_id,)
    ).fetchall()
    result["accounts"] = [dict(a) for a in accounts]
    return result


def get_transaction_history(conn, account_id: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM transactions
           WHERE from_account_id = ? OR to_account_id = ?
           ORDER BY event_time DESC LIMIT ?""",
        (account_id, account_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_network_graph(conn, account_id: str) -> dict:
    # Find device fingerprints used by this account
    fps = conn.execute(
        "SELECT DISTINCT device_fingerprint FROM devices WHERE account_id = ? AND device_fingerprint IS NOT NULL",
        (account_id,),
    ).fetchall()
    fp_list = [r["device_fingerprint"] for r in fps]

    if not fp_list:
        return {"nodes": [{"id": account_id, "type": "account"}], "edges": []}

    placeholders = ",".join("?" * len(fp_list))
    linked = conn.execute(
        f"SELECT DISTINCT account_id FROM devices WHERE device_fingerprint IN ({placeholders}) AND account_id IS NOT NULL",
        fp_list,
    ).fetchall()

    nodes = [{"id": account_id, "type": "account", "is_root": True}]
    edges = []
    for r in linked:
        aid = r["account_id"]
        if aid != account_id:
            nodes.append({"id": aid, "type": "account"})
            edges.append({"source": account_id, "target": aid, "relation": "shared_device"})

    return {"nodes": nodes, "edges": edges}


def get_device_overlap(conn, account_id: str) -> list[dict]:
    fps = conn.execute(
        "SELECT DISTINCT device_fingerprint FROM devices WHERE account_id = ? AND device_fingerprint IS NOT NULL",
        (account_id,),
    ).fetchall()
    fp_list = [r["device_fingerprint"] for r in fps]
    if not fp_list:
        return []
    placeholders = ",".join("?" * len(fp_list))
    rows = conn.execute(
        f"""SELECT d.account_id, d.device_fingerprint, d.ip_address
            FROM devices d
            WHERE d.device_fingerprint IN ({placeholders})
              AND d.account_id != ?""",
        fp_list + [account_id],
    ).fetchall()
    return [dict(r) for r in rows]


def get_model_explanation(conn, transaction_id: str) -> list[dict]:
    """Return top-5 features by importance from the champion model."""
    try:
        import xgboost as xgb
        from ml.feature_engineering import FEATURE_COLS
        from common.config import get_config

        cfg = get_config()
        row = conn.execute(
            "SELECT model_version FROM deployments WHERE status='CHAMPION' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return [{"error": "No CHAMPION deployment found"}]

        model_version = row["model_version"]
        model_dir = os.path.join(PROJECT_ROOT, cfg["model"].get("model_dir", "models"))
        model_path = os.path.join(model_dir, f"aml_model_{model_version}.json")

        model = xgb.XGBClassifier()
        model.load_model(model_path)

        importances = model.feature_importances_
        ranked = sorted(zip(FEATURE_COLS, importances), key=lambda x: x[1], reverse=True)
        return [{"feature": f, "importance": round(float(i), 6)} for f, i in ranked[:5]]
    except Exception as e:
        return [{"error": str(e)}]


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
