"""Private CML Application identity passed across the loopback frontend proxy."""
import hashlib
import hmac
import os
import re
import time

from fastapi import HTTPException, Request


def mode():
    return os.environ.get('AML_KYC_REVIEW_AUTH_MODE', 'demo').lower()


def signature(secret: str, actor: str, permission: str, method: str, path: str, timestamp: str) -> str:
    message='\n'.join((actor,permission,method.upper(),path,timestamp)).encode()
    return hmac.new(secret.encode(),message,hashlib.sha256).hexdigest()


def reviewer(request: Request, claimed_actor: str | None = None) -> tuple[str,str]:
    if mode() == 'demo':
        if not claimed_actor or not re.fullmatch(r'[A-Za-z0-9_.@-]{2,100}',claimed_actor):
            raise HTTPException(422,'Valid demo reviewer ID required')
        return claimed_actor,'self_declared_demo_identity'
    if mode() != 'cml' or os.environ.get('AML_KYC_APP_PRIVATE') != '1':
        raise HTTPException(503,'Authenticated review is not configured for a private Application')
    secret=os.environ.get('AML_KYC_PROXY_SECRET','')
    actor=request.headers.get('x-aml-actor','')
    permission=request.headers.get('x-aml-permission','')
    timestamp=request.headers.get('x-aml-timestamp','')
    received=request.headers.get('x-aml-signature','')
    if not secret or not re.fullmatch(r'[A-Za-z0-9_.@-]{2,100}',actor) or permission != 'RW':
        raise HTTPException(403,'Authenticated Workbench contributor required')
    try:
        fresh=abs(time.time()-int(timestamp)) <= 60
    except ValueError:
        fresh=False
    expected=signature(secret,actor,permission,request.method,request.url.path,timestamp)
    if not fresh or not hmac.compare_digest(received,expected):
        raise HTTPException(403,'Authenticated Workbench request required')
    if claimed_actor and claimed_actor != actor:
        raise HTTPException(403,'Reviewer ID does not match authenticated user')
    return actor,'cml_remote_user_rw'
