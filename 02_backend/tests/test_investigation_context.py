import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from agents import investigation_context as ic, workers, supervisor
from common import source
from common.db import get_connection
from common.evidence import create_evidence, get_evidence

CUT = '2026-09-12T10:31:21+00:00'
ACCOUNT = 'ACC-0000294'
CUSTOMER = 'CUST-000294'


def tx(tid, amount='10', currency='SGD', **extra):
    return {'transaction_id': tid, 'from_account_id': ACCOUNT, 'to_account_id': None,
            'amount': amount, 'currency': currency, 'event_time': '2026-09-10T00:00:00Z', **extra}


@pytest.fixture
def case(tmp_db_path, monkeypatch):
    conn = get_connection()
    conn.execute('INSERT INTO customers(customer_id,name) VALUES (?,?)', (CUSTOMER, 'Company'))
    conn.execute('INSERT INTO accounts(account_id,customer_id) VALUES (?,?)', (ACCOUNT, CUSTOMER))
    conn.execute('INSERT INTO alerts(alert_id,customer_id,account_id,data_cutoff_at,model_version,top_features) VALUES (?,?,?,?,?,?)',
                 ('A', CUSTOMER, ACCOUNT, CUT, 'historic-model', '{"signal":0.7}'))
    conn.execute('INSERT INTO cases(case_id,alert_id,customer_id) VALUES (?,?,?)', ('CASE', 'A', CUSTOMER))
    conn.commit(); conn.close()
    monkeypatch.delenv('AML_ENABLE_KYC_DEMO_CONTROLS', raising=False)
    monkeypatch.setattr(source, 'get_customer', lambda c: {'customer_id': c, 'expected_monthly_turnover': 500})
    monkeypatch.setattr(source, 'get_account', lambda a: {'account_id': a, 'customer_id': CUSTOMER})
    monkeypatch.setattr(source, 'investigation_transactions', lambda *a: {
        'rows': [tx('T1'), tx('T2', '20', 'USD')], 'query_complete': True})
    monkeypatch.setattr(source, 'investigation_devices', lambda *a: {'available': False, 'observations': []})
    monkeypatch.setattr(ic, 'Store', lambda **kw: (_ for _ in ()).throw(RuntimeError('offline')))
    return 'CASE'


def test_complete_window_not_recent_sample(monkeypatch):
    rows = [tx(str(i)) for i in range(5101)] + [
        tx('boundary', event_time='2026-08-13T10:31:21Z'),
        tx('future', event_time='2026-09-13T00:00:00Z'),
        tx('late', received_at='2026-09-13T00:00:00Z'),
        tx('end', event_time=CUT)]
    monkeypatch.setattr(source, 'backend', lambda: 'csv')
    monkeypatch.setattr(source, '_csv', lambda table: pd.DataFrame(rows))
    result = source.investigation_transactions(ACCOUNT, '2026-08-13T10:31:21Z', CUT)
    assert len(result['rows']) == 5102
    assert result['query_complete']
    assert result['excluded_later_receipts'] == 1
    assert not result['receipt_time_available']
    assert {'boundary', 'future', 'late'}.isdisjoint({r['transaction_id'] for r in result['rows']})


def test_sql_window_is_parameterized_uncapped_and_mcp_not_certified(monkeypatch):
    calls = []
    monkeypatch.setattr(source, 'backend', lambda: 'mcp')
    monkeypatch.setattr(source, '_sql_df', lambda sql, params: calls.append((sql, params)) or pd.DataFrame([tx('a')]))
    result = source.investigation_transactions(ACCOUNT, '2026-08-13T10:31:21Z', CUT)
    assert 'LIMIT' not in calls[0][0]
    assert calls[0][1][:2] == (ACCOUNT, ACCOUNT)
    assert not result['query_complete']


def test_currency_dedup_and_conflict():
    window = {'query_complete': True, 'rows': [tx('a', '0.1'), tx('a', '0.1'), tx('b', '0.2'), tx('c', '12', 'USD')]}
    result = ic.activity_facts(window, ACCOUNT)
    assert result['outbound_by_currency'] == {'SGD': '0.3', 'USD': '12'}
    assert result['record_count'] == 3
    window['rows'].append(tx('a', '99'))
    result = ic.activity_facts(window, ACCOUNT)
    assert not result['query_complete']
    assert result['outbound_by_currency'] == {}
    assert 'Conflicting duplicate' in result['issues'][0]


def test_context_pins_alert_account_and_regulation_without_documents(case):
    context = ic.prepare_context(case, 'A', CUSTOMER, 'WRONG-FIRST-ACCOUNT')
    assert context['account_id'] == ACCOUNT
    assert context['model_signal']['model_version'] == 'historic-model'
    assert context['activity']['outbound_by_currency'] == {'SGD': '10', 'USD': '20'}
    assert context['questions']
    assert all(q['applicability_status'] == 'undetermined' for q in context['questions'])
    assert not context['searches']
    retained = get_evidence(context['evidence_id'])
    assert retained['integrity_valid']
    assert retained['payload']['contract_hashes'] == context['contract_hashes']
    assert retained['payload']['transaction_window']['rows'][0]['transaction_id'] == 'T1'


