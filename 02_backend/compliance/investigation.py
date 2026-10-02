"""Retain deterministic demo assessments for an investigation's profile worker."""
import logging
import os

from compliance.audit import save
from compliance.evaluator import evaluate

logger = logging.getLogger(__name__)


def collect(conn, alert_id, customer_id):
    if os.environ.get('AML_ENABLE_KYC_DEMO_CONTROLS') != '1':
        return {'available': False, 'reason': 'Synthetic control demonstration is disabled'}
    row = conn.execute(
        'SELECT customer_id,account_id,data_cutoff_at FROM alerts WHERE alert_id=?',
        (alert_id,),
    ).fetchone()
    if row is None or row['customer_id'] != customer_id:
        return {'available': False, 'reason': 'Alert does not match investigation customer'}
    if not row['data_cutoff_at']:
        return {'available': False, 'reason': 'Alert has no historical data cutoff'}
    try:
        result = evaluate(row['customer_id'], row['account_id'], row['data_cutoff_at'],
                          include_snapshot=True)
        if not result.get('available'):
            return result
        retained = save(conn, alert_id, result['snapshot'])
        return {'available': True, 'assessment_id': retained['assessment_id'],
                'sha256': retained['sha256'], 'result': retained['result']}
    except Exception:
        # Optional enrichment must not discard the worker's baseline evidence.
        logger.exception('KYC assessment unavailable for alert %s', alert_id)
        return {'available': False, 'reason': 'Control assessment could not be evaluated and retained'}


def summary(assessment):
    """Rendered outside the LLM, also appended verbatim to the final narrative."""
    if not assessment.get('available'):
        return 'Synthetic KYC controls: UNAVAILABLE — ' + assessment['reason']
    result = assessment['result']
    lines = [f"Synthetic KYC controls (DEMO, not a legal compliance determination). "
             f"Assessment: {assessment['assessment_id']}; cutoff: {result['as_of']}; "
             f"release: {result['release_id']}."]
    lines.extend(f"• {control['control_id']}: {control['outcome']} — {control['reason']}"
                 for control in result['controls'])
    return '\n'.join(lines)
