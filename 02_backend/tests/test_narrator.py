import copy
import json

import pytest

from agents import narrator


@pytest.fixture
def findings():
    return [{'worker': 'profile', 'structured_findings': [
        {'id': 'owner', 'concept': 'beneficial_owner', 'status': 'conflicting_evidence',
         'observation': 'Mapped sources disagree', 'interpretation': 'UNTRUSTED EARLIER PROSE',
         'evidence': [{'value': 'Lim Wei Ming', 'source': 'registry'}, {'value': 'Chen Min', 'source': 'declaration'}]},
        {'id': 'funds', 'concept': 'source_of_funds', 'status': 'insufficient_evidence', 'observation': 'Incomplete funding evidence'},
    ]}, {'worker': 'screening', 'structured_findings': [
        {'id': 'screen', 'concept': 'screening', 'status': 'unavailable', 'observation': 'No dated screening supplied'},
    ]}]


CONTEXT = {'profile': {'name': 'Company'}, 'cutoff': '2026-09-12T10:31:21+00:00'}
RECOMMENDATION = {'available': True, 'disposition': 'NEEDS_MORE_INFO', 'finding_ids': ['owner']}


def response():
    return {'decision': 'NEEDS_MORE_INFO',
            'overview': [{'text': 'Further information is needed to complete the review.', 'finding_ids': ['owner']}],
            'findings': [{'text': 'The ownership records identify different people as the ultimate owner.', 'finding_ids': ['owner']}],
            'significance': [{'text': 'It is unclear who ultimately owns or controls the company.', 'finding_ids': ['owner']}],
            'actions': [{'text': 'Reconcile the ownership records and obtain a current declaration.', 'finding_ids': ['owner']}]}


def test_narrator_uses_recorded_facts_and_preserves_open_questions(findings, monkeypatch):
    original = copy.deepcopy(findings)
    def chat(messages, **kwargs):
        data = json.loads(messages[-1]['content'])
        assert data['decision'] == 'NEEDS_MORE_INFO'
        assert 'UNTRUSTED EARLIER PROSE' not in messages[-1]['content']
        assert data['findings'][0]['source_values'][0]['value'] == 'Lim Wei Ming'
        return json.dumps(response())
    monkeypatch.setattr(narrator, 'chat', chat)
    report = narrator.narrate(CONTEXT, findings, RECOMMENDATION)
    assert report['mode'] == 'narrated'
    assert len(report['open_questions']) == 3  # omissions in prose cannot remove the gaps
    assert findings == original
    text = narrator.render_report(report)
    assert 'NEEDS_MORE_INFO' not in text
    assert 'source contract' not in text
    assert 'Dated sanctions' in text
    assert report['sections'][0]['paragraphs'][0]['finding_ids'] == ['owner']


@pytest.mark.parametrize('bad', ['citation', 'decision', 'jargon', 'malformed', 'section'])
def test_invalid_narration_falls_back_to_readable_source_report(findings, monkeypatch, bad):
    result = response()
    if bad == 'citation': result['overview'][0]['finding_ids'] = ['invented']
    if bad == 'decision': result['decision'] = 'FALSE_POSITIVE'
    if bad == 'jargon': result['overview'][0]['text'] = 'There are 3 failed workers and a source contract issue.'
    if bad == 'section': result['actions'] = []
    monkeypatch.setattr(narrator, 'chat', lambda *a, **kw: 'not json' if bad == 'malformed' else json.dumps(result))
    report = narrator.narrate(CONTEXT, findings, RECOMMENDATION)
    assert report['mode'] == 'source_summary'
    assert report['recommendation'] == 'Further information is needed'
    assert 'ownership records disagree' in narrator.render_report(report)


def test_offline_fallback_keeps_currencies_and_scope(findings, monkeypatch):
    findings.append({'worker': 'pattern', 'structured_findings': [{
        'id': 'metric', 'concept': 'account_recorded_outflow_by_currency', 'status': 'recorded',
        'observation': 'Amounts recorded', 'metric': {'query_complete': True, 'outbound_by_currency': {'SGD': '1234.5', 'USD': '10'}}}]})
    monkeypatch.setattr(narrator, 'chat', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('offline')))
    report = narrator.narrate(CONTEXT, findings, RECOMMENDATION)
    text = narrator.render_report(report)
    assert 'SGD 1,234.50' in text and 'USD 10.00' in text
    assert 'include internal transfers' in text
    assert report['mode'] == 'source_summary'


def test_older_reports_project_without_rewriting_retained_payload(tmp_db_path):
    from common.db import get_connection
    from common.evidence import create_evidence, get_evidence
    from api.main import app
    from fastapi.testclient import TestClient
    conn = get_connection()
    conn.execute("INSERT INTO cases(case_id) VALUES ('CASE')")
    conn.commit(); conn.close()
    old = {'summary': '1 failed worker; raw cutoff', 'workers': [], 'recommendation': {}}
    eid = create_evidence('CASE', 'investigation_report', 'r', old, 'r')
    report = TestClient(app).get('/api/cases/CASE/investigation/latest').json()
    assert report['business_report']['mode'] == 'source_summary'
    assert 'failed worker' not in report['summary']
    assert get_evidence(eid)['payload'] == old


def test_narrator_revises_overlong_output_once(findings, monkeypatch):
    calls = []
    def chat(messages, **kwargs):
        calls.append(messages[:])
        output = response()
        if len(calls) == 1:
            for key in narrator.TITLES:
                output[key][0]['text'] = 'A sentence about reviewing the company records. ' * 15
        return json.dumps(output)
    monkeypatch.setattr(narrator, 'chat', chat)
    report = narrator.narrate(CONTEXT, findings, RECOMMENDATION)
    assert report['mode'] == 'narrated'
    assert len(calls) == 2
    assert 'exceeds 400 words' in calls[-1][-1]['content']


def test_escalation_remains_separate_from_missing_evidence_in_report(findings, monkeypatch):
    findings.append({'worker': 'pattern', 'structured_findings': [{
        'id': 'patterns', 'concept': 'account_activity_patterns', 'status': 'recorded',
        'observation': 'Concentrated activity', 'patterns': {'available': True, 'by_currency': {}}}]})
    def chat(messages, **kwargs):
        data = json.loads(messages[1]['content'])
        assert data['decision'] == 'SUSPICIOUS'
        assert data['evidence_completeness']['status'] == 'incomplete'
        assert data['findings'][-1]['patterns']['available']
        r = response()
        r['decision'] = 'SUSPICIOUS'
        r['overview'] = [{'text': 'Escalate the account and resolve the outstanding ownership questions during investigation.', 'finding_ids': ['patterns', 'owner']}]
        return json.dumps(r)
    monkeypatch.setattr(narrator, 'chat', chat)
    report = narrator.narrate(CONTEXT, findings, {'available': True, 'disposition': 'SUSPICIOUS', 'activity_assessment': 'concerning'})
    assert report['recommendation'] == 'Escalate for further investigation'
    assert report['evidence_completeness']['label'] == 'Additional information required'
    assert 'Supporting information: Additional information required' in narrator.render_report(report)
    assert len(report['open_questions']) == 3