def test_unknown_booking_keeps_regulation_questions(case, monkeypatch):
    monkeypatch.setattr(ic.kyc_source, 'rows', lambda name: [])
    context = ic.prepare_context(case, 'A', CUSTOMER, ACCOUNT)
    assert {q['jurisdiction'] for q in context['questions']} == {'SG', 'HK'}
    assert all(q['selection_basis'] == 'booking_jurisdiction_unknown' for q in context['questions'])


def test_missing_cutoff_never_substitutes_now(case, monkeypatch):
    conn = get_connection(); conn.execute("UPDATE alerts SET data_cutoff_at=NULL"); conn.commit(); conn.close()
    monkeypatch.setattr(source, 'investigation_transactions', lambda *a: pytest.fail('must not fetch without cutoff'))
    context = ic.prepare_context(case, 'A', CUSTOMER, ACCOUNT)
    assert context['cutoff'] is None
    assert not context['activity']['query_complete']
    assert context['questions']


def test_scope_mismatch_fails_before_worker_reads(case):
    with pytest.raises(ValueError, match='scope mismatch'):
        ic.prepare_context(case, 'A', 'OTHER-CUSTOMER', ACCOUNT)


def test_retained_payload_tamper_and_legacy_evidence(case):
    eid = create_evidence(case, 'tool', 'q', {'value': 'original'}, 'v1')
    assert get_evidence(eid)['payload'] == {'value': 'original'}
    conn = get_connection()
    conn.execute('UPDATE evidence_payloads SET payload_json=? WHERE evidence_id=?', ('{}', eid))
    conn.execute("INSERT INTO evidence(evidence_id,case_id,tool) VALUES ('LEGACY',?,'old')", (case,))
    conn.commit(); conn.close()
    assert not get_evidence(eid)['integrity_valid']
    assert get_evidence(eid)['payload'] is None
    assert not get_evidence('LEGACY')['payload_available']
    from api.main import app
    client = TestClient(app)
    assert client.get(f'/api/cases/{case}/evidence/{eid}').status_code == 409
    assert client.get(f'/api/cases/OTHER/evidence/{eid}').status_code == 404


def test_worker_keeps_conflicts_and_discards_unknown_ids(case, monkeypatch):
    context = ic.prepare_context(case, 'A', CUSTOMER, ACCOUNT)
    context['controls'] = {'available': True, 'assessment_id': 'ASSESS', 'result': {'controls': [
        {'control_id': 'OWNER', 'concept': 'beneficial_owner', 'reason': 'Sources disagree',
         'outcome': 'CONFLICTING_EVIDENCE', 'evidence': []}]}}
    def reply(messages, **kw):
        findings = json.loads(messages[1]['content'])['findings']
        return json.dumps({'interpretations': [
            {'finding_id': findings[1]['id'], 'text': 'Obtain a reconciled ownership declaration.', 'status': 'satisfied'},
            {'finding_id': 'INVENTED', 'text': 'Everything passed.'}]})
    monkeypatch.setattr(workers, 'chat', reply)
    result = workers.run_profile_worker(case, 'A', CUSTOMER, context=context)
    owner = result['structured_findings'][1]
    assert owner['status'] == 'conflicting_evidence'
    assert owner['observation'] == 'Sources disagree'
    assert owner['interpretation'] == 'Obtain a reconciled ownership declaration.'
    assert 'Everything passed' not in result['findings']
    assert get_evidence(result['evidence_ids'][-1])['payload']['findings'][1] == owner


def test_invalid_llm_preserves_findings_and_no_screening_clearance(case, monkeypatch):
    context = ic.prepare_context(case, 'A', CUSTOMER, ACCOUNT)
    monkeypatch.setattr(workers, 'chat', lambda *a, **k: 'unstructured output')
    result = workers.run_screening_worker(case, 'A', CUSTOMER, context=context)
    assert result['ai_status'] == 'unavailable'
    assert result['structured_findings'][0]['status'] == 'unavailable'
    assert 'No dated sanctions' in result['findings']


def test_real_index_retrieval_pinned_scoped_and_bilingual(case, monkeypatch, tmp_path):
    from knowledge.kb import build, Store
    from knowledge.demo_records import entries
    monkeypatch.setenv('AML_KNOWLEDGE_DIR', str(tmp_path / 'knowledge'))
    built = build(entries(), root=tmp_path / 'knowledge')
    monkeypatch.setattr(ic, 'Store', Store)
    context = ic.prepare_context(case, 'A', CUSTOMER, ACCOUNT)
    assert context['knowledge_release'] == built['release_id']
    assert context['document_count'] > 0
    assert any('受益所有人' in s['query'] for s in context['searches'])
    hits = [h for s in context['searches'] for h in s['hits']]
    assert hits
    assert all(ic.instant(h['received_at']) <= ic.instant(CUT) for h in hits)
    assert all('hk-' not in h['document_id'] for h in hits)


