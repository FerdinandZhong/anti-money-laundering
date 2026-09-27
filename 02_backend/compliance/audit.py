"""Retained control-input snapshots in the operational SQLite store."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone
from compliance.evaluator import assess_snapshot


class AuditConfigurationError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def _key():
    key=os.environ.get('AML_KYC_AUDIT_HMAC_KEY','')
    key_file=os.environ.get('AML_KYC_AUDIT_HMAC_KEY_FILE','')
    if key and key_file:
        raise AuditConfigurationError('Configure only one KYC audit seal key source')
    if key_file:
        try:
            key=Path(key_file).read_text(encoding='utf-8').strip()
        except OSError as exc:
            raise AuditConfigurationError('KYC audit seal key file is unavailable') from exc
    if os.environ.get('AML_KYC_APP_PRIVATE') == '1' and len(key) < 32:
        raise AuditConfigurationError('Private KYC audit requires a 32+ character seal key')
    return key.encode() if key else None


def _seal(value):
    key=_key()
    return hmac.new(key,canonical(value).encode(),hashlib.sha256).hexdigest() if key else ''


def _check_seal(value,actual):
    expected=_seal(value)
    if expected and not hmac.compare_digest(expected,actual or ''):
        raise ValueError('Retained audit seal integrity failure')


def ensure_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS kyc_control_assessments (
        assessment_id TEXT PRIMARY KEY, alert_id TEXT NOT NULL,
        created_at TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
        seal TEXT NOT NULL DEFAULT '')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS kyc_review_events (
        event_id TEXT PRIMARY KEY, assessment_id TEXT NOT NULL, alert_id TEXT NOT NULL,
        sequence INTEGER NOT NULL, created_at TEXT NOT NULL, actor_id TEXT NOT NULL,
        control_id TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
        previous_hash TEXT NOT NULL, payload_hash TEXT NOT NULL,
        seal TEXT NOT NULL DEFAULT '',
        UNIQUE (assessment_id, sequence))''')
    for table in ('kyc_control_assessments','kyc_review_events'):
        if 'seal' not in {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN seal TEXT NOT NULL DEFAULT ''")
    conn.execute('''CREATE TABLE IF NOT EXISTS kyc_review_heads (
        assessment_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL,
        payload_hash TEXT NOT NULL, seal TEXT NOT NULL)''')


def save(conn,alert_id,snapshot):
    ensure_schema(conn)
    payload={'alert_id':alert_id,'snapshot':snapshot,'result':assess_snapshot(snapshot)}
    encoded=canonical(payload)
    sha=hashlib.sha256(encoded.encode()).hexdigest()
    identifier='assessment-'+sha
    created=datetime.now(timezone.utc).isoformat()
    seal=_seal({'assessment_id':identifier,'alert_id':alert_id,'created_at':created,'sha256':sha})
    conn.execute('INSERT OR IGNORE INTO kyc_control_assessments VALUES (?,?,?,?,?,?)',
                 (identifier,alert_id,created,encoded,sha,seal))
    conn.commit()
    return load(conn,alert_id,identifier)


def load(conn,alert_id,identifier):
    ensure_schema(conn)
    row=conn.execute('SELECT * FROM kyc_control_assessments WHERE alert_id=? AND assessment_id=?',
                     (alert_id,identifier)).fetchone()
    if not row:
        raise KeyError('Assessment not found in alert scope')
    if hashlib.sha256(row['payload'].encode()).hexdigest()!=row['sha256'] or identifier!='assessment-'+row['sha256']:
        raise ValueError('Retained assessment integrity failure')
    _check_seal({'assessment_id':identifier,'alert_id':alert_id,
                 'created_at':row['created_at'],'sha256':row['sha256']},row['seal'])
    data=json.loads(row['payload'])
    if data['alert_id']!=alert_id:
        raise ValueError('Retained assessment scope mismatch')
    return {'assessment_id':identifier,'created_at':row['created_at'],'sha256':row['sha256'],**data}


def replay(conn,alert_id,identifier):
    retained=load(conn,alert_id,identifier)
    actual=assess_snapshot(retained['snapshot'])
    return {'assessment_id':identifier,'matches':canonical(actual)==canonical(retained['result']),
            'result':actual,'mode':'retained control inputs; OCR is not rerun'}


def review_events(conn,alert_id,assessment_id):
    retained=load(conn,alert_id,assessment_id)
    rows=conn.execute('SELECT * FROM kyc_review_events WHERE alert_id=? AND assessment_id=? ORDER BY sequence',
                      (alert_id,assessment_id)).fetchall()
    previous=retained['sha256']
    events=[]
    for expected_sequence,row in enumerate(rows,1):
        event=dict(row)
        if event['sequence']!=expected_sequence or event['previous_hash']!=previous:
            raise ValueError('Review event chain integrity failure')
        actual=hashlib.sha256(canonical({k:v for k,v in event.items() if k not in ('payload_hash','seal')}).encode()).hexdigest()
        if actual!=event['payload_hash']:
            raise ValueError('Review event integrity failure')
        _check_seal({'event_id':event['event_id'],'payload_hash':actual},event['seal'])
        events.append(event)
        previous=actual
    head=conn.execute('SELECT * FROM kyc_review_heads WHERE assessment_id=?',(assessment_id,)).fetchone()
    if head:
        if head['sequence']!=len(events) or head['payload_hash']!=previous:
            raise ValueError('Review event head integrity failure')
        _check_seal({'assessment_id':assessment_id,'sequence':head['sequence'],
                     'payload_hash':head['payload_hash']},head['seal'])
    elif _key() and events:
        raise ValueError('Signed review head is missing')
    return events


def append_review(conn,alert_id,assessment_id,event_id,actor_id,control_id,action,reason):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',event_id):
        raise ValueError('Invalid review event ID')
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{2,100}',actor_id):
        raise ValueError('Invalid reviewer ID')
    if action not in {'CONFIRM','DISPUTE','ESCALATE'} or not reason.strip() or len(reason)>2000:
        raise ValueError('Invalid review action or reason')
    ensure_schema(conn)
    conn.execute('BEGIN IMMEDIATE')
    try:
        retained=load(conn,alert_id,assessment_id)
        if control_id not in {control['control_id'] for control in retained['result']['controls']}:
            raise ValueError('Control is not in this assessment')
        events=review_events(conn,alert_id,assessment_id)
        prior=conn.execute('SELECT * FROM kyc_review_events WHERE event_id=?',(event_id,)).fetchone()
        if prior:
            result=dict(prior)
            if (result['alert_id'],result['assessment_id'],result['actor_id'],result['control_id'],
                result['action'],result['reason']) != (alert_id,assessment_id,actor_id,control_id,action,reason):
                raise ValueError('Review event ID already used for different content')
            conn.commit()
            return result
        event={'event_id':event_id,'assessment_id':assessment_id,'alert_id':alert_id,
               'sequence':len(events)+1,'created_at':datetime.now(timezone.utc).isoformat(),
               'actor_id':actor_id,'control_id':control_id,'action':action,'reason':reason.strip(),
               'previous_hash':events[-1]['payload_hash'] if events else retained['sha256']}
        event['payload_hash']=hashlib.sha256(canonical(event).encode()).hexdigest()
        event['seal']=_seal({'event_id':event_id,'payload_hash':event['payload_hash']})
        conn.execute('INSERT INTO kyc_review_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',tuple(event.values()))
        head_seal=_seal({'assessment_id':assessment_id,'sequence':event['sequence'],
                         'payload_hash':event['payload_hash']})
        conn.execute('''INSERT INTO kyc_review_heads VALUES (?,?,?,?)
                        ON CONFLICT(assessment_id) DO UPDATE SET sequence=excluded.sequence,
                        payload_hash=excluded.payload_hash,seal=excluded.seal''',
                     (assessment_id,event['sequence'],event['payload_hash'],head_seal))
        conn.commit()
        return event
    except Exception:
        conn.rollback()
        raise
