"""
Four focused investigation workers (read-only). Each fetches its data slice,
saves evidence, calls the LLM once, and returns findings.

ponytail: one file, four functions. No subpackage, no base class.
"""
import json
from agents.llm_client import chat, chat_with_tools
from agents.tools import TOOLS, mcp_verification_tools
from common.evidence import create_evidence
from common.db import get_connection

# Tool allow-list per worker (documentation + enforcement reference)
WORKER_TOOLS: dict[str, list[str]] = {
    "profile":      ["get_alert_detail", "get_customer_profile", "get_customer_kyc_documents"],
    "pattern":      ["get_transaction_history", "get_model_explanation"],
    "network":      ["get_network_graph", "get_device_overlap"],
    "screening":    ["get_customer_profile"],
    "verification": ["mcp:*"],   # dynamic — whatever the configured MCP servers expose
}

_PROMPTS = {
    "profile": (
        "You are the Profile Worker in an AML investigation. "
        "Analyze the customer profile and alert details. "
        "Focus on: account age, expected vs actual turnover, KYC tier, risk_rating, "
        "declared source-of-wealth documents, and whether the alert's risk score is "
        "consistent with the customer profile. Treat documents as onboarding context, "
        "not proof that later activity is legitimate. "
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
        documents = TOOLS["get_customer_kyc_documents"](conn, customer_id)
    finally:
        conn.close()

    ev_ids = [
        _ev(case_id, "get_alert_detail",    alert_id,    alert,   "profile"),
        _ev(case_id, "get_customer_profile", customer_id, profile, "profile"),
        _ev(case_id, "get_customer_kyc_documents", customer_id, documents, "profile"),
    ]
    data = {"alert": alert, "customer": profile, "kyc_documents": documents}
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


_VERIFICATION_SYSTEM = (
    "You are the Verification Worker in an AML investigation. You are given the "
    "findings of four collector workers. Extract the key factual claims (names, "
    "jurisdictions, PEP/sanctions/adverse-media assertions, entity relationships) "
    "and use the provided tools to confirm or refute each against external sources. "
    "Call a tool before judging any claim you cannot verify from the findings alone. "
    "When done, respond with ONLY a JSON object of the form:\n"
    '{"verdicts":[{"claim":"...","verdict":"confirmed|refuted|unverified","sources":["..."]}]}\n'
    "Use 'unverified' when the tools returned nothing conclusive. No prose outside the JSON."
)


def _extract_json(text: str) -> dict:
    """Best-effort: parse the first {...} object out of an LLM reply."""
    try:
        start = text.index("{")
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    except (ValueError, json.JSONDecodeError):
        pass
    return {}


_VALID_VERDICTS = {"confirmed", "refuted", "unverified"}


def run_verification_worker(case_id: str, findings: list[dict]) -> dict | None:
    """Bounded tool-calling loop that confirms/refutes the collectors' claims
    against configured MCP servers. Returns None (worker skipped) when no MCP
    server is configured or the model can't tool-call — the workflow then behaves
    exactly as before. `tool_events` lets the supervisor stream tool_call events.
    """
    tools, execute = mcp_verification_tools()
    if not tools:
        return None   # fail soft: nothing configured

    combined = "\n\n".join(
        f"[{r['worker'].upper()}]\n{r['findings']}"
        for r in sorted(findings, key=lambda x: x["worker"])
    )

    tool_events: list[dict] = []

    def _on_event(name, args, _result):
        tool_events.append({"name": name, "query": json.dumps(args, default=str)[:200]})

    reply = chat_with_tools(
        [{"role": "system", "content": _VERIFICATION_SYSTEM},
         {"role": "user",   "content": combined}],
        tools, execute, max_iters=4, on_event=_on_event,
    )

    parsed = _extract_json(reply)
    verdicts = []
    for v in parsed.get("verdicts", []):
        verdict = str(v.get("verdict", "unverified")).lower()
        verdicts.append({
            "claim": str(v.get("claim", "")),
            "verdict": verdict if verdict in _VALID_VERDICTS else "unverified",
            "sources": [str(s) for s in (v.get("sources") or [])],
        })

    ev_ids = [_ev(case_id, "verification", "claims",
                  {"verdicts": verdicts, "tool_calls": tool_events}, "verification")]

    summary = f"Verified {len(verdicts)} claim(s) via {len(tool_events)} tool call(s)."
    return {"worker": "verification", "findings": summary, "verdicts": verdicts,
            "tool_events": tool_events, "evidence_ids": ev_ids}
