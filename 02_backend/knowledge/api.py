"""Alert-derived evidence scope. Deployment authentication is inherited from app."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from common.db import get_connection
from knowledge.kb import Store, Unavailable

router = APIRouter(prefix='/api/alerts/{alert_id}/knowledge',tags=['KYC knowledge'])


def context(alert_id):
    conn=get_connection()
    try:
        row=conn.execute('SELECT customer_id,account_id,data_cutoff_at FROM alerts WHERE alert_id=?',(alert_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404,'Alert not found')
    return dict(row)


def get_store(release):
    try:
        return Store(release=release)
    except Unavailable as exc:
        raise HTTPException(503,str(exc)) from exc


@router.get('')
def list_documents(alert_id: str, release: str | None = None):
    scope=context(alert_id)
    try:
        store=Store(release=release)
        docs=store.documents(scope['customer_id'],scope['account_id'])
        return {'available':True,'release_id':store.manifest['release_id'],'documents':docs,
                'alert_cutoff':scope['data_cutoff_at'],
                'note':'Document library includes later receipts. Search defaults to the alert cutoff; later receipts are context only.'}
    except Unavailable as exc:
        return {'available':False,'release_id':None,'documents':[],'note':str(exc)}


@router.get('/search')
def search_documents(alert_id: str, q: str = Query(min_length=1,max_length=1000),
                     release: str | None = None, limit: int = Query(default=10,ge=1,le=50)):
    scope=context(alert_id)
    if not scope['data_cutoff_at']:
        return {'available':False,'hits':[],'note':'Alert has no recorded cutoff; historical evidence search is unavailable.'}
    try:
        result=get_store(release).search(scope['customer_id'],q,scope['account_id'],scope['data_cutoff_at'],limit)
        result['as_of']=scope['data_cutoff_at']
        return result
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@router.get('/assets/{version_id}')
def get_asset(alert_id: str, version_id: str, release: str):
    scope=context(alert_id)
    try:
        path,media=get_store(release).asset(scope['customer_id'],version_id,scope['account_id'])
        return FileResponse(path,media_type=media,headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, no-store'})
    except (ValueError,KeyError):
        raise HTTPException(404,'Document not found in alert scope')
    except Unavailable as exc:
        raise HTTPException(503,str(exc)) from exc


@router.get('/pages/{version_id}/{page}')
def get_page(alert_id: str, version_id: str, page: int, release: str):
    scope=context(alert_id)
    try:
        store=get_store(release)
        return {'release_id':store.manifest['release_id'],
                'chunks':store.page(scope['customer_id'],version_id,page,scope['account_id'])}
    except (ValueError,KeyError):
        raise HTTPException(404,'Page not found in alert scope')
