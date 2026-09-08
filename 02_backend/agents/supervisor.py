"""
Supervisor: dispatch 4 workers in parallel, compose narrative, yield SSE event dicts.

Event shapes emitted:
  {"type": "phase",       "phase": str}
  {"type": "worker_start","worker": str}
  {"type": "worker_done", "worker": str, "findings": str, "evidence_ids": [str]}
  {"type": "tool_call",   "worker": "verification", "query": str}
  {"type": "verdict",     "claim": str, "verdict": str, "sources": [str]}
  {"type": "token",       "text": str}
  {"type": "done"}
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Generator

from agents.llm_client import chat
from agents.state_machine import CaseState, transition
from agents.workers import (
    run_profile_worker,
    run_pattern_worker,
    run_network_worker,
    run_screening_worker,
    run_verification_worker,
)

_NARRATIVE_SYSTEM = """You are a senior AML analyst. Four specialist workers investigated this case.
Synthesize their findings into a structured narrative:
1. Executive summary and overall risk level
2. Key suspicious indicators (cite specific findings)
3. Recommended disposition: SUSPICIOUS / FALSE_POSITIVE / NEEDS_MORE_INFO
4. Confidence: LOW / MEDIUM / HIGH
If VERIFICATION VERDICTS are present, weight confirmed claims up and refuted claims
down, cite the verdicts, and let unresolved/refuted items lower your confidence.
Be concise, evidence-based, and write in the present tense."""


def _e(type_: str, **kw) -> dict:
    return {"type": type_, **kw}


def run_investigation(
    case_id: str, alert_id: str, customer_id: str, account_id: str
) -> Generator[dict, None, None]:
    """
    Generator that yields structured event dicts. Each caller wraps them as SSE.
    Workers run in parallel threads; each opens its own DB connection.
    """
    state = CaseState.ALERT_CREATED

    # ── Phase 1: COLLECTING ──────────────────────────────────────────────────
    state = transition(state, CaseState.COLLECTING)
    yield _e("phase", phase="COLLECTING")

    _workers = [
        ("profile",   run_profile_worker,   dict(case_id=case_id, alert_id=alert_id, customer_id=customer_id)),
        ("pattern",   run_pattern_worker,   dict(case_id=case_id, customer_id=customer_id, account_id=account_id)),
        ("network",   run_network_worker,   dict(case_id=case_id, account_id=account_id)),
        ("screening", run_screening_worker, dict(case_id=case_id, customer_id=customer_id)),
    ]

    findings_list: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {}
        for name, fn, kwargs in _workers:
            yield _e("worker_start", worker=name)
            futures[ex.submit(fn, **kwargs)] = name

        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception as exc:
                name = futures[fut]
                result = {"worker": name, "findings": f"Error: {exc}", "evidence_ids": []}
            findings_list.append(result)
            yield _e("worker_done",
                     worker=result["worker"],
                     findings=result["findings"],
                     evidence_ids=result["evidence_ids"])

    # ── Phase 2: VERIFYING (optional — only when an MCP server is configured) ─
    verdicts: list[dict] = []
    verification = run_verification_worker(case_id, findings_list)
    if verification is not None:
        state = transition(state, CaseState.VERIFYING)
        yield _e("phase", phase="VERIFYING")
        yield _e("worker_start", worker="verification")
        for ev in verification.get("tool_events", []):
            yield _e("tool_call", worker="verification", query=ev.get("query", ev.get("name", "")))
        verdicts = verification.get("verdicts", [])
        for v in verdicts:
            yield _e("verdict", claim=v["claim"], verdict=v["verdict"], sources=v["sources"])
        yield _e("worker_done",
                 worker="verification",
                 findings=verification["findings"],
                 evidence_ids=verification["evidence_ids"])
        findings_list.append(verification)

    # ── Phase 3: ANALYZING (narrative compose, real streaming) ───────────────
    state = transition(state, CaseState.ANALYZING)
    yield _e("phase", phase="ANALYZING")

    combined = "\n\n".join(
        f"[{r['worker'].upper()} WORKER]\n{r['findings']}"
        for r in sorted(findings_list, key=lambda x: x["worker"])
    )
    if verdicts:
        combined += "\n\n[VERIFICATION VERDICTS]\n" + "\n".join(
            f"- {v['verdict'].upper()}: {v['claim']}"
            + (f" (sources: {', '.join(v['sources'])})" if v["sources"] else "")
            for v in verdicts
        )
    messages = [
        {"role": "system", "content": _NARRATIVE_SYSTEM},
        {"role": "user",   "content": combined},
    ]
    for token in chat(messages, stream=True):
        yield _e("token", text=token)

    # ── Phase 3: REVIEWED ────────────────────────────────────────────────────
    state = transition(state, CaseState.REVIEWED)
    yield _e("phase", phase="REVIEWED")
    yield _e("done")
