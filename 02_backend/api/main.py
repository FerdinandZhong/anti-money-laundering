import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import json
import sqlite3
import threading
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from common.db import get_connection
from common import source
from common.tx_flags import derive_tx_flags
from agents.supervisor import run_investigation
from agents.tools import get_network_graph
from agents import llm_client
from ml.drift_monitor import get_drift_summary
from agents.retraining import run_retraining

# docs/openapi under /api so they're reachable through the frontend proxy
# (which only forwards /api/*) — the hosted app's Swagger UI lives at /api/docs.
app = FastAPI(
    title="AML Investigation Platform",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@app.on_event("startup")
def _bootstrap_alert_queue():
    """Self-heal an empty alert queue on boot: if no alerts exist but a champion
    model is available, score transactions to populate the queue. Runs in a
    background thread so it never blocks the CML readiness probe, and only when
    the queue is empty — so it's a no-op once alerts exist (idempotent)."""
    def _run():
        try:
            conn = get_connection()
            try:
                if conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]:
                    return  # queue already populated — nothing to do
                champ = conn.execute(
                    "SELECT model_version FROM deployments WHERE status='CHAMPION' "
                    "ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if champ is None:
                    print("[bootstrap] alert queue empty but no CHAMPION model — skipping auto-score")
                    return
                from ml.scorer import score_transactions
                created = score_transactions(conn)
                print(f"[bootstrap] alert queue was empty -> scored champion, created {created} alert(s)")
            finally:
                conn.close()
        except Exception as e:  # best-effort: never crash the app over this
            print(f"[bootstrap] auto-score skipped: {type(e).__name__}: {e}")

    threading.Thread(target=_run, name="bootstrap-scorer", daemon=True).start()


# ── Dashboard A: Alert Queue & Investigation ──────────────────────────────────

_ALERT_SORTS = {
    "risk_score": "risk_score DESC",
    "newest": "created_at DESC",
    "oldest": "created_at ASC",
}

_DISPOSITION_TO_STATUS = {
    "SUSPICIOUS": "PROPOSED",       # awaiting SAR/STR filing
    "FALSE_POSITIVE": "CLOSED",     # archived
    "NEEDS_MORE_INFO": "PENDING",   # stays visible, needs info
}


@app.get("/api/alerts")
def list_alerts(
    status: str = "OPEN",
    limit: int = 20,
    offset: int = 0,
    sort: str = "risk_score",
    conn=Depends(get_db),
):
    order_by = _ALERT_SORTS.get(sort, _ALERT_SORTS["risk_score"])
    rows = conn.execute(
        f"SELECT * FROM alerts WHERE status = ? ORDER BY {order_by} LIMIT ? OFFSET ?",
        (status, limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM alerts WHERE status = ?", (status,)).fetchone()[0]
    return {"alerts": [dict(r) for r in rows], "total": total}


@app.get("/api/alerts/counts")
def alert_counts(conn=Depends(get_db)):
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM alerts GROUP BY status").fetchall()
    counts = {"OPEN": 0, "PROPOSED": 0, "PENDING": 0, "CLOSED": 0}
    for r in rows:
        counts[r["status"]] = r["n"]
    return {"counts": counts}


@app.get("/api/alerts/{alert_id}")
def get_alert(alert_id: str, conn=Depends(get_db)):
    alert = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
    if not alert:
        raise HTTPException(404, "Alert not found")
    case = conn.execute("SELECT * FROM cases WHERE alert_id = ?", (alert_id,)).fetchone()
    return {"alert": dict(alert), "case": dict(case) if case else None}


def _json_list(raw) -> list:
    try:
        v = json.loads(raw) if raw else []
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _json_obj(raw) -> dict:
    try:
        v = json.loads(raw) if raw else {}
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


@app.get("/api/alerts/{alert_id}/detail")
def get_alert_detail(alert_id: str, conn=Depends(get_db)):
    """Flat, alert-driven case detail. Creates the case on first open so the
    investigate/dispose endpoints (which key off cases) work for any alert."""
    alert = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert = dict(alert)

    # Find or create the case for this alert (on-open case creation).
    case = conn.execute("SELECT * FROM cases WHERE alert_id = ?", (alert_id,)).fetchone()
    if case is None:
        case_id = "CASE-" + alert_id.replace("ALERT-", "", 1)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO cases (case_id, alert_id, customer_id, state, priority, created_at, updated_at) "
            "VALUES (?, ?, ?, 'ALERT_CREATED', ?, ?, ?)",
            (case_id, alert_id, alert["customer_id"], alert.get("risk_band") or "MEDIUM", now, now),
        )
        conn.commit()
        case = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    case = dict(case)
    case_id = case["case_id"]

    # Source (reference) data comes from the source layer (Impala/CSV), not SQLite.
    customer = source.get_customer(alert["customer_id"]) or {}

    customer_txns = source.customer_transactions(alert["customer_id"], limit=20)
    tx_ids = [t.get("transaction_id") for t in customer_txns if t.get("transaction_id")]
    tx_scores = {}
    tx_labels = {}
    if tx_ids:
        placeholders = ",".join("?" * len(tx_ids))
        tx_scores = {
            r["transaction_id"]: r["score"]
            for r in conn.execute(
                f"SELECT transaction_id, score FROM transaction_scores WHERE transaction_id IN ({placeholders})",
                tx_ids,
            ).fetchall()
        }
        # analyst per-transaction labels (ML training signal); None if unlabeled
        tx_labels = {
            r["transaction_id"]: r["label"]
            for r in conn.execute(
                f"SELECT transaction_id, label FROM transaction_labels WHERE transaction_id IN ({placeholders})",
                tx_ids,
            ).fetchall()
        }

    transactions = []
    for t in customer_txns:
        row = {
            "transaction_id": t.get("transaction_id"),
            "event_time": t.get("event_time"),
            "direction": t.get("direction"),
            "amount": t.get("amount"),
            "channel": t.get("channel"),
            "counterparty_name": t.get("counterparty_name"),
            "counterparty_country": t.get("counterparty_country"),
            "typology": t.get("typology"),
            "is_suspicious": t.get("is_suspicious"),
            "score": tx_scores.get(t.get("transaction_id")),
            "label": tx_labels.get(t.get("transaction_id")),
            "from_account_id": t.get("from_account_id"),
            "to_account_id": t.get("to_account_id"),
            "currency": t.get("currency"),
            "mcc": t.get("mcc"),
            "reference": t.get("reference"),
        }
        row["flags"] = derive_tx_flags(t, customer_txns)
        transactions.append(row)

    accounts = source.get_accounts(alert["customer_id"])
    root_account_id = accounts[0]["account_id"] if accounts else alert["customer_id"]
    try:
        network = get_network_graph(None, root_account_id)
    except Exception:
        network = {"nodes": [{"id": root_account_id, "type": "collector", "is_root": True}], "edges": []}

    return {
        "case_id": case_id,
        "alert_id": alert_id,
        "customer_id": alert["customer_id"],
        "customer_name": customer.get("name", alert["customer_id"]),
        "customer_kyc_rating": customer.get("risk_rating", "MEDIUM"),
        "risk_score": alert.get("risk_score", 0.0),
        "risk_band": alert.get("risk_band", "MEDIUM"),
        "triggered_rules": _json_list(alert.get("triggered_rules")),
        "reason_codes": _json_list(alert.get("reason_codes")),
        "top_features": _json_obj(alert.get("top_features")),
        "model_version": alert.get("model_version"),
        "account_age_days": customer.get("account_age_days", 0),
        "expected_monthly_turnover": customer.get("expected_monthly_turnover", 0),
        "transactions": transactions,
        "network": network,
        "analysis": case.get("analysis"),
        "analyzed_at": case.get("analyzed_at"),
        "disposition": case.get("disposition"),
    }


class InvestigateBody(BaseModel):
    stream: bool = True


@app.post("/api/cases/{case_id}/investigate")
def investigate_case(case_id: str, body: InvestigateBody, conn=Depends(get_db)):
    case = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if not case:
        raise HTTPException(404, "Case not found")
    case = dict(case)

    alert_id    = case["alert_id"]
    customer_id = case["customer_id"]

    # first account for this customer (needed by tx/network tools)
    accounts   = source.get_accounts(customer_id)
    account_id = accounts[0]["account_id"] if accounts else customer_id

    def event_stream():
        narrative_parts: list[str] = []
        findings_parts: list[str] = []
        for evt in run_investigation(case_id, alert_id, customer_id, account_id):
            if evt.get("type") == "token":
                narrative_parts.append(evt.get("text", ""))
            elif evt.get("type") == "worker_done":
                findings_parts.append(f"[{evt.get('worker', '').upper()}]\n{evt.get('findings', '')}")
            elif evt.get("type") == "done":
                analysis = ("\n\n".join(findings_parts) + "\n\n" + "".join(narrative_parts)).strip()
                write_conn = get_connection()
                try:
                    write_conn.execute(
                        "UPDATE cases SET analysis = ?, analyzed_at = ? WHERE case_id = ?",
                        (analysis, datetime.now(timezone.utc).isoformat(), case_id),
                    )
                    write_conn.commit()
                finally:
                    write_conn.close()
            yield f"data: {json.dumps(evt)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class DisposeBody(BaseModel):
    disposition: str
    notes: str = ""
    adjudicator: str = ""


@app.post("/api/cases/{case_id}/dispose")
def dispose_case(case_id: str, body: DisposeBody, conn=Depends(get_db)):
    if body.disposition not in ("SUSPICIOUS", "FALSE_POSITIVE", "NEEDS_MORE_INFO"):
        raise HTTPException(400, "Invalid disposition")
    case = conn.execute("SELECT 1 FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if not case:
        raise HTTPException(404, "Case not found")

    annotation_id = f"ANN-{uuid4().hex[:8].upper()}"
    conn.execute(
        "INSERT INTO annotations (annotation_id, case_id, disposition, notes, adjudicator) VALUES (?, ?, ?, ?, ?)",
        (annotation_id, case_id, body.disposition, body.notes, body.adjudicator),
    )
    conn.execute(
        "UPDATE cases SET state = 'CLOSED', disposition = ?, updated_at = ? WHERE case_id = ?",
        (body.disposition, datetime.now(timezone.utc).isoformat(), case_id),
    )
    conn.execute(
        "UPDATE alerts SET status = ? "
        "WHERE alert_id = (SELECT alert_id FROM cases WHERE case_id = ?)",
        (_DISPOSITION_TO_STATUS[body.disposition], case_id),
    )
    conn.commit()

    return {"ok": True, "annotation_id": annotation_id}


def _bg_retrain(triggered_by: str = "threshold"):
    """Drain the retraining agent workflow in a daemon thread (non-streaming).
    The workflow opens its own DB connection and handles the local fallback."""
    try:
        for evt in run_retraining(triggered_by):
            if evt.get("type") != "token":
                print(f"[retrain] {evt}")
    except Exception as e:
        print(f"[bg retrain] error: {e}")


class TxLabel(BaseModel):
    transaction_id: str
    label: int | None = None  # 1=suspicious, 0=clean, None=unset (delete)


class TxLabelsBody(BaseModel):
    labels: list[TxLabel]
    labeled_by: str = ""


@app.post("/api/cases/{case_id}/transaction-labels")
def set_transaction_labels(case_id: str, body: TxLabelsBody, conn=Depends(get_db)):
    """Upsert analyst per-transaction labels (the ML training signal). label=None
    clears a previously-set label. Account-level disposition is separate (dispose)."""
    case = conn.execute("SELECT 1 FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if not case:
        raise HTTPException(404, "Case not found")

    upserts = 0
    deletes = 0
    for item in body.labels:
        if item.label is None:
            conn.execute("DELETE FROM transaction_labels WHERE transaction_id = ?", (item.transaction_id,))
            deletes += 1
        else:
            if item.label not in (0, 1):
                raise HTTPException(400, f"Invalid label {item.label}; must be 0 or 1")
            conn.execute(
                "INSERT OR REPLACE INTO transaction_labels (transaction_id, label, case_id, labeled_by) "
                "VALUES (?, ?, ?, ?)",
                (item.transaction_id, item.label, case_id, body.labeled_by),
            )
            upserts += 1
    conn.commit()
    return {"ok": True, "labeled": upserts, "cleared": deletes}


@app.get("/api/cases/{case_id}/evidence")
def get_evidence(case_id: str, conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT * FROM evidence WHERE case_id = ? ORDER BY created_at DESC",
        (case_id,),
    ).fetchall()
    return {"evidence": [dict(r) for r in rows]}


# ── Customer-centric endpoints (agent / MCP surface) ──────────────────────────
# Read-only by customer_id, EXCEPT the investigate POST. The MCP server
# (mcp_server/) is a thin HTTP client over exactly these routes.

_ACTIVE_STATUSES = ("OPEN", "PROPOSED", "PENDING")


def _resolve_alert_and_case(conn, customer_id: str, create: bool = False):
    """(alert|None, case|None) for a customer — highest-risk active alert first.
    create=True lazily creates the case (mirrors get_alert_detail); create=False
    never mutates."""
    alert = conn.execute(
        "SELECT * FROM alerts WHERE customer_id = ? "
        "ORDER BY (status IN ('OPEN','PROPOSED','PENDING')) DESC, risk_score DESC, created_at DESC LIMIT 1",
        (customer_id,),
    ).fetchone()
    if alert is None:
        return None, None
    alert = dict(alert)
    case = conn.execute("SELECT * FROM cases WHERE alert_id = ?", (alert["alert_id"],)).fetchone()
    if case is None and create:
        case_id = "CASE-" + alert["alert_id"].replace("ALERT-", "", 1)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO cases (case_id, alert_id, customer_id, state, priority, created_at, updated_at) "
            "VALUES (?, ?, ?, 'ALERT_CREATED', ?, ?, ?)",
            (case_id, alert["alert_id"], customer_id, alert.get("risk_band") or "MEDIUM", now, now),
        )
        conn.commit()
        case = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    return alert, (dict(case) if case else None)


def _customer_transactions(conn, customer_id: str, limit: int) -> list[dict]:
    """Customer transactions + model scores + analyst labels, sorted by score DESC
    (unscored last). Same assembly as get_alert_detail."""
    customer_txns = source.customer_transactions(customer_id, limit=limit)
    tx_ids = [t.get("transaction_id") for t in customer_txns if t.get("transaction_id")]
    tx_scores, tx_labels = {}, {}
    if tx_ids:
        ph = ",".join("?" * len(tx_ids))
        tx_scores = {r["transaction_id"]: r["score"] for r in conn.execute(
            f"SELECT transaction_id, score FROM transaction_scores WHERE transaction_id IN ({ph})", tx_ids)}
        tx_labels = {r["transaction_id"]: r["label"] for r in conn.execute(
            f"SELECT transaction_id, label FROM transaction_labels WHERE transaction_id IN ({ph})", tx_ids)}
    rows = []
    for t in customer_txns:
        tid = t.get("transaction_id")
        rows.append({
            "transaction_id": tid, "event_time": t.get("event_time"), "direction": t.get("direction"),
            "amount": t.get("amount"), "channel": t.get("channel"),
            "counterparty_name": t.get("counterparty_name"), "counterparty_country": t.get("counterparty_country"),
            "typology": t.get("typology"), "is_suspicious": t.get("is_suspicious"),
            "score": tx_scores.get(tid), "label": tx_labels.get(tid),
            "flags": derive_tx_flags(t, customer_txns),
        })
    rows.sort(key=lambda r: (r["score"] is not None, r["score"] or 0.0), reverse=True)
    return rows


@app.get("/api/customers/{customer_id}/suspicious")
def customer_suspicious(customer_id: str, conn=Depends(get_db)):
    """Is this customer suspicious? True if any alert is OPEN/PROPOSED/PENDING.
    Read-only."""
    rows = [dict(r) for r in conn.execute(
        "SELECT alert_id, risk_score, risk_band, status, triggered_rules, reason_codes, created_at "
        "FROM alerts WHERE customer_id = ? ORDER BY risk_score DESC", (customer_id,)).fetchall()]
    alerts = [{
        "alert_id": r["alert_id"], "risk_score": r["risk_score"], "risk_band": r["risk_band"],
        "status": r["status"], "triggered_rules": _json_list(r["triggered_rules"]),
        "reason_codes": _json_list(r["reason_codes"]), "created_at": r["created_at"],
    } for r in rows]
    active = [a for a in alerts if a["status"] in _ACTIVE_STATUSES]
    return {
        "customer_id": customer_id, "suspicious": bool(active), "alerts": alerts,
        "highest_risk_score": max((a["risk_score"] or 0.0 for a in alerts), default=None),
    }


@app.get("/api/customers/{customer_id}/transactions")
def customer_transactions(customer_id: str, limit: int = 20, conn=Depends(get_db)):
    """Customer transactions ranked by model risk score (unscored last). Read-only."""
    txns = _customer_transactions(conn, customer_id, limit)
    return {"customer_id": customer_id, "count": len(txns), "transactions": txns}


@app.get("/api/customers/{customer_id}/case-status")
def customer_case_status(customer_id: str, conn=Depends(get_db)):
    """Analyst-processing status for the customer's case. Read-only — does NOT
    create a case if none exists yet."""
    alert, case = _resolve_alert_and_case(conn, customer_id, create=False)
    if alert is None:
        return {"customer_id": customer_id, "processed": False, "reason": "no alert for customer"}
    if case is None:
        return {"customer_id": customer_id, "alert_id": alert["alert_id"],
                "processed": False, "reason": "alert not yet opened as a case"}
    annotations = [dict(r) for r in conn.execute(
        "SELECT disposition, notes, adjudicator, created_at FROM annotations "
        "WHERE case_id = ? ORDER BY created_at DESC", (case["case_id"],)).fetchall()]
    return {
        "customer_id": customer_id, "alert_id": alert["alert_id"], "case_id": case["case_id"],
        "processed": bool(case.get("disposition") or case.get("analyzed_at")),
        "state": case.get("state"), "disposition": case.get("disposition"),
        "analyzed_at": case.get("analyzed_at"), "has_analysis": bool(case.get("analysis")),
        "annotations": annotations,
    }


@app.get("/api/customers/{customer_id}/network")
def customer_network(customer_id: str, conn=Depends(get_db)):
    """Fund-flow + shared-device network graph around the customer's primary
    account: {nodes, edges}. Read-only."""
    accounts = source.get_accounts(customer_id)
    root = accounts[0]["account_id"] if accounts else customer_id
    try:
        return get_network_graph(None, root)
    except Exception:
        return {"nodes": [{"id": root, "type": "collector", "is_root": True}], "edges": []}


@app.post("/api/customers/{customer_id}/investigate")
def customer_investigate(customer_id: str, conn=Depends(get_db)):
    """Run the multi-agent AI investigation for the customer's case and return the
    analysis (non-streaming). THE ONLY MUTATION on this surface: writes the
    analysis + timestamp to the case, exactly like the SSE investigate endpoint.
    Requires an LLM configured. Returns {case_id, analysis, verdicts, worker_findings}."""
    alert, case = _resolve_alert_and_case(conn, customer_id, create=True)
    if alert is None:
        raise HTTPException(404, f"No alert for customer {customer_id}; nothing to investigate")
    case_id = case["case_id"]
    accounts = source.get_accounts(customer_id)
    account_id = accounts[0]["account_id"] if accounts else customer_id

    narrative_parts, worker_findings, verdicts = [], [], []
    for evt in run_investigation(case_id, alert["alert_id"], customer_id, account_id):
        t = evt.get("type")
        if t == "token":
            narrative_parts.append(evt.get("text", ""))
        elif t == "worker_done":
            worker_findings.append({"worker": evt.get("worker"), "findings": evt.get("findings", "")})
        elif t == "verdict":
            verdicts.append({"claim": evt.get("claim"), "verdict": evt.get("verdict"),
                             "sources": evt.get("sources", [])})
    findings_block = "\n\n".join(f"[{w['worker'].upper()}]\n{w['findings']}" for w in worker_findings)
    analysis = (findings_block + "\n\n" + "".join(narrative_parts)).strip()

    conn.execute("UPDATE cases SET analysis = ?, analyzed_at = ? WHERE case_id = ?",
                 (analysis, datetime.now(timezone.utc).isoformat(), case_id))
    conn.commit()
    return {"case_id": case_id, "analysis": analysis, "verdicts": verdicts,
            "worker_findings": worker_findings}


# ── Dashboard B: Model & Data ─────────────────────────────────────────────────

@app.get("/api/model/runs")
def model_runs(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT * FROM model_runs ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    return {"runs": [dict(r) for r in rows]}


@app.get("/api/model/deployments")
def model_deployments(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT * FROM deployments WHERE status IN ('CHAMPION', 'SHADOW', 'CANARY')"
    ).fetchall()
    return {"deployments": [dict(r) for r in rows]}


@app.get("/api/model/drift")
def model_drift(conn=Depends(get_db)):
    # get_drift_summary → {feat: {psi, drift_detected, threshold}}; reshape to the
    # typed DriftResult contract the frontend expects ({features:[...], computed_at}).
    summary = get_drift_summary(conn)
    features = [{"feature": k, "psi": (v.get("psi", 0.0) if isinstance(v, dict) else v)}
                for k, v in summary.items()]
    return {"features": features, "computed_at": datetime.now(timezone.utc).isoformat()}


@app.post("/api/model/retrain")
def retrain():
    """Fire-and-forget: run the retrain → canary → promote workflow in a thread."""
    t = threading.Thread(target=_bg_retrain, args=("manual",), daemon=True)
    t.start()
    return {"ok": True, "message": "Training started"}


@app.post("/api/model/retrain/stream")
def retrain_stream():
    """Same workflow, streamed as SSE so Dashboard B can show live
    create-job → run → canary → promote progress. run_retraining opens its own
    DB connection, so no get_db dependency here (it would close mid-stream)."""
    def event_stream():
        for evt in run_retraining("manual"):
            yield f"data: {json.dumps(evt)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/stats")
def stats(conn=Depends(get_db)):
    total_alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    open_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE status = 'OPEN'").fetchone()[0]
    critical_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE risk_band = 'CRITICAL'").fetchone()[0]
    total_cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    total_annotations = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
    human_labelled = conn.execute("SELECT COUNT(*) FROM transaction_labels").fetchone()[0]
    return {
        "total_alerts": total_alerts,
        "open_alerts": open_alerts,
        "critical_alerts": critical_alerts,
        "total_cases": total_cases,
        "total_annotations": total_annotations,
        "suspicious_labelled": source.count_suspicious(),
        "human_labelled": human_labelled,
        "total_labelled": source.count_transactions(),
    }


@app.get("/api/model/score-histogram")
def score_histogram(conn=Depends(get_db)):
    rows = conn.execute("SELECT score FROM transaction_scores").fetchall()
    buckets = [0] * 10
    for r in rows:
        idx = min(int(r["score"] * 10), 9)
        buckets[max(idx, 0)] += 1
    return {
        "bins": [
            {"bucket": f"{i/10:.1f}–{(i+1)/10:.1f}", "count": buckets[i]}
            for i in range(10)
        ]
    }


@app.get("/api/model/alert-bands")
def alert_bands(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT risk_band, COUNT(*) AS n FROM alerts GROUP BY risk_band"
    ).fetchall()
    counts = {r["risk_band"]: r["n"] for r in rows}
    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    return {"bands": [{"band": b, "count": counts[b]} for b in order if b in counts]}


# ── LLM config ───────────────────────────────────────────────────────────────

@app.get("/api/config/llm")
def get_llm_config(conn=Depends(get_db)):
    from common.config import get_config
    cfg = get_config()["llm"]
    from agents.llm_client import _provider_override
    providers = [k for k in cfg if isinstance(cfg[k], dict)]
    # A registered model (Models view) is the source of truth when one is active.
    active = conn.execute(
        "SELECT alias, model_identifier FROM llm_models WHERE is_active=1 LIMIT 1"
    ).fetchone()
    if active:
        provider, model, endpoint = active["alias"], active["model_identifier"], ""
    else:
        provider = _provider_override or cfg.get("provider", "caii")
        pcfg = cfg.get(provider, {})
        model, endpoint = pcfg.get("model", ""), pcfg.get("endpoint", "")
    return {
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "available_providers": {
            p: {"model": cfg[p].get("model", ""), "endpoint": cfg[p].get("endpoint", "")}
            for p in providers
        },
    }


@app.get("/api/config/llm/caii-endpoints")
def caii_endpoints():
    """Live CAII inference endpoints discovered from the workspace (empty locally)."""
    from common.caii import list_caii_endpoints
    return {"endpoints": list_caii_endpoints()}


class LlmProviderBody(BaseModel):
    provider: str
    base_url: str | None = None   # optional: pin a specific CAII endpoint
    model: str | None = None


@app.post("/api/config/llm")
def set_llm_config(body: LlmProviderBody):
    from common.config import get_config
    cfg = get_config()["llm"]
    if body.provider not in cfg or not isinstance(cfg[body.provider], dict):
        raise HTTPException(400, f"Unknown provider: {body.provider}")
    llm_client.set_provider(body.provider)
    if body.base_url and body.model:
        llm_client.set_endpoint(body.base_url, body.model)
        return {"ok": True, "provider": body.provider, "model": body.model, "endpoint": body.base_url}
    return {"ok": True, "provider": body.provider, "model": cfg[body.provider].get("model", "")}


# ── Registered LLM models (Models view) ───────────────────────────────────────

class RegisterModelBody(BaseModel):
    alias: str
    provider: str                       # openai | openai_compatible | caii | vllm | ollama
    model_identifier: str
    api_base: str | None = None
    api_key: str | None = None


def _mask_key(k: str | None) -> str:
    if not k:
        return ""
    return ("••••" + k[-4:]) if len(k) > 4 else "••••"


@app.get("/api/config/llm/models")
def list_llm_models(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT id, alias, provider, model_identifier, api_base, api_key, is_active "
        "FROM llm_models ORDER BY created_at DESC"
    ).fetchall()
    return {"models": [{**dict(r), "api_key": _mask_key(r["api_key"])} for r in rows]}


@app.post("/api/config/llm/models")
def register_llm_model(body: RegisterModelBody, conn=Depends(get_db)):
    """Register a model and make it active. Agents resolve the active row on each call."""
    if not body.alias.strip() or not body.model_identifier.strip():
        raise HTTPException(400, "alias and model_identifier are required")
    try:
        conn.execute("UPDATE llm_models SET is_active=0")
        conn.execute(
            "INSERT INTO llm_models (alias, provider, model_identifier, api_base, api_key, is_active) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (body.alias.strip(), body.provider, body.model_identifier.strip(),
             body.api_base, body.api_key),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Alias '{body.alias}' already exists")
    return {"ok": True, "alias": body.alias, "model": body.model_identifier, "active": True}


class UpdateModelBody(BaseModel):
    alias: str | None = None
    provider: str | None = None
    model_identifier: str | None = None
    api_base: str | None = None
    api_key: str | None = None   # blank/omitted = keep existing (list masks it)


@app.put("/api/config/llm/models/{model_id}")
def update_llm_model(model_id: int, body: UpdateModelBody, conn=Depends(get_db)):
    """Edit a registered model (e.g. fix a typo'd api_base). api_key is kept when
    left blank, since the list only ever returns a masked key."""
    row = conn.execute("SELECT * FROM llm_models WHERE id=?", (model_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Model not found")
    cur = dict(row)
    alias = (body.alias or cur["alias"]).strip()
    provider = body.provider or cur["provider"]
    model_identifier = (body.model_identifier or cur["model_identifier"]).strip()
    # form always sends api_base; empty string clears it to NULL (OpenAI default)
    api_base = (body.api_base or "").strip() or None
    api_key = body.api_key.strip() if (body.api_key and body.api_key.strip()) else cur["api_key"]
    try:
        conn.execute(
            "UPDATE llm_models SET alias=?, provider=?, model_identifier=?, api_base=?, api_key=? WHERE id=?",
            (alias, provider, model_identifier, api_base, api_key, model_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Alias '{alias}' already exists")
    return {"ok": True, "id": model_id, "alias": alias}


@app.post("/api/config/llm/models/{model_id}/activate")
def activate_llm_model(model_id: int, conn=Depends(get_db)):
    row = conn.execute("SELECT alias, model_identifier FROM llm_models WHERE id=?", (model_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Model not found")
    conn.execute("UPDATE llm_models SET is_active=0")
    conn.execute("UPDATE llm_models SET is_active=1 WHERE id=?", (model_id,))
    conn.commit()
    return {"ok": True, "alias": row["alias"], "model": row["model_identifier"], "active": True}


@app.post("/api/config/llm/models/{model_id}/test")
def test_llm_model(model_id: int, conn=Depends(get_db)):
    """Probe a registered model's endpoint without changing which model is active."""
    row = conn.execute(
        "SELECT provider, model_identifier, api_base, api_key FROM llm_models WHERE id=?", (model_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Model not found")
    ok, message = llm_client.probe(row["api_base"], row["model_identifier"], row["api_key"])
    return {"ok": ok, "message": message}


# ── MCP tool servers (Tools view) ─────────────────────────────────────────────

class ToolConfigBody(BaseModel):
    name: str
    url: str
    api_key: str | None = None   # blank/omitted on edit = keep existing (list masks it)
    enabled: bool = True


class EmbeddedConfigBody(BaseModel):
    params: dict = {}
    enabled: bool = True


@app.get("/api/config/tools")
def list_tools(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT id, kind, name, transport, url, api_key, enabled "
        "FROM tool_config ORDER BY created_at DESC"
    ).fetchall()
    return {"tools": [{**dict(r), "api_key": _mask_key(r["api_key"])} for r in rows]}


@app.post("/api/config/tools")
def register_tool(body: ToolConfigBody, conn=Depends(get_db)):
    """Register a remote streamable-HTTP MCP server."""
    if not body.name.strip() or not body.url.strip():
        raise HTTPException(400, "name and url are required")
    try:
        conn.execute(
            "INSERT INTO tool_config (kind, name, transport, url, api_key, enabled) "
            "VALUES ('mcp_server', ?, 'http', ?, ?, ?)",
            (body.name.strip(), body.url.strip(), body.api_key, 1 if body.enabled else 0),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Tool server '{body.name}' already exists")
    return {"ok": True, "name": body.name}


@app.put("/api/config/tools/{tool_id}")
def update_tool(tool_id: int, body: ToolConfigBody, conn=Depends(get_db)):
    """Edit a server. api_key is kept when left blank (the list only returns a masked key)."""
    row = conn.execute("SELECT * FROM tool_config WHERE id=?", (tool_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Tool server not found")
    api_key = body.api_key.strip() if (body.api_key and body.api_key.strip()) else row["api_key"]
    try:
        conn.execute(
            "UPDATE tool_config SET name=?, url=?, api_key=?, enabled=? WHERE id=?",
            (body.name.strip(), body.url.strip(), api_key, 1 if body.enabled else 0, tool_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Tool server '{body.name}' already exists")
    return {"ok": True, "id": tool_id, "name": body.name}


@app.post("/api/config/tools/{tool_id}/test")
def test_tool(tool_id: int, conn=Depends(get_db)):
    """Connect to the MCP server and list its tools. Never changes config."""
    from common import mcp_client
    row = conn.execute(
        "SELECT url, api_key FROM tool_config WHERE id=?", (tool_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Tool server not found")
    ok, res = mcp_client.probe(row["url"], row["api_key"])
    if ok:
        return {"ok": True, "tools": [t["name"] for t in res], "count": len(res)}
    return {"ok": False, "message": res}


# ── embedded MCP servers (fixed registry, parameter-driven) ──────────────────

_SECRET_KEYS = {"impala_password", "api_key"}
_MASK = "•••"


def _embedded_row(conn, name: str):
    return conn.execute(
        "SELECT * FROM tool_config WHERE name=? AND kind='embedded'", (name,)
    ).fetchone()


@app.get("/api/config/embedded")
def list_embedded(conn=Depends(get_db)):
    from common import mcp_client
    servers = []
    for name, spec in mcp_client.EMBEDDED_SERVERS.items():
        row = _embedded_row(conn, name)
        stored = json.loads(row["params"]) if row and row["params"] else {}
        masked = {k: (_MASK if k in _SECRET_KEYS and v else v) for k, v in stored.items()}
        servers.append({
            "name": name,
            "enabled": bool(row["enabled"]) if row else False,
            "configured": mcp_client.embedded_params(name) is not None,
            "params": masked,
            "required": spec["required"],
            "fields": list(spec["env_map"].keys()),
        })
    return {"servers": servers}


@app.put("/api/config/embedded/{name}")
def update_embedded(name: str, body: EmbeddedConfigBody, conn=Depends(get_db)):
    from common import mcp_client
    if name not in mcp_client.EMBEDDED_SERVERS:
        raise HTTPException(404, f"unknown embedded server '{name}'")
    row = _embedded_row(conn, name)
    stored = json.loads(row["params"]) if row and row["params"] else {}
    merged = dict(stored)
    for k, v in (body.params or {}).items():
        v = str(v or "").strip()
        if k in _SECRET_KEYS and (not v or v == _MASK):
            continue                      # blank/masked secret = keep existing
        merged[k] = v
    if row:
        conn.execute("UPDATE tool_config SET params=?, enabled=? WHERE id=?",
                     (json.dumps(merged), 1 if body.enabled else 0, row["id"]))
    else:
        conn.execute(
            "INSERT INTO tool_config (kind, name, transport, params, enabled) "
            "VALUES ('embedded', ?, 'stdio', ?, ?)",
            (name, json.dumps(merged), 1 if body.enabled else 0))
    conn.commit()
    mcp_client.reset_embedded(name)
    from common import source
    reset = getattr(source, "reset_backend", None)   # arrives in Task 4
    if reset:
        reset()
    return {"ok": True, "name": name}


@app.post("/api/config/embedded/{name}/test")
def test_embedded(name: str, body: EmbeddedConfigBody, conn=Depends(get_db)):
    from common import mcp_client
    if name not in mcp_client.EMBEDDED_SERVERS:
        raise HTTPException(404, f"unknown embedded server '{name}'")
    row = _embedded_row(conn, name)
    stored = json.loads(row["params"]) if row and row["params"] else {}
    params = dict(stored)
    for k, v in (body.params or {}).items():
        v = str(v or "").strip()
        if v and v != _MASK:
            params[k] = v
    ok, res = mcp_client.probe_embedded(name, params)
    if ok:
        return {"ok": True, "tools": [t["name"] for t in res], "count": len(res)}
    return {"ok": False, "message": str(res)}


# ── Utility ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health(conn=Depends(get_db)):
    conn.execute("SELECT 1").fetchone()  # verify DB reachable
    return {"status": "ok", "db": "connected", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/health/environment")
def health_environment(conn=Depends(get_db)):
    """First-run health check: surfaces today's silent fallbacks (CSV-when-
    Impala-expected, unreachable model, missing champion artifact) as explicit
    booleans instead of quiet degradation."""
    from common.config import get_config

    try:
        source_backend = source.backend()
        source_ok = True
    except Exception:  # noqa: BLE001 — backend=impala forced but unreachable
        source_backend = "csv"
        source_ok = False

    cfg = get_config()["llm"]
    active = conn.execute(
        "SELECT alias, model_identifier, api_base, api_key FROM llm_models WHERE is_active=1 LIMIT 1"
    ).fetchone()
    if active:
        alias, model, base_url, api_key = active["alias"], active["model_identifier"], active["api_base"], active["api_key"]
    else:
        provider = llm_client._provider_override or cfg.get("provider", "caii")
        pcfg = cfg.get(provider, {})
        alias, model, base_url, api_key = provider, pcfg.get("model", ""), pcfg.get("endpoint"), pcfg.get("api_key")
    reachable, message = llm_client.probe(base_url, model, api_key)

    dep = conn.execute(
        "SELECT model_version FROM deployments WHERE status='CHAMPION' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    champion_artifact_present = False
    if dep:
        model_dir = os.path.join(PROJECT_ROOT, get_config()["model"].get("model_dir", "models"))
        champion_artifact_present = os.path.exists(
            os.path.join(model_dir, f"aml_model_{dep['model_version']}.json")
        )

    return {
        "source_backend": source_backend,
        "source_ok": source_ok,
        "active_model": {"alias": alias, "reachable": reachable, "message": message},
        "champion_artifact_present": champion_artifact_present,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("02_backend.api.main:app", host="0.0.0.0", port=8000, reload=True)
