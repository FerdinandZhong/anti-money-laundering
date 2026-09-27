"""Curated synthetic SG/HK controls: scope, dates, ambiguity and no silent pass."""
from fastapi.testclient import TestClient
from compliance import applicability
from compliance.evaluator import evaluate
from knowledge.demo_records import entries as demo_entries
from knowledge.kb import build
import pytest


@pytest.fixture
def knowledge_release(tmp_path,monkeypatch):
    root=tmp_path/'knowledge'
    monkeypatch.setenv('AML_KNOWLEDGE_DIR',str(root))
    build(demo_entries(),root=root)
    return root


def test_exact_contextual_mapping_and_non_equivalence(monkeypatch):
    assert applicability.resolve('registry','法定代表人','beneficial_owner','SG','2026-09-12')['status']=='unsupported'
    assert applicability.resolve('registry','受益所有人','beneficial_owner','HK','2026-09-12')['status']=='unmapped'
    assert applicability.resolve('onboarding','funding_origin','source_of_wealth','SG','2026-09-12')['status']=='unmapped'
    original=applicability.mappings()
    monkeypatch.setattr(applicability,'mappings',lambda:{**original,'mappings':original['mappings'] + [{**original['mappings'][0],'id':'duplicate'}]})
    assert applicability.resolve('registry','受益所有人','beneficial_owner','SG','2026-09-12')['status']=='ambiguous'


def test_candidate_regulatory_sources_cannot_promote_demo_pack():
    contract=applicability.pack()
    with pytest.raises(ValueError,match='DEMO'):
        applicability.applicable_controls('SG','CORPORATE','2026-09-12',
                                          {**contract,'classification':'LEGAL'})
    with pytest.raises(ValueError,match='DEMO'):
        applicability.applicable_controls('SG','CORPORATE','2026-09-12',
                                          {**contract,'controls':[{**contract['controls'][0],'id':'MAS-626-BO'}]})


def test_historical_outcomes_and_evidence_chain(knowledge_release):
    old=evaluate('CUST-000294','ACC-0000294','2026-09-12T10:31:21Z')
    results={r['control_id']:r for r in old['controls']}
    assert results['DEMO-SG-OWNER']['outcome']=='CONFLICTING_EVIDENCE'
    assert {a['value'] for a in results['DEMO-SG-OWNER']['evidence']}=={'Lim Wei Ming','Chen Min'}
    assert all(a['source_ref'] and a['page'] and a['mapping']['mapping_ids'] for a in results['DEMO-SG-OWNER']['evidence'])
    assert all(a['version_id'] and a['chunk_id'] and a['source_sha256'] for a in results['DEMO-SG-OWNER']['evidence'])
    assert results['DEMO-SG-SOF']['outcome']=='INSUFFICIENT_EVIDENCE'
    assert old['metrics']['satisfied_controls']==1 and not old['metrics']['complete']
    assert old['regulatory_linkage']['status']=='SOURCE_REVIEW_ONLY'
    assert {item['clause'] for item in old['regulatory_linkage']['candidates']} >= {'6.13-6.14','6.19-6.24'}
    assert all(item['relation']=='candidate_related_not_equivalent' for item in old['regulatory_linkage']['candidates'])
    later=evaluate('CUST-000294','ACC-0000294','2026-09-20T00:00:00Z')
    assert {r['control_id']:r['outcome'] for r in later['controls']}['DEMO-SG-SOF']=='SATISFIED'
    assert old['input_hashes']['assertions.csv']==later['input_hashes']['assertions.csv']
    assert 'records/sg_funding.md' not in old['input_hashes']
    assert 'records/sg_funding.md' in later['input_hashes']
    assert old['controls'][0]['control_version']!=later['controls'][0]['control_version']
    clean=evaluate('CUST-000295','ACC-0000295','2026-09-12T00:00:00Z')
    assert clean['metrics']['coverage']==1 and clean['metrics']['complete']
    assert not evaluate('CUST-000295','ACC-0000294','2026-09-12')['available']


