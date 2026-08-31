import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import threading
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from common.db import get_connection
from agents.investigator import run_investigation
from ml.drift_monitor import get_drift_summary
from ml.train import train_model

app = FastAPI(title="AML Investigation Platform")

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


# ── Dashboard A: Alert Queue & Investigation ──────────────────────────────────

@app.get("/api/alerts")
def list_alerts(status: str = "OPEN", limit: int = 20, offset: int = 0, conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT * FROM alerts WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (status, limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM alerts WHERE status = ?", (status,)).fetchone()[0]
    return {"alerts": [dict(r) for r in rows], "total": total}


@app.get("/api/alerts/{alert_id}")
def get_alert(alert_id: str, conn=Depends(get_db)):
    alert = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
    if not alert:
        raise HTTPException(404, "Alert not found")
    case = conn.execute("SELECT * FROM cases WHERE alert_id = ?", (alert_id,)).fetchone()
    return {"alert": dict(alert), "case": dict(case) if case else None}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, conn=Depends(get_db)):
    case = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if not case:
        raise HTTPException(404, "Case not found")
    case = dict(case)

    alert = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (case["alert_id"],)).fetchone()
    customer = conn.execute("SELECT * FROM customers WHERE customer_id = ?", (case["customer_id"],)).fetchone()

    # Recent 20 transactions for this customer's accounts
    txns = conn.execute(
        """SELECT t.* FROM transactions t
           JOIN accounts a ON t.from_account_id = a.account_id
           JOIN customers c ON a.customer_id = c.customer_id
           WHERE c.customer_id = ?
           ORDER BY t.event_time DESC LIMIT 20""",
        (case["customer_id"],),
    ).fetchall()

    return {
        "case": case,
        "alert": dict(alert) if alert else None,
        "customer": dict(customer) if customer else None,
        "transactions": [dict(t) for t in txns],
    }


class InvestigateBody(BaseModel):
    stream: bool = True


@app.post("/api/cases/{case_id}/investigate")
def investigate_case(case_id: str, body: InvestigateBody, conn=Depends(get_db)):
    case = conn.execute("SELECT 1 FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if not case:
        raise HTTPException(404, "Case not found")

    result = run_investigation(case_id, conn, stream=body.stream)

    if body.stream:
        def event_stream():
            for token in result:
                yield f"data: {token}\n\n"
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return {"report": result}


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
        "UPDATE cases SET state = 'CLOSED', updated_at = ? WHERE case_id = ?",
        (datetime.now(timezone.utc).isoformat(), case_id),
    )
    conn.commit()

    total_annotations = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
    if total_annotations >= 500:
        t = threading.Thread(target=_bg_retrain, daemon=True)
        t.start()

    return {"ok": True, "annotation_id": annotation_id}


def _bg_retrain():
    conn = get_connection()
    try:
        train_model(conn)
    except Exception as e:
        print(f"[bg retrain] error: {e}")
    finally:
        conn.close()


@app.get("/api/cases/{case_id}/evidence")
def get_evidence(case_id: str, conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT * FROM evidence WHERE case_id = ? ORDER BY created_at DESC",
        (case_id,),
    ).fetchall()
    return {"evidence": [dict(r) for r in rows]}


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
    return get_drift_summary(conn)


@app.post("/api/model/retrain")
def retrain(conn=Depends(get_db)):  # conn needed to satisfy lifespan; thread opens its own
    t = threading.Thread(target=_bg_retrain, daemon=True)
    t.start()
    return {"ok": True, "message": "Training started"}


@app.get("/api/stats")
def stats(conn=Depends(get_db)):
    total_alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    open_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE status = 'OPEN'").fetchone()[0]
    critical_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE risk_band = 'CRITICAL'").fetchone()[0]
    total_cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    total_annotations = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
    return {
        "total_alerts": total_alerts,
        "open_alerts": open_alerts,
        "critical_alerts": critical_alerts,
        "total_cases": total_cases,
        "total_annotations": total_annotations,
        "annotations_to_retrain": max(0, 500 - total_annotations),
    }


# ── Utility ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health(conn=Depends(get_db)):
    conn.execute("SELECT 1").fetchone()  # verify DB reachable
    return {"status": "ok", "db": "connected", "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("02_backend.api.main:app", host="0.0.0.0", port=8000, reload=True)
