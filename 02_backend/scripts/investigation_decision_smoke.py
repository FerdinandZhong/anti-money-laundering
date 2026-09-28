"""Live-model decision checks; retained local inputs, no operational DB writes."""
import copy
import json
from pathlib import Path
import sqlite3
import sys

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / '02_backend'))

from agents.activity_patterns import transaction_patterns, pattern_observation
from agents.investigation_context import activity_facts
from agents.investigation_decision import recommend
from agents.llm_client import chat
from common.db import get_db_path
from common.evidence import get_evidence


def examples():
    # Retained inputs preserve each original alert cutoff. Recompute descriptive metrics only.
    with sqlite3.connect('file:' + str(get_db_path()) + '?mode=ro', uri=True) as conn:
        rows = conn.execute("SELECT evidence_id FROM evidence WHERE tool='investigation_report' ORDER BY rowid DESC").fetchall()
    saved = {}
    for (eid,) in rows:
        report = get_evidence(eid)
        if not report['integrity_valid']:
            continue
        report = report['payload']
        account = report['account_id']
        if account not in {'ACC-0000294', 'ACC-NIGHTFALL-001'} or account in saved:
            continue
        context = get_evidence(report['context_evidence_id'])
        assert context['integrity_valid']
        context = context['payload']
        window = context['transaction_window']
        p = transaction_patterns(window, account, activity_facts(window, account))
        workers = copy.deepcopy(report['workers'])
        for worker in workers:
            if worker['worker'] == 'pattern':
                worker['structured_findings'] = [f for f in worker['structured_findings'] if f['concept'] != 'account_activity_patterns']
                worker['structured_findings'].append({'id': account + ':patterns', 'concept': 'account_activity_patterns',
                    'status': 'recorded' if p['available'] else 'incomplete', 'patterns': p, 'observation': pattern_observation(p)})
        saved[account] = (workers, 'SUSPICIOUS')
    assert len(saved) == 2, 'Run and retain investigations for both reference accounts first.'
    saved['documents_missing_only'] = ([{'structured_findings': [
        {'id': 'kyc', 'concept': 'kyc_evidence', 'status': 'incomplete', 'observation': 'No indexed documents available.'},
        {'id': 'activity', 'concept': 'account_activity_patterns', 'status': 'incomplete', 'observation': 'Transaction source unavailable.'},
    ]}], 'NEEDS_MORE_INFO')
    saved['explained_activity'] = ([{'structured_findings': [
        {'id': 'activity', 'concept': 'account_activity_patterns', 'status': 'recorded',
         'observation': 'Four SGD supplier payments totalling 2400 over 30 days; no concentrated payment burst. Account records are complete.'},
        {'id': 'explanation', 'concept': 'business_explanation', 'status': 'satisfied',
         'observation': 'Each payment matches a verified invoice and the recorded monthly supplier schedule. The alert was caused by a duplicate import, reconciled against the ledger.'},
        {'id': 'kyc', 'concept': 'kyc_evidence', 'status': 'satisfied', 'observation': 'Current identity, ownership and funding records verified; no conflicts.'},
        {'id': 'screen', 'concept': 'screening', 'status': 'satisfied', 'observation': 'Dated screening reviewed with no unresolved identity matches.'},
    ]}], 'FALSE_POSITIVE')
    saved['large_total_only'] = ([{'structured_findings': [
        {'id': 'activity', 'concept': 'account_recorded_outflow_by_currency', 'status': 'recorded',
         'observation': 'Recorded SGD outflow of 9000000 over 30 days. No transaction timing, counterparty information or comparable activity expectation is available.'},
        {'id': 'kyc', 'concept': 'kyc_evidence', 'status': 'incomplete', 'observation': 'Business purpose and supporting records unavailable.'},
    ]}], 'NEEDS_MORE_INFO')
    return saved


def main():
    output = ROOT / 'artifacts/investigation/decision-evaluation.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for name, (workers, expected) in examples().items():
        result = recommend(workers, chat)
        passed = result.get('available') and result.get('disposition') == expected
        results.append({'example': name, 'expected': expected, 'passed': bool(passed), 'result': result})
        print(json.dumps(results[-1]), flush=True)
        output.write_text(json.dumps(results, indent=2))
    assert all(r['passed'] for r in results), 'Decision examples failed; inspect ' + str(output)


if __name__ == '__main__':
    main()
