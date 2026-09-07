"""
Four focused investigation workers (read-only). Each fetches its data slice,
saves evidence, calls the LLM once, and returns findings.

ponytail: one file, four functions. No subpackage, no base class.
"""
import json
from agents.llm_client import chat
from agents.tools import TOOLS
from common.evidence import create_evidence
from common.db import get_connection

# Tool allow-list per worker (documentation + enforcement reference)
WORKER_TOOLS: dict[str, list[str]] = {
    "profile":   ["get_alert_detail", "get_customer_profile"],
    "pattern":   ["get_transaction_history", "get_model_explanation"],
    "network":   ["get_network_graph", "get_device_overlap"],
    "screening": ["get_customer_profile"],
}

_PROMPTS = {
    "profile": (
        "You are the Profile Worker in an AML investigation. "
        "Analyze the customer profile and alert details. "
        "Focus on: account age, expected vs actual turnover, KYC tier, risk_rating, "
        "and whether the alert's risk score is consistent with the customer profile. "
        "Return exactly 3 concise bullet-point findings starting with '•'."
    ),
    "pattern": (
        "You are the Pattern Worker in an AML investigation. "
        "Analyze transaction history and model feature importances. "
        "Focus on: round amounts, rapid layering, unusual channels, "
        "high-frequency micro-transactions, and which features drove the model score. "
        "If model_explanation contains an 'error' field starting with 'no explanation "
        "available', state that plainly as one finding and do not invent feature "
        "importances — base the other findings on transaction history alone. "
        "Return exactly 3 concise bullet-point findings starting with '•'."
    ),
    "network": (
        "You are the Network Worker in an AML investigation. "
        "Analyze shared-device account graph and device overlap. "
        "Focus on: number of linked accounts, shared fingerprints, "
        "potential mule network topology, and structural risk. "
        "Return exactly 3 concise bullet-point findings starting with '•'."
    ),
    "screening": (
        "You are the Screening Worker in an AML investigation. "
        "Analyze the customer profile for adverse screening indicators. "
        "Focus on: risk_rating classification, high-risk jurisdiction exposure, "
        "PEP or sanctions flags, and whether KYC matches expected business profile. "
        "Return exactly 3 concise bullet-point findings starting with '•'."
    ),
}


def _ev(case_id: str, tool: str, query: str, payload, worker: str) -> str:
    return create_evidence(case_id, tool, query, payload, "ws2", worker)


def run_profile_worker(case_id: str, alert_id: str, customer_id: str) -> dict:
    conn = get_connection()
    try:
        alert   = TOOLS["get_alert_detail"](conn, alert_id)
        profile = TOOLS["get_customer_profile"](conn, customer_id)
    finally:
        conn.close()

    ev_ids = [
        _ev(case_id, "get_alert_detail",    alert_id,    alert,   "profile"),
        _ev(case_id, "get_customer_profile", customer_id, profile, "profile"),
    ]
    data = {"alert": alert, "customer": profile}
    findings = chat([
        {"role": "system", "content": _PROMPTS["profile"]},
        {"role": "user",   "content": json.dumps(data, default=str)},
    ], stream=False)
    assert isinstance(findings, str)
    return {"worker": "profile", "findings": findings, "evidence_ids": ev_ids}


def run_pattern_worker(case_id: str, customer_id: str, account_id: str) -> dict:
    conn = get_connection()
    try:
        txns  = TOOLS["get_transaction_history"](conn, account_id)
        # transaction_id arg is unused by get_model_explanation; account_id is safe placeholder
        model = TOOLS["get_model_explanation"](conn, account_id)
    finally:
        conn.close()

    ev_ids = [
        _ev(case_id, "get_transaction_history", account_id, txns,  "pattern"),
        _ev(case_id, "get_model_explanation",   account_id, model, "pattern"),
    ]
    data = {"transactions": txns[:20], "model_explanation": model}
    findings = chat([
        {"role": "system", "content": _PROMPTS["pattern"]},
        {"role": "user",   "content": json.dumps(data, default=str)},
    ], stream=False)
    assert isinstance(findings, str)
    return {"worker": "pattern", "findings": findings, "evidence_ids": ev_ids}


def run_network_worker(case_id: str, account_id: str) -> dict:
    # get_network_graph and get_device_overlap use source layer; conn unused
    graph   = TOOLS["get_network_graph"](None, account_id)
    overlap = TOOLS["get_device_overlap"](None, account_id)

    ev_ids = [
        _ev(case_id, "get_network_graph",  account_id, graph,   "network"),
        _ev(case_id, "get_device_overlap", account_id, overlap, "network"),
    ]
    data = {"graph": graph, "device_overlap": overlap}
    findings = chat([
        {"role": "system", "content": _PROMPTS["network"]},
        {"role": "user",   "content": json.dumps(data, default=str)},
    ], stream=False)
    assert isinstance(findings, str)
    return {"worker": "network", "findings": findings, "evidence_ids": ev_ids}


def run_screening_worker(case_id: str, customer_id: str) -> dict:
    # get_customer_profile uses source layer; conn unused
    profile = TOOLS["get_customer_profile"](None, customer_id)

    ev_ids = [
        _ev(case_id, "get_customer_profile", customer_id, profile, "screening"),
    ]
    findings = chat([
        {"role": "system", "content": _PROMPTS["screening"]},
        {"role": "user",   "content": json.dumps({"customer": profile}, default=str)},
    ], stream=False)
    assert isinstance(findings, str)
    return {"worker": "screening", "findings": findings, "evidence_ids": ev_ids}
