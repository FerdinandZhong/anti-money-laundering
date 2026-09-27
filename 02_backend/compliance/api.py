"""Alert-scoped synthetic control demonstration."""
import os
from fastapi import APIRouter, HTTPException, Request
from common.db import get_connection
from compliance.evaluator import evaluate
from knowledge.kb import Store, Unavailable
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix='/api/alerts/{alert_id}/controls', tags=['KYC demo controls'])


@router.get('')
def assessment(alert_id: str, release: str | None = None):
    return _assessment(alert_id,release)


def _assessment(alert_id,release=None,include_snapshot=False):
    if os.environ.get('AML_ENABLE_KYC_DEMO_CONTROLS') != '1':
        return {'available':False, 'reason':'Synthetic control demonstration is disabled'}
    conn = get_connection()
    try:
        row = conn.execute('SELECT customer_id,account_id,data_cutoff_at FROM alerts WHERE alert_id=?',
                           (alert_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404,'Alert not found')
    if not row['data_cutoff_at']:
        return {'available':False, 'reason':'Alert has no historical data cutoff'}
    try:
        return evaluate(row['customer_id'], row['account_id'], row['data_cutoff_at'],release,include_snapshot)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503,'Synthetic control inputs unavailable') from exc


@router.get('/records/{assertion_id}')
def source_record(alert_id: str, assertion_id: str, release: str):
    result = assessment(alert_id,release)
    if not result.get('available'):
        raise HTTPException(404,'Demo source record unavailable')
    evidence = [item for control in result['controls'] for item in control['evidence']
                if item['assertion_id'] == assertion_id]
    if not evidence:
        raise HTTPException(404,'Source record outside alert assessment')
    item = evidence[0]
    try:
        path,media=Store(release=release).asset(result['customer_id'],item['version_id'],result['account_id'],result['as_of'])
    except (KeyError,Unavailable,ValueError):
        raise HTTPException(503,'Source document unavailable or failed integrity validation')
    return FileResponse(path,media_type=media,headers={
        'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff'})


@router.post('/assessments')
def save_assessment(alert_id: str, release: str | None = None):
    from compliance.audit import save, AuditConfigurationError
    result=_assessment(alert_id,release,include_snapshot=True)
    if not result.get('available'):
        raise HTTPException(409,result.get('reason','Assessment unavailable'))
    conn=get_connection()
    try:
        retained=save(conn,alert_id,result['snapshot'])
        return {k:v for k,v in retained.items() if k!='snapshot'}
    except AuditConfigurationError as exc:
        raise HTTPException(503,str(exc)) from exc
    finally:
        conn.close()


@router.get('/assessments')
def list_assessments(alert_id: str):
    if os.environ.get('AML_ENABLE_KYC_DEMO_CONTROLS')!='1':
        return {'assessments':[]}
    from compliance.audit import ensure_schema
    conn=get_connection()
    try:
        if not conn.execute('SELECT 1 FROM alerts WHERE alert_id=?',(alert_id,)).fetchone():
            raise HTTPException(404,'Alert not found')
        ensure_schema(conn)
        rows=conn.execute('SELECT assessment_id,created_at FROM kyc_control_assessments WHERE alert_id=? ORDER BY created_at DESC LIMIT 100',(alert_id,)).fetchall()
        return {'assessments':[dict(row) for row in rows]}
    finally:
        conn.close()


def _retained(alert_id,assessment_id,replay=False):
    from compliance import audit
    if os.environ.get('AML_ENABLE_KYC_DEMO_CONTROLS')!='1':
        raise HTTPException(404,'Synthetic controls disabled')
    conn=get_connection()
    try:
        scope=conn.execute('SELECT customer_id,account_id FROM alerts WHERE alert_id=?',(alert_id,)).fetchone()
        if not scope:
            raise HTTPException(404,'Alert not found')
        retained=audit.load(conn,alert_id,assessment_id)
        if (retained['snapshot']['customer_id'],retained['snapshot']['account_id']) != (scope['customer_id'],scope['account_id']):
            raise HTTPException(409,'Assessment no longer matches alert scope')
        return audit.replay(conn,alert_id,assessment_id) if replay else retained
    except KeyError as exc:
        raise HTTPException(404,'Assessment not found in alert scope') from exc
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    except audit.AuditConfigurationError as exc:
        raise HTTPException(503,str(exc)) from exc
    finally:
        conn.close()