def test_alert_endpoint_uses_derived_scope_and_explicit_demo_gate(tmp_db_path,knowledge_release,monkeypatch):
    from common.db import get_connection
    from api.main import app
    conn=get_connection()
    conn.execute("INSERT INTO customers (customer_id,name) VALUES ('CUST-000294','Demo')")
    conn.execute("INSERT INTO accounts (account_id,customer_id) VALUES ('ACC-0000294','CUST-000294')")
    conn.execute("INSERT INTO alerts (alert_id,customer_id,account_id,risk_score,risk_band,status,data_cutoff_at,created_at) VALUES ('ALERT-DEMO-CONTROL','CUST-000294','ACC-0000294',0.8,'HIGH','OPEN','2026-09-12T10:31:21Z','2026-09-12T10:31:21Z')")
    conn.commit();conn.close()
    client=TestClient(app)
    route='/api/alerts/ALERT-DEMO-CONTROL/controls'
    monkeypatch.delenv('AML_ENABLE_KYC_DEMO_CONTROLS',raising=False)
    assert not client.get(route).json()['available']
    monkeypatch.setenv('AML_ENABLE_KYC_DEMO_CONTROLS','1')
    response=client.get(route)
    assert response.status_code==200
    assert response.json()['booking_context']['booking_jurisdiction']=='SG'
    assert response.json()['controls'][0]['outcome']=='CONFLICTING_EVIDENCE'
    release=response.json()['release_id']
    record=client.get(route+'/records/A-SG-DECL-OWNER',params={'release':release})
    assert record.status_code==200 and 'UBO: Chen Min' in record.text
    assert client.get(route+'/records/A-HK-CONTROL',params={'release':release}).status_code==404
    assert client.get(route+'/records/A-SG-FOUNDS',params={'release':release}).status_code==404
    assert client.get('/api/alerts/unknown/controls').status_code==404
    saved=client.post(route+'/assessments',params={'release':release})
    assert saved.status_code==200,saved.text
    identifier=saved.json()['assessment_id']
    assert client.get(route+'/assessments').json()['assessments'][0]['assessment_id']==identifier
    assert client.get(route+'/assessments/'+identifier+'/replay').json()['matches']
    exported=client.get(route+'/assessments/'+identifier).json()
    assert exported['snapshot']['control_pack']['version']=='demo-controls-v3'
    retained=client.get(route+'/assessments/'+identifier+'/records/A-SG-DECL-OWNER')
    assert retained.status_code==200 and 'UBO: Chen Min' in retained.text
    assert client.get(route+'/assessments/'+identifier+'/records/A-HK-CONTROL').status_code==404


def test_missing_indexed_field_cannot_pass(knowledge_release,tmp_path):
    from pathlib import Path
    from knowledge.kb import build
    from knowledge.kb import Store
    old_release=Store(root=knowledge_release).manifest['release_id']
    rows=demo_entries()
    target=next(row for row in rows if row['document_id']=='control-demo-hk-mandate')
    changed=tmp_path/'changed_mandate.md'
    changed.write_text(Path(target['path']).read_text().replace('authorized_signatory: Anita Wong','unrelated_field: Anita Wong'))
    target['path']=str(changed)
    target['pages'][0]['text']=target['pages'][0]['text'].replace('authorized_signatory: Anita Wong','unrelated_field: Anita Wong')
    newer=build(rows,root=knowledge_release)
    result=evaluate('CUST-000295','ACC-0000295','2026-09-12',release=newer['release_id'])
    outcomes={c['control_id']:c['outcome'] for c in result['controls']}
    assert outcomes['DEMO-HK-MANDATE']=='INSUFFICIENT_EVIDENCE'
    assert outcomes['DEMO-HK-CONTROL']=='SATISFIED'
    old=evaluate('CUST-000295','ACC-0000295','2026-09-12',release=old_release)
    assert {c['control_id']:c['outcome'] for c in old['controls']}['DEMO-HK-MANDATE']=='SATISFIED'


