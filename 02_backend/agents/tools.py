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
    linked = source.accounts_by_fingerprints(fp_list) if fp_list else []

    txns = source.account_transactions(account_id, limit=200)
    flow = source.fund_flow_edges(txns, account_id)

    # node set: root + device-linked accounts + every endpoint named by a flow edge
    node_ids = {account_id}
    node_ids.update(a for a in linked if a != account_id)
    for e in flow:
        node_ids.add(e["source"]); node_ids.add(e["target"])

    # classify: root is the collector; flow targets that aren't accounts are beneficiaries
    flow_targets = {e["target"] for e in flow if e["source"] == account_id}
    flow_sources = {e["source"] for e in flow if e["target"] == account_id}

    def _label(aid: str) -> str:
        acc = source.get_account(aid)
        if not acc:
            return aid
        cust = source.get_customer(acc.get("customer_id", ""))
        return (cust or {}).get("name") or aid

    nodes = []
    for nid in node_ids:
        label = _label(nid)
        if nid == account_id:
            nodes.append({"id": nid, "type": "collector", "is_root": True, "label": label})
        elif nid in flow_targets and nid not in linked:
            nodes.append({"id": nid, "type": "beneficiary", "label": label})
        elif nid in flow_sources or nid in linked:
            nodes.append({"id": nid, "type": "source", "label": label})
        else:
            nodes.append({"id": nid, "type": "account", "label": label})

    edges = [{"source": account_id, "target": aid, "relation": "shared_device"}
             for aid in linked if aid != account_id]
    edges.extend(flow)
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


# ---------------------------------------------------------------------------
# MCP verification tools — bridge configured MCP servers into the tool-calling
# loop. Aggregates every enabled server's tools into one OpenAI schema list plus
# an execute() that routes each call back to the owning server. Empty + no-op
# when nothing is configured (verification then fails soft).
# ---------------------------------------------------------------------------

def mcp_verification_tools() -> "tuple[list[dict], Callable]":
    from common import mcp_client

    schemas: list[dict] = []
    routing: dict[str, str] = {}   # tool_name -> server_name (last wins on clash)
    for srv in mcp_client.enabled_servers():
        listed = mcp_client.list_tools_sync(srv["name"])
        if not listed:
            continue
        for t in listed:
            routing[t["name"]] = srv["name"]
            schemas.append({"type": "function", "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            }})

    def execute(name: str, args: dict) -> str:
        server = routing.get(name)
        if not server:
            return f"error: unknown tool '{name}'"
        res = mcp_client.call_tool_sync(server, name, args)
        if res is None:
            return f"error: tool '{name}' unavailable"
        if isinstance(res, dict) and "error" in res:
            return f"error: {res['error']}"
        return res

    return schemas, execute
