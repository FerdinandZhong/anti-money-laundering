"""A review is attributable, append-only, scoped and distinct from calculation."""
from fastapi.testclient import TestClient
import time


def test_amp_private_audit_defaults_create_stable_demo_key(tmp_path,monkeypatch):
    import importlib.util
    from pathlib import Path
    import stat
    import yaml
    root=Path(__file__).resolve().parents[2]
    metadata=yaml.safe_load((root/'.project-metadata.yaml').read_text())
    app=next(task for task in metadata['tasks'] if task['type']=='start_application')
    assert app['bypass_authentication'] is False
    assert app['environment_variables']['AML_KYC_APP_PRIVATE']=='1'
    assert metadata['environment_variables']['AML_KYC_AUDIT_HMAC_KEY_FILE']['default']=='data/kyc_audit_demo.key'
    spec=importlib.util.spec_from_file_location('aml_installer',root/'01_installer/install.py')
    installer=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(installer,'PROJECT_ROOT',str(tmp_path))
    monkeypatch.delenv('AML_KYC_AUDIT_HMAC_KEY_FILE',raising=False)
    installer.ensure_demo_audit_key()
    key=tmp_path/'data/kyc_audit_demo.key'
    first=key.read_text()
    key.chmod(0o644)
    installer.ensure_demo_audit_key()
    assert key.read_text()==first and len(first.strip())==64
    assert stat.S_IMODE(key.stat().st_mode)==0o600


def test_review_chain_scope_retry_and_export(tmp_db_path,tmp_path,monkeypatch):
    from common.db import get_connection
    from knowledge.demo_records import entries
    from knowledge.kb import build
    from api.main import app
    monkeypatch.setenv('AML_ENABLE_KYC_DEMO_CONTROLS','1')
    monkeypatch.setenv('AML_KNOWLEDGE_DIR',str(tmp_path/'kb'))
    monkeypatch.delenv('AML_KYC_SEMANTIC_DIR',raising=False)
    build(entries(),root=tmp_path/'kb')
    conn=get_connection()
    for customer,account,alert in [('CUST-000294','ACC-0000294','A-294'),
                                   ('CUST-000295','ACC-0000295','A-295')]:
        conn.execute('INSERT INTO customers(customer_id,name) VALUES (?,?)',(customer,'Demo'))
        conn.execute('INSERT INTO accounts(account_id,customer_id) VALUES (?,?)',(account,customer))
        conn.execute('INSERT INTO alerts(alert_id,customer_id,account_id,data_cutoff_at) VALUES (?,?,?,?)',
                     (alert,customer,account,'2026-09-12T10:31:21Z'))
    conn.commit();conn.close()
    client=TestClient(app)
    root='/api/alerts/A-294/controls'
    saved=client.post(root+'/assessments').json()
    assessment=saved['assessment_id']
    url=root+'/assessments/'+assessment+'/reviews'
    body={'event_id':'review-00000001','actor_id':'analyst_1','control_id':'DEMO-SG-OWNER',
          'action':'ESCALATE','reason':'Registry and declaration disagree; request source verification.'}
    first=client.post(url,json=body)
    assert first.status_code==200,first.text
    assert client.post(url,json=body).json()['event']['payload_hash']==first.json()['event']['payload_hash']
    second={**body,'event_id':'review-00000002','action':'DISPUTE','reason':'Second reviewer disagrees.'}
    assert client.post(url,json=second).status_code==200
    events=client.get(url).json()['events']
    assert [event['sequence'] for event in events]==[1,2]
    assert events[1]['previous_hash']==events[0]['payload_hash']
    assert client.get(root+'/assessments/'+assessment).json()['review_events']==events
    assert client.get(root+'/assessments/'+assessment+'/replay').json()['matches']
    assert client.post(url,json={**body,'reason':'Changed payload'}).status_code==409
    assert client.post(url,json={**body,'event_id':'review-00000003','control_id':'UNKNOWN'}).status_code==409
    assert client.get('/api/alerts/A-295/controls/assessments/'+assessment+'/reviews').status_code==404
    conn=get_connection()
    conn.execute("UPDATE kyc_review_events SET reason='tampered' WHERE event_id='review-00000001'")
    conn.commit();conn.close()
    assert client.get(url).status_code==409
    assert client.get(root+'/assessments/'+assessment).status_code==409


