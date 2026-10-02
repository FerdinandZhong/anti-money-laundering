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
import logging
import json

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Generator

from agents.llm_client import chat
from agents.investigation_context import prepare_context, report_summary
from agents.narrator import narrate, render_report
from common.evidence import create_evidence
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

_NARRATIVE_SYSTEM += (
    " Synthetic KYC control outcomes are deterministic DEMO results, not legal conclusions."
    " Preserve conflicts, gaps, unavailable inputs and their historical cutoff;"
    " do not infer a control passed from the worker's general narrative."
)


def _e(type_: str, **kw) -> dict:
    return {"type": type_, **kw}


def recommend_disposition(results):
    from agents.investigation_decision import recommend
    return recommend(results, chat)


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

    try:
        context = prepare_context(case_id, alert_id, customer_id, account_id)
    except Exception:
        logging.getLogger(__name__).exception('Investigation context unavailable')
        yield _e("error", message="Investigation context unavailable. Check the alert account and source inputs before retrying.")
        return
    if context is not None:
        account_id = context['account_id']
        yield _e('context', run_id=context['run_id'], account_id=account_id,
                 cutoff=context['cutoff'], evidence_id=context['evidence_id'])

    _workers = [
        ("profile",   run_profile_worker,   dict(case_id=case_id, alert_id=alert_id, customer_id=customer_id)),
        ("pattern",   run_pattern_worker,   dict(case_id=case_id, alert_id=alert_id, customer_id=customer_id, account_id=account_id)),
        ("network",   run_network_worker,   dict(case_id=case_id, alert_id=alert_id, customer_id=customer_id, account_id=account_id)),
        ("screening", run_screening_worker, dict(case_id=case_id, alert_id=alert_id, customer_id=customer_id)),
    ]

    findings_list: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {}
        for name, fn, kwargs in _workers:
            yield _e("worker_start", worker=name)
            futures[ex.submit(fn, **kwargs, context=context)] = name

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
                     evidence_ids=result["evidence_ids"],
                     **({'structured_findings': result['structured_findings'], 'ai_status': result['ai_status']}
                        if 'structured_findings' in result else {}))

    # ── Phase 2: VERIFYING (optional — only when an MCP server is configured) ─
    verdicts: list[dict] = []
    try:
        verification = run_verification_worker(case_id, findings_list)
    except Exception:
        verification = None
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
    if context is not None:
        technical_summary = report_summary(findings_list, context)
        recommendation = recommend_disposition(findings_list)
        yield _e('narrator_status', status='running')
        business_report = narrate(context, findings_list, recommendation)
        summary = render_report(business_report)
        create_evidence(case_id, 'investigation_report', context['run_id'], {
            'run_id': context['run_id'], 'account_id': context['account_id'],
            'cutoff': context['cutoff'], 'summary': summary,
            'workers': findings_list, 'context_evidence_id': context['evidence_id'],
            'verification_status': 'completed' if verification is not None else 'unavailable',
            'recommendation': recommendation, 'business_report': business_report,
            'technical_summary': technical_summary,
        }, context['run_id'], 'supervisor')
        yield _e('report', report=business_report)
        yield _e('token', text=summary)
        yield _e('narrator_status', status='complete')
    else:
        for token in chat(messages, stream=True):
            yield _e("token", text=token)

    for result in findings_list:
        if result.get('control_summary'):
            yield _e('token', text='\n\n' + result['control_summary'])

    # ── Phase 3: REVIEWED ────────────────────────────────────────────────────
    state = transition(state, CaseState.REVIEWED)
    yield _e("phase", phase="REVIEWED")
    yield _e("done")
