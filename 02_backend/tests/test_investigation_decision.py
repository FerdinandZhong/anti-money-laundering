import json

import pytest

from agents.activity_patterns import transaction_patterns
from agents.investigation_context import activity_facts
from agents.investigation_decision import recommend, evidence_completeness


def tx(tid, time, amount='10', origin='A', target='B', currency='SGD'):
    return {'transaction_id': tid, 'event_time': time, 'amount': amount,
            'from_account_id': origin, 'to_account_id': target, 'currency': currency}


def patterns(rows, complete=True):
    window = {'rows': rows, 'query_complete': complete}
    return transaction_patterns(window, 'A', activity_facts(window, 'A'))


def test_direction_rolling_boundary_currency_dedup_and_self_transfers():
    a = tx('a', '2026-09-01T12:00:00Z')
    result = patterns([a, a, tx('b', '2026-09-02T12:00:00Z', '20'),
                       tx('c', '2026-09-02T12:00:00Z', '30'),
                       tx('in', '2026-09-02T11:30:00Z', '60', 'X', 'A'),
                       tx('usd', '2026-09-02T12:00:00Z', '1000', currency='USD'),
                       tx('self', '2026-09-02T12:00:00Z', '9999', 'A', 'A')])
    assert result['available']
    s = result['by_currency']['SGD']
    assert (s['incoming_count'], s['outgoing_count'], s['self_transfer_count']) == (1, 3, 1)
    assert s['peak_outgoing_24h']['transaction_count'] == 2  # exactly 24h earlier is excluded
    assert s['peak_outgoing_24h']['amount'] == '50'
    assert s['outbound_amount'] == '60'
    assert s['payments_within_60m_after_receipt'] == 2
    assert result['by_currency']['USD']['payments_within_60m_after_receipt'] == 0
    assert s['top_recipient_outflow_share'] == '1'


def test_unknown_recipients_not_grouped_and_simultaneous_receipt_not_preceding():
    result = patterns([tx('i', '2026-09-01T00:00:00Z', '50', 'X', 'A'),
                       tx('o', '2026-09-01T00:00:00Z', '20', target=''),
                       tx('o2', '2026-09-01T01:00:00Z', '30', target='B')])['by_currency']['SGD']
    assert result['unknown_recipient_count'] == 1
    assert result['distinct_recorded_recipients'] == 1
    assert result['top_recipient_outflow_share'] == '0.6'
    assert result['payments_within_60m_after_receipt'] == 1


@pytest.mark.parametrize('rows,complete', [
    ([tx('a', 'bad-time')], True),
    ([tx('a', '2026-09-01'), tx('a', '2026-09-01', '99')], True),
    ([tx('a', '2026-09-01', origin='X', target='Y')], True),
    ([tx('a', '2026-09-01')], False),
])
def test_incomplete_or_invalid_patterns_are_not_evidence(rows, complete):
    assert not patterns(rows, complete)['available']


def finding(id, concept, status='recorded', **extra):
    return {'id': id, 'concept': concept, 'status': status, 'observation': 'Recorded observation', **extra}


def proposal(assessment, ids):
    decisions = {'concerning': 'SUSPICIOUS', 'inconclusive': 'NEEDS_MORE_INFO', 'explained': 'FALSE_POSITIVE'}
    return {'activity_assessment': assessment, 'disposition': decisions[assessment], 'finding_ids': ids,
            'reason': 'The recorded activity supports this assessment.'}


def evaluate(fs, p):
    return recommend([{'structured_findings': fs}], lambda *a, **kw: json.dumps(p))


def test_suspicious_activity_with_kyc_gaps_escalates_and_keeps_gaps():
    fs = [finding('activity', 'account_activity_patterns'),
          finding('owner', 'beneficial_owner', 'conflicting_evidence'), finding('screen', 'screening', 'unavailable')]
    result = evaluate(fs, proposal('concerning', ['activity', 'owner']))
    assert result['available'] and result['disposition'] == 'SUSPICIOUS'
    assert result['evidence_completeness']['status'] == 'incomplete'
    assert result['evidence_completeness']['finding_ids'] == ['owner', 'screen']


def test_missing_documents_alone_or_score_alone_cannot_support_escalation():
    fs = [finding('kyc', 'kyc_evidence', 'incomplete'), finding('score', 'model_signal')]
    assert not evaluate(fs, proposal('concerning', ['kyc', 'score']))['available']
    result = evaluate(fs, proposal('inconclusive', ['kyc']))
    assert result['available'] and result['evidence_completeness']['status'] == 'insufficient'


def test_explained_activity_can_close_but_not_with_material_gaps():
    fs = [finding('activity', 'account_activity_patterns'), finding('explanation', 'business_explanation', 'satisfied')]
    assert evaluate(fs, proposal('explained', ['activity', 'explanation']))['disposition'] == 'FALSE_POSITIVE'
    fs.append(finding('screen', 'screening', 'unavailable'))
    assert not evaluate(fs, proposal('explained', ['activity', 'explanation']))['available']


def test_unestablished_regulatory_search_question_is_not_failed_control():
    fs = [finding('activity', 'account_activity_patterns'),
          finding('question', 'beneficial_owner', 'candidate_evidence', requirement_id='REG')]
    assert evidence_completeness([{'structured_findings': fs}])['status'] == 'available'


def test_concerning_activity_cannot_be_downgraded_to_gather_information():
    p = proposal('concerning', ['activity'])
    p['disposition'] = 'NEEDS_MORE_INFO'
    assert not evaluate([finding('activity', 'account_activity_patterns')], p)['available']


def test_prompt_separates_evidence_and_activity_and_excludes_earlier_ai():
    def chat(messages, **kwargs):
        facts = json.loads(messages[1]['content'])
        assert 'interpretation' not in facts['findings'][0]
        assert 'does NOT prevent escalation' in messages[0]['content']
        assert facts['evidence_completeness']['status'] == 'incomplete'
        return json.dumps(proposal('concerning', ['activity']))
    result = recommend([{'structured_findings': [finding('activity', 'account_activity_patterns', interpretation='untrusted'),
                         finding('screen', 'screening', 'unavailable')]}], chat)
    assert result['disposition'] == 'SUSPICIOUS'