def test_private_review_uses_signed_workbench_identity_and_audit_seal(tmp_db_path,tmp_path,monkeypatch):
    from common.db import get_connection
    from common.reviewer_identity import signature
    from knowledge.demo_records import entries
    from knowledge.kb import build
    from api.main import app
    monkeypatch.setenv('AML_ENABLE_KYC_DEMO_CONTROLS','1')
    monkeypatch.setenv('AML_KNOWLEDGE_DIR',str(tmp_path/'kb'))
    monkeypatch.setenv('AML_KYC_APP_PRIVATE','1')
    monkeypatch.setenv('AML_KYC_REVIEW_AUTH_MODE','cml')
    monkeypatch.setenv('AML_KYC_PROXY_SECRET','proxy-secret-for-test')
    monkeypatch.setenv('AML_KYC_AUDIT_HMAC_KEY','audit-seal-key-for-test-0123456789abcdef')
    build(entries(),root=tmp_path/'kb')
    conn=get_connection()
    conn.execute('INSERT INTO customers(customer_id,name) VALUES (?,?)',('CUST-000294','Demo'))
    conn.execute('INSERT INTO accounts(account_id,customer_id) VALUES (?,?)',('ACC-0000294','CUST-000294'))
    conn.execute('INSERT INTO alerts(alert_id,customer_id,account_id,data_cutoff_at) VALUES (?,?,?,?)',
                 ('A-294','CUST-000294','ACC-0000294','2026-09-12T10:31:21Z'))
    conn.commit();conn.close()
    client=TestClient(app)
    root='/api/alerts/A-294/controls'
    saved=client.post(root+'/assessments')
    assert saved.status_code==200,saved.text
    assessment=saved.json()['assessment_id']
    key_file=tmp_path/'audit.key'
    key_file.write_text('audit-seal-key-for-test-0123456789abcdef')
    monkeypatch.delenv('AML_KYC_AUDIT_HMAC_KEY')
    monkeypatch.setenv('AML_KYC_AUDIT_HMAC_KEY_FILE',str(key_file))
    assert client.get(root+'/assessments/'+assessment).status_code==200
    monkeypatch.setenv('AML_KYC_AUDIT_HMAC_KEY_FILE',str(tmp_path/'missing.key'))
    assert client.get(root+'/assessments/'+assessment).status_code==503
    monkeypatch.setenv('AML_KYC_AUDIT_HMAC_KEY_FILE',str(key_file))
    path=root+'/assessments/'+assessment+'/reviews'
    body={'event_id':'review-private-001','control_id':'DEMO-SG-OWNER',
          'action':'ESCALATE','reason':'Verify the conflicting source declarations.'}
    assert client.post(path,json=body).status_code==403
    stamp=str(int(time.time()))
    def headers(permission='RW'):
        return {'x-aml-actor':'analyst_1','x-aml-permission':permission,'x-aml-timestamp':stamp,
                'x-aml-signature':signature('proxy-secret-for-test','analyst_1',permission,'POST',path,stamp)}
    assert client.post(path,json=body,headers=headers('RO')).status_code==403
    assert client.post(path,json=body,headers={**headers(),'x-aml-timestamp':str(int(time.time())-120)}).status_code==403
    assert client.post(path,json={**body,'actor_id':'someone_else'},headers=headers()).status_code==403
    assert client.post(path,json=body,headers=headers()).json()['event']['actor_id']=='analyst_1'
    assert client.get(root+'/assessments/'+assessment).status_code==200
    monkeypatch.setenv('AML_KYC_REVIEW_AUTH_MODE','disabled')
    assert client.post(path,json={**body,'event_id':'review-private-002'},headers=headers()).status_code==503
    monkeypatch.setenv('AML_KYC_REVIEW_AUTH_MODE','cml')
    conn=get_connection()
    conn.execute('DELETE FROM kyc_review_events WHERE event_id=?',(body['event_id'],))
    conn.commit();conn.close()
    assert client.get(path).status_code==409  # signed head detects a truncated trail