def test_full_workflow_retains_report_with_llm_offline(case, monkeypatch):
    monkeypatch.setattr(workers, 'chat', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('LLM offline')))
    monkeypatch.setattr(supervisor, 'run_verification_worker', lambda *a: None)
    monkeypatch.setattr(supervisor, 'chat', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('LLM offline')))
    from agents import narrator
    monkeypatch.setattr(narrator, 'chat', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('LLM offline')))
    events = list(supervisor.run_investigation(case, 'A', CUSTOMER, 'WRONG-FIRST-ACCOUNT'))
    assert events[-1]['type'] == 'done'
    assert len([e for e in events if e['type'] == 'worker_done']) == 4
    assert all(e['structured_findings'] for e in events if e['type'] == 'worker_done')
    from api.main import app
    client = TestClient(app)
    report = client.get(f'/api/cases/{case}/investigation/latest').json()
    assert report['available']
    assert report['account_id'] == ACCOUNT
    assert report['business_report']['mode'] == 'source_summary'
    assert any(e['type'] == 'report' for e in events)
    assert len(report['workers']) == 4
    assert all(w['ai_status'] == 'unavailable' for w in report['workers'])


def test_device_observations_respect_cutoff(monkeypatch):
    rows = [
        {'account_id': ACCOUNT, 'device_fingerprint': 'F1', 'login_time': '2026-09-01'},
        {'account_id': 'OTHER', 'device_fingerprint': 'F1', 'login_time': '2026-09-02'},
        {'account_id': 'FUTURE', 'device_fingerprint': 'F1', 'login_time': '2026-09-20'},
        {'account_id': ACCOUNT, 'device_fingerprint': 'F2', 'login_time': '2026-09-20'},
        {'account_id': 'NOT-YET-LINKED', 'device_fingerprint': 'F2', 'login_time': '2026-09-02'},
    ]
    monkeypatch.setattr(source, 'backend', lambda: 'csv')
    monkeypatch.setattr(source, '_csv', lambda name: pd.DataFrame(rows))
    result = source.investigation_devices(ACCOUNT, CUT)
    assert {r['account_id'] for r in result['observations']} == {ACCOUNT, 'OTHER'}


def test_network_currency_and_duplicate_boundaries():
    window = {'rows': [tx('a', '10'), tx('a', '10'), tx('b', '20', 'USD')]}
    edges = ic.scoped_flows(window, ACCOUNT, True)
    assert {(r['currency'], r['amount'], r['count']) for r in edges} == {('SGD', '10', 1), ('USD', '20', 1)}
    assert ic.scoped_flows(window, ACCOUNT, False) == []


def test_both_api_entry_points_use_alert_account(case, monkeypatch):
    from api import main
    calls = []
    monkeypatch.setattr(source, 'get_accounts', lambda c: [{'account_id': 'WRONG-FIRST-ACCOUNT'}])
    def run(*args):
        calls.append(args)
        yield {'type': 'token', 'text': 'retained result'}
        yield {'type': 'done'}
    monkeypatch.setattr(main, 'run_investigation', run)
    client = TestClient(main.app)
    assert client.post('/api/cases/CASE/investigate', json={}).status_code == 200
    assert client.post(f'/api/customers/{CUSTOMER}/investigate').status_code == 200
    assert [args[3] for args in calls] == [ACCOUNT, ACCOUNT]


def test_context_failure_is_not_a_successful_report(case, monkeypatch):
    monkeypatch.setattr(supervisor, 'prepare_context', lambda *a: (_ for _ in ()).throw(ValueError('bad scope')))
    events = list(supervisor.run_investigation(case, 'A', CUSTOMER, ACCOUNT))
    assert events[-1]['type'] == 'error'
    assert not any(e['type'] == 'done' for e in events)


def test_disposition_rejects_unknown_citations_and_clearance_with_gaps(monkeypatch):
    results = [{'structured_findings': [{'id': 'known', 'status': 'conflicting_evidence', 'observation': 'Sources disagree'}]}]
    for proposal in ({'activity_assessment': 'concerning', 'disposition': 'SUSPICIOUS', 'finding_ids': ['invented'], 'reason': 'Activity needs review.'},
                     {'activity_assessment': 'explained', 'disposition': 'FALSE_POSITIVE', 'finding_ids': ['known'], 'reason': 'Activity is explained.'}):
        monkeypatch.setattr(supervisor, 'chat', lambda *a, **kw: json.dumps(proposal))
        assert not supervisor.recommend_disposition(results)['available']
    monkeypatch.setattr(supervisor, 'chat', lambda *a, **kw: json.dumps({'activity_assessment': 'inconclusive', 'disposition': 'NEEDS_MORE_INFO', 'finding_ids': ['known'], 'reason': 'Only conflicting ownership records are available.'}))
    assert supervisor.recommend_disposition(results)['finding_ids'] == ['known']
