import hashlib
import json
import uuid
from typing import Any
from common.db import get_connection


def _new_evidence_id() -> str:
    return f"EVD-{uuid.uuid4().hex[:12].upper()}"


def create_evidence(
    case_id: str,
    tool: str,
    query: str,
    payload: Any,
    data_version: str,
    agent_worker: str = "",
) -> str:
    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    evidence_id = _new_evidence_id()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO evidence
               (evidence_id, case_id, tool, query, payload_hash, data_version, agent_worker)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (evidence_id, case_id, tool, query, payload_hash, data_version, agent_worker),
        )
    return evidence_id


def get_evidence(evidence_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_case_evidence(case_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM evidence WHERE case_id = ? ORDER BY created_at", (case_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
