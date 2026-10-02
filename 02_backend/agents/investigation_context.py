"""One retained input bundle and deterministic findings for an investigation run.

The LLM interprets these findings; it does not calculate amounts, declare source
agreement, choose a historical release or assign regulatory applicability.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import logging
import uuid

from common import source, kyc_source
from common.db import get_connection
from common.evidence import create_evidence
from compliance.applicability import instant
from compliance.investigation import collect
from knowledge.kb import Store
from semantic.model_loader import contract_sources, _load_yaml
from semantic.regulation import regulation_catalog
from agents.activity_patterns import transaction_patterns, pattern_observation

logger = logging.getLogger(__name__)


def _json(value):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return None


def _optional(fn, default):
    try:
        return fn()
    except Exception:
        logger.exception('Optional investigation input unavailable')
        return default


def activity_facts(window, account_id):
    """Exact decimal totals per currency. Never silently combine currencies."""
    totals, seen, issues, rows = {}, {}, [], []
    for row in window.get('rows', []):
        tid = row.get('transaction_id')
        if not tid:
            issues.append('Missing transaction identifier')
            continue
        if tid in seen:
            if seen[tid] != row:
                issues.append('Conflicting duplicate transaction ' + tid)
            continue
        seen[tid] = row
        rows.append(row)
        try:
            amount = Decimal(str(row.get('amount')))
            currency = row.get('currency')
            if not amount.is_finite() or amount < 0 or not currency:
                raise ValueError('Invalid amount or currency')
            if row.get('from_account_id') == account_id:
                totals[currency] = totals.get(currency, Decimal(0)) + amount
        except (InvalidOperation, ValueError):
            issues.append('Invalid amount or currency for ' + tid)
    complete = window.get('query_complete', False) and not issues
    return {'account_id': account_id, 'source': 'operational_transactions',
            'query_complete': complete, 'source_coverage': 'not_certified',
            'outbound_by_currency': {c: str(v) for c, v in sorted(totals.items())} if complete else {},
            'record_count': len(rows), 'issues': issues,
            'transaction_ids': sorted(seen),
            'definition': 'Outgoing recorded amounts for the selected account in (window start, cutoff]; includes internal transfers. No FX conversion.',
            'comparison': 'Customer expected monthly turnover has customer scope; no account deviation ratio is inferred.'}


def scoped_flows(window, account_id, complete):
    if not complete:
        return []
    edges, seen = {}, set()
    for row in window['rows']:
        if row['transaction_id'] in seen:
            continue
        seen.add(row['transaction_id'])
        if row.get('from_account_id') == account_id:
            origin, target = account_id, row.get('to_account_id') or row.get('counterparty_name') or 'Unknown counterparty'
        else:
            origin, target = row.get('from_account_id') or row.get('counterparty_name') or 'Unknown counterparty', account_id
        if origin == target:
            continue
        key = (origin, target, row['currency'])
        value = edges.setdefault(key, {'source': origin, 'target': target, 'currency': row['currency'], 'amount': Decimal(0), 'count': 0})
        value['amount'] += Decimal(str(row['amount']))
        value['count'] += 1
    return [{**value, 'amount': str(value['amount'])} for value in edges.values()]


def regulatory_questions(catalog, profile):
    jurisdiction = profile.get('booking_jurisdiction')
    questions = []
    for requirement in catalog['requirements']:
        if jurisdiction and requirement['jurisdiction'] != jurisdiction:
            continue
        questions.append({**requirement,
            'applicability_status': 'undetermined',
            'selection_basis': 'booking_jurisdiction' if jurisdiction else 'booking_jurisdiction_unknown',
            'question': 'What available evidence addresses ' + requirement['term'].lower() + '?',
            'next_action': 'Check applicability conditions and obtain missing ' + ', '.join(requirement['evidence_types']) + '.',
        })
    return questions


def prepare_context(case_id, alert_id, customer_id, account_id):
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM alerts WHERE alert_id=? AND customer_id=?',
                           (alert_id, customer_id)).fetchone()
        case = conn.execute('SELECT alert_id,customer_id FROM cases WHERE case_id=?', (case_id,)).fetchone()
        if row is None or case is None or case['alert_id'] != alert_id or case['customer_id'] != customer_id:
            raise ValueError('Investigation case/alert/customer scope mismatch')
        alert = dict(row)
        selected = alert.get('account_id')
        if not selected:
            raise ValueError('Alert has no recorded account')
        # The alert is authoritative even when a legacy caller supplies a different account.
        cutoff = instant(alert['data_cutoff_at']) if alert.get('data_cutoff_at') else None
        start = cutoff - timedelta(days=30) if cutoff else None
        profile = _optional(lambda: source.get_customer(customer_id), None)
        account = _optional(lambda: source.get_account(selected), None)
        if account and account.get('customer_id') != customer_id:
            raise ValueError('Alert account does not belong to investigation customer')
        window = _optional(lambda: source.investigation_transactions(selected, start.isoformat(), cutoff.isoformat()),
                           {'rows': [], 'query_complete': False, 'note': 'Transaction source unavailable'}) if cutoff else {
                               'rows': [], 'query_complete': False, 'note': 'Alert cutoff unavailable'}
        controls = collect(conn, alert_id, customer_id)
    finally:
        conn.close()
    business_profiles = _optional(lambda: kyc_source.rows('accounts'), [])
    matched = [r for r in business_profiles if r.get('account_id') == selected and r.get('customer_id') == customer_id]
    regulatory_profile = matched[0] if len(matched) == 1 else {}
    contracts = contract_sources()
    mappings = _load_yaml('aml_source_mappings.yaml')
    catalog = regulation_catalog()
    questions = regulatory_questions(catalog, regulatory_profile)
    searches, release, documents = [], None, []
    knowledge_status = 'Alert cutoff unavailable'
    if cutoff:
        try:
            # Pin once, including deterministic control evidence when available.
            release = (controls.get('result') or {}).get('release_id')
            store = Store(release=release)
            release = store.manifest['release_id']
            documents = store.documents(customer_id, selected, cutoff.isoformat())
            knowledge_status = 'available' if documents else 'No indexed documents at the alert cutoff'
            # Group overlapping requirements; at most four concept-focused searches.
            groups = {}
            for question in questions:
                key = question['term']
                groups.setdefault(key, []).append(question)
            for term, requirements in list(groups.items())[:4]:
                concepts = {c for r in requirements for c in r['business_concepts']}
                aliases = [m['field'] for m in mappings['mappings'] if m['concept'] in concepts and m.get('relation') == 'equivalent']
                query = ' '.join([term] + sorted(concepts) + sorted(set(aliases)))[:1000]
                try:
                    result = store.search(customer_id, query, selected, cutoff.isoformat(), 5)
                    # Verify originals before using snippets as evidence.
                    hits = []
                    for hit in result['hits']:
                        store.asset(customer_id, hit['version_id'], selected, cutoff.isoformat())
                        hits.append(hit)
                    searches.append({'requirement_ids': [r['id'] for r in requirements],
                                     'query': query, 'hits': hits, 'mode': result['mode']})
                except Exception:
                    logger.exception('KYC concept search unavailable')
                    searches.append({'requirement_ids': [r['id'] for r in requirements],
                                     'query': query, 'hits': [], 'unavailable': True})
        except Exception:
            logger.exception('Investigation knowledge unavailable')
            knowledge_status = 'Indexed evidence unavailable'
    activity = activity_facts(window, selected)
    devices = _optional(lambda: source.investigation_devices(selected, cutoff.isoformat()),
                        {'available': False, 'observations': []}) if cutoff else {'available': False, 'observations': []}
    context = {
        'run_id': 'INV-' + uuid.uuid4().hex, 'case_id': case_id, 'alert_id': alert_id,
        'customer_id': customer_id, 'account_id': selected,
        'cutoff': cutoff.isoformat() if cutoff else None,
        'window_start_exclusive': start.isoformat() if start else None,
        'profile': profile, 'profile_temporality': 'Current source record; not a historical profile snapshot',
        'account': account, 'alert': alert,
        'model_signal': {'model_version': alert.get('model_version'),
                         'reason_codes': _json(alert.get('reason_codes')),
                         'recorded_features': _json(alert.get('top_features')),
                         'meaning': 'Recorded alert signals, not current champion global feature importance or a crime probability'},
        'transaction_window': window, 'activity': activity,
        'activity_patterns': transaction_patterns(window, selected, activity),
        'network': {'flows': scoped_flows(window, selected, activity['query_complete']),
                    'meaning': 'Recorded fund flows in the same account window; no inference of common ownership',
                    'devices': devices},
        'controls': controls, 'regulatory_profile': regulatory_profile,
        'questions': questions, 'knowledge_release': release, 'knowledge_status': knowledge_status,
        'document_count': len(documents), 'searches': searches,
        'contracts': contracts, 'source_mappings': mappings,
        'contract_hashes': {r['filename']: hashlib.sha256(r['content'].encode()).hexdigest() for r in contracts},
        'limitations': ['Regulatory relationships do not establish legal applicability or compliance.',
                         'Search hits are candidate evidence, not verified assertions.',
                         'Operational transaction metrics and separate control-ledger metrics are distinct.',
                         'Missing screening data is not a clear screening result.'],
    }
    context['evidence_id'] = create_evidence(case_id, 'investigation_context', alert_id, context,
                                             context['run_id'], 'context')
    return context


def finding(concept, observation, status, next_action='', **extra):
    return {'concept': concept, 'observation': observation, 'status': status,
            'next_action': next_action, **extra}


def worker_findings(worker, context):
    activity = context['activity']
    if worker == 'profile':
        profile = context['profile'] or {}
        results = [finding('kyc_declaration', 'Current customer profile records expected monthly turnover: '
                           + str(profile.get('expected_monthly_turnover', 'unavailable')) +
                           '. This is customer-level context, not an account-level threshold or verified document.',
                           'recorded' if profile else 'unavailable')]
        controls = context['controls']
        if controls.get('available'):
            for control in controls['result']['controls']:
                results.append(finding(control['concept'], control['reason'], control['outcome'].lower(),
                                       'Reconcile the cited sources or obtain missing evidence.' if control['outcome'] != 'SATISFIED' else '',
                                       control_id=control['control_id'], assessment_id=controls['assessment_id'],
                                       source_kind='configured_control',
                                       evidence=control.get('evidence', []),
                                       calculation=control.get('calculation')))
        else:
            results.append(finding('kyc_evidence', context['knowledge_status'], 'incomplete',
                                   'Obtain dated supporting documents for this account.'))
        for question in context['questions']:
            hits = [h for s in context['searches'] if question['id'] in s['requirement_ids'] for h in s['hits']]
            results.append(finding(question['business_concepts'][0], question['question'],
                                   'candidate_evidence' if hits else 'incomplete', question['next_action'],
                                   requirement_id=question['id'], applicability='undetermined',
                                   meaning=question['meaning'], distinction=question['distinction'],
                                   source_url=question['source_url'], clause=question['clause'],
                                   evidence=hits))
        return results
    if worker == 'pattern':
        return [finding('account_recorded_outflow_by_currency',
                        'Recorded account outflow by currency: ' + json.dumps(activity['outbound_by_currency']) +
                        f"; {activity['record_count']} unique transaction records. " + activity['definition'],
                        'recorded' if activity['query_complete'] else 'incomplete',
                        'Confirm source coverage and a comparable account expectation before evaluating deviation.',
                        metric=activity),
                finding('model_signal', 'Recorded alert model: ' + str(context['model_signal']['model_version']) +
                        '; reasons: ' + json.dumps(context['model_signal']['reason_codes']),
                        'recorded' if context['model_signal']['recorded_features'] else 'incomplete',
                        model_signal=context['model_signal']),
                finding('account_activity_patterns', pattern_observation(context['activity_patterns']),
                        'recorded' if context['activity_patterns']['available'] else 'incomplete',
                        'Assess timing and concentration alongside the business explanation and supporting records.',
                        patterns=context['activity_patterns'])]
    if worker == 'network':
        return [finding('account_relationship', f"{len(context['network']['flows'])} fund-flow relationships in the account window. "
                        + context['network']['meaning'] + '. Device observations: ' + str(len(context['network']['devices']['observations']))
                        + (' recorded.' if context['network']['devices']['available'] else ' unavailable.'), 'recorded' if activity['query_complete'] else 'incomplete',
                        'Check ownership evidence before inferring common control.', network=context['network'])]
    return [finding('screening', 'No dated sanctions, PEP or adverse-media screening result is supplied by the current source contract.',
                    'unavailable', 'Obtain a dated screening result and resolve candidate identity matches.')]


def render_findings(findings):
    blocks = []
    for item in findings:
        citation = item.get('evidence_url', '')
        blocks.append(f"**{item['concept'].replace('_', ' ').title()} · {item['status'].replace('_', ' ')}**\n\n"
                      + item['observation'] + (f"\n\n[View retained evidence]({citation})" if citation else ''))
        if item.get('interpretation'):
            blocks.append('AI interpretation: ' + item['interpretation'])
        if item.get('next_action'):
            blocks.append('Next step: ' + item['next_action'])
    return '\n\n'.join(blocks)


def report_summary(results, context):
    findings = [f for r in results for f in r.get('structured_findings', [])]
    failed = sum(str(r.get('findings', '')).startswith('Error:') for r in results)
    conflicts = sum(f['status'] == 'conflicting_evidence' for f in findings)
    gaps = sum(f['status'] in {'incomplete', 'unavailable', 'insufficient_evidence', 'gap', 'review_required'} for f in findings)
    return (f"Account {context['account_id']} · cutoff {context['cutoff'] or 'unavailable'}. "
            f"{len(findings)} findings; {conflicts} source conflicts; {gaps} gaps or unavailable checks; {failed} failed workers. "
            "Review the evidence and next steps below. Regulatory applicability is not established; "
            "AI interpretations are suggestions, separate from recorded observations.")
