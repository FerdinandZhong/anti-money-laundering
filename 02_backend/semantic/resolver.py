"""Governed semantic discovery and case-context assembly.

This module deliberately resolves a small, declared AML vocabulary to existing
source/ops accessors. It is not a generic SQL layer: callers choose an intent
and approved concepts, while the resolver retains the correct scope, cutoff,
definitions, and claim limitations.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from common import source
from semantic.model_loader import context_registry, ontology, semantic_model


_ACTIVE_STATUSES = {"OPEN", "PROPOSED", "PENDING"}


def _normalise(value: str) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").split())


def _iso(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed.isoformat()
    except (TypeError, ValueError):
        return None


def _time(value: Any) -> datetime | None:
    raw = _iso(value)
    return datetime.fromisoformat(raw) if raw else None


def _json(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value else {}
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _json_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(value) if value else []
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def model_summary() -> dict[str, Any]:
    """Portable, agent-safe summary of the AML semantic model."""
    model = semantic_model()
    root = (model.get("semantic_model") or [{}])[0]
    return {
        "version": model.get("version"),
        "name": root.get("name"),
        "description": root.get("description"),
        "datasets": [d.get("name") for d in root.get("datasets", [])],
        "metrics": [m.get("name") for m in root.get("metrics", [])],
        "relationships": [r.get("name") for r in root.get("relationships", [])],
        "ai_context": root.get("ai_context", {}),
        "ontology_version": ontology().get("ontology_version"),
        "context_registry_version": context_registry().get("version"),
    }


def list_intents() -> dict[str, Any]:
    return {
        "version": context_registry().get("version"),
        "intents": context_registry().get("intents", {}),
    }


def _concept_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in ontology().get("concepts", []):
        entry = dict(item)
        entry["kind"] = "concept"
        entries.append(entry)
    root = (semantic_model().get("semantic_model") or [{}])[0]
    for item in root.get("metrics", []):
        entry = dict(item)
        entry["id"] = entry.get("name")
        entry["label"] = entry.get("name", "").replace("_", " ").title()
        entry["kind"] = "metric"
        entries.append(entry)
    return entries


def resolve_concept(term: str) -> dict[str, Any] | None:
    """Resolve a declared concept/metric by id, label, or declared synonym."""
    wanted = _normalise(term)
    if not wanted:
        return None
    exact, partial = [], []
    for entry in _concept_entries():
        names = [entry.get("id", ""), entry.get("label", "")]
        names.extend(entry.get("synonyms", []))
        names.extend((entry.get("ai_context") or {}).get("synonyms", []))
        normalized = {_normalise(name) for name in names}
        if wanted in normalized:
            exact.append(entry)
        elif any(wanted in name or name in wanted for name in normalized if name):
            partial.append(entry)
    matches = exact or partial
    if not matches:
        return None
    result = dict(matches[0])
    result["semantic_model_version"] = model_summary()["version"]
    return result


def metric_definition(metric: str) -> dict[str, Any] | None:
    wanted = _normalise(metric)
    root = (semantic_model().get("semantic_model") or [{}])[0]
    for item in root.get("metrics", []):
        names = [item.get("name", "")]
        names.extend((item.get("ai_context") or {}).get("synonyms", []))
        if wanted in {_normalise(name) for name in names}:
            result = dict(item)
            result.update({
                "id": result.get("name"), "label": result.get("name", "").replace("_", " ").title(),
                "kind": "metric", "semantic_model_version": model_summary()["version"],
            })
            return result
    return None


def relationship_paths(from_concept: str, to_concept: str) -> list[list[dict[str, str]]]:
    """Return declared concept paths. The model is intentionally small, so a
    bounded BFS is clearer and safer than a graph-database dependency."""
    start, end = _normalise(from_concept), _normalise(to_concept)
    aliases: dict[str, str] = {}
    for concept in ontology().get("concepts", []):
        cid = concept["id"]
        aliases[_normalise(cid)] = cid
        aliases[_normalise(concept.get("label", ""))] = cid
        for synonym in concept.get("synonyms", []):
            aliases[_normalise(synonym)] = cid
    start, end = aliases.get(start, start), aliases.get(end, end)
    relations = ontology().get("relations", [])
    queue: list[tuple[str, list[dict[str, str]]]] = [(start, [])]
    results: list[list[dict[str, str]]] = []
    while queue and len(results) < 5:
        node, path = queue.pop(0)
        if node == end and path:
            results.append(path)
            continue
        if len(path) >= 4:
            continue
        for relation in relations:
            if relation.get("from") != node:
                continue
            if any(step["from"] == relation["to"] for step in path):
                continue
            queue.append((relation["to"], path + [{
                "id": relation["id"], "from": relation["from"], "to": relation["to"],
                "definition": relation.get("definition", ""),
            }]))
    return results


def _active_alert(conn, customer_id: str) -> dict[str, Any] | None:
    rows = conn.execute(
        "SELECT * FROM alerts WHERE customer_id = ? ORDER BY risk_score DESC, created_at DESC",
        (customer_id,),
    ).fetchall()
    alerts = [dict(row) for row in rows]
    return next((a for a in alerts if a.get("status") in _ACTIVE_STATUSES), alerts[0] if alerts else None)


def _fact(concept: str, value: Any, source_ref: str, *, scope: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": f"fact:{concept}", "concept": concept, "value": value,
        "source_ref": source_ref, "scope": scope or {},
    }


def build_case_context(conn, customer_id: str, intent: str, alert_id: str | None = None) -> dict[str, Any]:
    """Build a read-only, case-scoped context bundle for a declared intent."""
    intent_config = (context_registry().get("intents") or {}).get(intent)
    if intent_config is None:
        raise ValueError(f"Unsupported investigation intent: {intent}")
    customer = source.get_customer(customer_id)
    if not customer:
        raise LookupError(f"Customer not found: {customer_id}")
    accounts = source.get_accounts(customer_id)
    alert = None
    if alert_id:
        row = conn.execute(
            "SELECT * FROM alerts WHERE alert_id = ? AND customer_id = ?", (alert_id, customer_id)
        ).fetchone()
        if row is None:
            raise LookupError(f"Alert not found for customer: {alert_id}")
        alert = dict(row)
    else:
        alert = _active_alert(conn, customer_id)
    account_ids = [a.get("account_id") for a in accounts if a.get("account_id")]
    selected_account = (alert or {}).get("account_id") or (account_ids[0] if account_ids else None)

    history: dict[str, dict[str, Any]] = {}
    for account_id in account_ids:
        for tx in source.account_transactions(account_id, limit=5000):
            transaction_id = tx.get("transaction_id")
            if transaction_id:
                history[transaction_id] = tx
    cutoff = _time((alert or {}).get("data_cutoff_at"))
    if cutoff is None:
        cutoff = max((_time(tx.get("event_time")) for tx in history.values() if _time(tx.get("event_time"))), default=None)
    cutoff = cutoff or datetime.now(timezone.utc).replace(tzinfo=None)
    window_start = cutoff - timedelta(days=30)
    outbound = round(sum(
        float(tx.get("amount") or 0)
        for tx in history.values()
        if tx.get("from_account_id") in account_ids
        and (event_time := _time(tx.get("event_time")))
        and window_start <= event_time <= cutoff
    ), 2)
    expected = float(customer.get("expected_monthly_turnover") or 0)
    pct = round(outbound / expected * 100, 1) if expected else None
    top_features = _json((alert or {}).get("top_features"))
    score_breakdown = top_features.get("score_breakdown")
    case = None
    evidence: list[dict[str, Any]] = []
    if alert:
        row = conn.execute("SELECT * FROM cases WHERE alert_id = ?", (alert["alert_id"],)).fetchone()
        case = dict(row) if row else None
    if case:
        evidence = [dict(row) for row in conn.execute(
            "SELECT evidence_id, tool, query, data_version, agent_worker, created_at "
            "FROM evidence WHERE case_id = ? ORDER BY created_at", (case["case_id"],)
        ).fetchall()]

    scope = {
        "customer_id": customer_id, "account_ids": account_ids,
        "selected_account_id": selected_account, "data_cutoff_at": cutoff.isoformat(),
        "window_start_at": window_start.isoformat(), "window": "30d",
    }
    facts = [
        _fact("customer", {k: customer.get(k) for k in ("customer_id", "name", "industry", "risk_rating", "beneficial_owner", "kyc_last_updated")}, "customers", scope=scope),
        _fact("kyc_declaration", expected, "customers.expected_monthly_turnover", scope=scope),
        _fact("observed_outbound_flow_30d", outbound, "transactions.amount", scope=scope),
        _fact("observed_vs_expected_pct", pct, "derived:observed_outbound_flow_30d/expected_monthly_turnover", scope=scope),
    ]
    if alert:
        facts.extend([
            _fact("account_priority_score", alert.get("risk_score"), f"alerts:{alert['alert_id']}.risk_score", scope=scope),
            _fact("model_signal", {"reason_codes": _json_list(alert.get("reason_codes")), "triggered_rules": _json_list(alert.get("triggered_rules")), "score_breakdown": score_breakdown}, f"alerts:{alert['alert_id']}.top_features", scope=scope),
            _fact("sustained_pattern", {"pattern_start_at": _iso(alert.get("pattern_start_at")), "latest_contributing_at": _iso(alert.get("latest_contributing_at"))}, f"alerts:{alert['alert_id']}", scope=scope),
        ])

    allowed = set(intent_config.get("concepts", []))
    visible_facts = [fact for fact in facts if fact["concept"] in allowed or fact["concept"] == "customer"]
    relations = []
    if account_ids:
        relations.append({"relation": "owns", "from": customer_id, "to": account_ids})
    if selected_account:
        relations.append({"relation": "monitored_account", "from": (alert or {}).get("alert_id"), "to": selected_account})
    return {
        "semantic_model_version": model_summary()["version"],
        "ontology_version": ontology().get("ontology_version"),
        "intent": intent,
        "intent_description": intent_config.get("description"),
        "case_id": (case or {}).get("case_id"),
        "alert_id": (alert or {}).get("alert_id"),
        "scope": scope,
        "facts": visible_facts,
        "relationships": relations,
        "evidence_refs": evidence,
        "allowed_conclusions": intent_config.get("allowed_conclusions", []),
        "claim_limitations": intent_config.get("limitations", []) + [c["rule"] for c in ontology().get("claim_constraints", [])],
    }


def query_case_facts(
    conn, customer_id: str, intent: str, concepts: list[str], alert_id: str | None = None
) -> dict[str, Any]:
    context = build_case_context(conn, customer_id, intent, alert_id)
    allowed = {fact["concept"] for fact in context["facts"]}
    requested = []
    unknown = []
    for term in concepts:
        resolved = resolve_concept(term)
        if not resolved or resolved.get("id") not in allowed:
            unknown.append(term)
        else:
            requested.append(resolved["id"])
    context["facts"] = [fact for fact in context["facts"] if fact["concept"] in set(requested)]
    context["requested_concepts"] = requested
    context["unavailable_concepts"] = unknown
    return context
