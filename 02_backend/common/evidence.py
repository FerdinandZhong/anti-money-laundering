from contextlib import closing
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
    payload_json = json.dumps(payload, sort_keys=True, default=str)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
    evidence_id = _new_evidence_id()
    with closing(get_connection()) as conn, conn:
        conn.execute(
            """INSERT INTO evidence
               (evidence_id, case_id, tool, query, payload_hash, data_version, agent_worker)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (evidence_id, case_id, tool, query, payload_hash, data_version, agent_worker),
        )
        conn.execute('INSERT INTO evidence_payloads (evidence_id,payload_json) VALUES (?,?)',
                     (evidence_id, payload_json))
    return evidence_id


def get_evidence(evidence_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT e.*, p.payload_json FROM evidence e LEFT JOIN evidence_payloads p "
        "ON e.evidence_id=p.evidence_id WHERE e.evidence_id = ?", (evidence_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    raw = result.pop('payload_json')
    result['payload_available'] = raw is not None
    result['integrity_valid'] = (hashlib.sha256(raw.encode()).hexdigest() == result['payload_hash']) if raw is not None else None
    result['payload'] = json.loads(raw) if raw is not None and result['integrity_valid'] else None
    return result


def list_case_evidence(case_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM evidence WHERE case_id = ? ORDER BY created_at", (case_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