@router.get('/assessments/{assessment_id}')
def export_assessment(alert_id: str, assessment_id: str):
    retained=_retained(alert_id,assessment_id)
    from compliance import audit
    conn=get_connection()
    try:
        retained['review_events']=audit.review_events(conn,alert_id,assessment_id)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    except audit.AuditConfigurationError as exc:
        raise HTTPException(503,str(exc)) from exc
    finally:
        conn.close()
    return retained


class ReviewInput(BaseModel):
    event_id: str
    actor_id: str | None = None
    control_id: str
    action: str
    reason: str


@router.get('/reviewer')
def current_reviewer(request: Request):
    from common.reviewer_identity import mode, reviewer
    if mode() == 'demo':
        return {'mode':'demo','actor_id':None,'can_review':True}
    if mode() != 'cml':
        return {'mode':'disabled','actor_id':None,'can_review':False}
    try:
        actor,attribution=reviewer(request)
        return {'mode':'cml','actor_id':actor,'can_review':True,'actor_attribution':attribution}
    except HTTPException:
        return {'mode':'cml','actor_id':None,'can_review':False}


@router.get('/assessments/{assessment_id}/reviews')
def list_reviews(alert_id: str, assessment_id: str):
    _retained(alert_id,assessment_id)
    from compliance import audit
    from common.reviewer_identity import mode
    conn=get_connection()
    try:
        return {'events':audit.review_events(conn,alert_id,assessment_id),
                'actor_attribution':'cml_remote_user_rw' if mode()=='cml' else 'self_declared_demo_identity'}
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    except audit.AuditConfigurationError as exc:
        raise HTTPException(503,str(exc)) from exc
    finally:
        conn.close()


@router.post('/assessments/{assessment_id}/reviews')
def add_review(alert_id: str, assessment_id: str, body: ReviewInput, request: Request):
    _retained(alert_id,assessment_id)
    from compliance import audit
    from common.reviewer_identity import reviewer
    actor,attribution=reviewer(request,body.actor_id)
    conn=get_connection()
    try:
        event=audit.append_review(conn,alert_id,assessment_id,body.event_id,actor,
                                  body.control_id,body.action,body.reason)
        return {'event':event,'actor_attribution':attribution}
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    except audit.AuditConfigurationError as exc:
        raise HTTPException(503,str(exc)) from exc
    finally:
        conn.close()


@router.get('/assessments/{assessment_id}/replay')
def replay_assessment(alert_id: str, assessment_id: str):
    return _retained(alert_id,assessment_id,True)


@router.get('/assessments/{assessment_id}/records/{assertion_id}')
def retained_source(alert_id: str, assessment_id: str, assertion_id: str):
    retained=_retained(alert_id,assessment_id)
    snapshot=retained['snapshot']
    matches=[a for a in snapshot['assertions'] if a['assertion_id']==assertion_id]
    if len(matches)!=1:
        raise HTTPException(404,'Evidence not present in retained assessment')
    try:
        path,media=Store(release=snapshot['release_id']).asset(snapshot['customer_id'],matches[0]['version_id'],snapshot['account_id'],snapshot['as_of'])
        from knowledge.embeddings import digest
        if digest(path)!=matches[0]['source_sha256']:
            raise Unavailable('Retained source hash mismatch')
    except (KeyError,Unavailable,ValueError):
        raise HTTPException(503,'Retained source document unavailable')
    return FileResponse(path,media_type=media,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