def test_csv_value_is_not_the_control_fact(knowledge_release,monkeypatch):
    import compliance.evaluator as evaluator
    original=evaluator._rows
    def poisoned(name):
        rows=original(name)
        if name=='assertions.csv':
            for row in rows:
                row['value']='CSV answer must be ignored'
        return rows
    monkeypatch.setattr(evaluator,'_rows',poisoned)
    result=evaluator.evaluate('CUST-000294','ACC-0000294','2026-09-12')
    owner=next(item for item in result['controls'] if item['control_id']=='DEMO-SG-OWNER')
    assert owner['outcome']=='CONFLICTING_EVIDENCE'
    assert {e['value'] for e in owner['evidence']}=={'Lim Wei Ming','Chen Min'}


@pytest.mark.parametrize('failure',['document','field','metadata','empty_field','asset'])
def test_partial_owner_evidence_never_passes(knowledge_release,monkeypatch,failure):
    import compliance.evaluator as evaluator
    rows=demo_entries()
    if failure=='document':
        rows=[r for r in rows if r['document_id']!='control-demo-sg-declaration']
    elif failure in ('field','empty_field'):
        for row in rows:
            if row['document_id']=='control-demo-sg-declaration':
                replacement='other: Chen Min' if failure=='field' else 'UBO: \nOther: not an owner'
                row['pages'][1]['text']=row['pages'][1]['text'].replace('UBO: Chen Min',replacement)
    elif failure=='metadata':
        original=evaluator._rows
        monkeypatch.setattr(evaluator,'_rows',lambda name:[r for r in original(name) if r.get('source')!='declaration'])
    build(rows,root=knowledge_release)
    if failure=='asset':
        from knowledge.kb import Store
        store=Store(root=knowledge_release)
        doc=next(d for d in store.documents('CUST-000294','ACC-0000294') if d['document_id']=='control-demo-sg-declaration')
        path,_=store.asset('CUST-000294',doc['version_id'],'ACC-0000294')
        path.write_text('corrupted original')
    result=evaluate('CUST-000294','ACC-0000294','2026-09-12')
    owner=result['controls'][0]
    assert owner['outcome']=='INSUFFICIENT_EVIDENCE'
    assert owner['missing_sources']==['declaration']
    assert len(owner['evidence'])==1


def test_low_ocr_confidence_cannot_inherit_fixture_confidence(knowledge_release):
    rows=demo_entries()
    declaration=next(r for r in rows if r['document_id']=='control-demo-sg-declaration')
    declaration['pages'][1]['evidence']=[{'method':'rapidocr','confidence':0.2,'text':'UBO: Chen Min'}]
    build(rows,root=knowledge_release)
    owner=evaluate('CUST-000294','ACC-0000294','2026-09-12')['controls'][0]
    assert owner['outcome']=='INSUFFICIENT_EVIDENCE'
    assert next(e for e in owner['evidence'] if e['source']=='declaration')['confidence']==0.2


def test_snapshot_replay_ignores_live_rules_and_detects_corruption(knowledge_release,tmp_db_path,monkeypatch):
    from common.db import get_connection
    from compliance import audit
    import compliance.evaluator as evaluator
    result=evaluate('CUST-000294','ACC-0000294','2026-09-12',include_snapshot=True)
    conn=get_connection()
    saved=audit.save(conn,'ALERT-X',result['snapshot'])
    monkeypatch.setattr(evaluator,'pack',lambda: {'version':'changed','controls':[]})
    monkeypatch.setattr(evaluator,'Store',lambda **kw: (_ for _ in ()).throw(RuntimeError('offline')))
    assert audit.replay(conn,'ALERT-X',saved['assessment_id'])['matches']
    with pytest.raises(KeyError):audit.load(conn,'OTHER-ALERT',saved['assessment_id'])
    conn.execute('UPDATE kyc_control_assessments SET payload=? WHERE assessment_id=?',('{}',saved['assessment_id']))
    conn.commit()
    with pytest.raises(ValueError,match='integrity'):audit.replay(conn,'ALERT-X',saved['assessment_id'])
    conn.close()
