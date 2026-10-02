"""Real local LanceDB tests: scoping, version retention, integrity and fallback."""
import json
import pytest
from fastapi.testclient import TestClient
from knowledge import kb


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    root=tmp_path/'kb'; monkeypatch.setenv('AML_KNOWLEDGE_DIR',str(root))
    entries=[]
    for name,customer,account,date,text in [
        ('one','C-1','A-1','2026-09-01','受益所有人 陈敏 beneficial owner Chen Min registration KYC00017'),
        ('other','C-2','A-2','2026-09-01','受益所有人 secret competitor'),
        ('future','C-1','A-1','2026-10-01','受益所有人 future owner'),
        ('account','C-1','A-3','2026-09-01','受益所有人 other account'),
    ]:
        path=tmp_path/f'{name}.txt'; path.write_text(text)
        entries.append({'document_id':name,'customer_id':customer,'account_id':account,
                        'title':name,'path':str(path),'received_at':date,
                        'pages':[{'page':1,'text':text,'evidence':[{'method':'test_fixture','page':1}]}]})
    manifest=kb.build(entries,root)
    return kb.Store(root),entries,manifest


def test_scoped_bilingual_search_and_temporal_filter(corpus):
    store,_,manifest=corpus
    for query in ['受益所有人','beneficial owner','KYC00017']:
        result=store.search('C-1',query,'A-1','2026-09-15')
        assert result['mode']=='keyword'
        assert {r['document_id'] for r in result['hits']}=={'one'}
        assert result['hits'][0]['page']==1
        assert result['hits'][0]['evidence'][0]['method']=='test_fixture'
        assert result['release_id']==manifest['release_id']


def test_asset_scope_injection_and_integrity(corpus):
    store,_,_=corpus
    doc=store.documents('C-1','A-1')[0]
    with pytest.raises(KeyError): store.asset('C-2',doc['version_id'],'A-2')
    with pytest.raises(ValueError): store.search("C-1' OR TRUE",'owner')
    with pytest.raises(ValueError): store.asset('C-1','../../secret','A-1')
    path,_=store.asset('C-1',doc['version_id'],'A-1')
    path.write_text('tampered')
    with pytest.raises(kb.Unavailable): store.asset('C-1',doc['version_id'],'A-1')


def test_immutable_releases_and_failed_build_keep_pointer(corpus):
    store,entries,old=corpus
    first=kb.build(entries,store.root)
    assert first['release_id']==old['release_id']
    from pathlib import Path
    Path(entries[0]['path']).write_text('new ownership declaration')
    entries[0]['pages'][0]['text']='new ownership declaration'
    new=kb.build(entries,store.root)
    assert new['release_id']!=old['release_id']
    assert kb.Store(store.root,old['release_id']).search('C-1','陈敏','A-1')['hits']
    with pytest.raises(ValueError): kb.build(entries+entries,store.root)
    assert kb.Store(store.root).manifest['release_id']==new['release_id']


def test_model_mismatch_falls_back_without_vector_query(corpus,monkeypatch):
    store,_,_=corpus
    store.manifest['embedding']={'backend':'bge_m3_onnx','model_dir':'/not/a/model'}
    monkeypatch.setattr(kb,'load',lambda p: (_ for _ in ()).throw(FileNotFoundError()))
    result=store.search('C-1','beneficial owner','A-1')
    assert result['mode']=='keyword' and result['hits'] and 'unavailable' in result['note']


def test_unavailable_store_is_explicit(tmp_path):
    with pytest.raises(kb.Unavailable): kb.Store(tmp_path/'missing')


def test_alert_api_derives_scope_and_pins_assets(corpus,tmp_db_path):
    from common.db import get_connection
    from api.main import app
    store,_,manifest=corpus
    with get_connection() as conn:
        conn.execute("INSERT INTO customers(customer_id,name) VALUES('C-1','Test')")
        conn.execute("INSERT INTO accounts(account_id,customer_id) VALUES('A-1','C-1')")
        conn.execute("INSERT INTO alerts(alert_id,customer_id,account_id,data_cutoff_at) VALUES('AL-1','C-1','A-1','2026-09-15')")
    client=TestClient(app)
    assert client.get('/api/alerts/UNKNOWN/knowledge').status_code==404
    r=client.get('/api/alerts/AL-1/knowledge/search',params={'q':'受益所有人','release':manifest['release_id']})
    assert r.status_code==200 and len(r.json()['hits'])==1
    hit=r.json()['hits'][0]
    base='/api/alerts/AL-1/knowledge'
    assert client.get(f"{base}/assets/{hit['version_id']}",params={'release':manifest['release_id']}).status_code==200
    page=client.get(f"{base}/pages/{hit['version_id']}/1",params={'release':manifest['release_id']})
    assert page.json()['chunks'][0]['page']==1
    foreign=store.documents('C-2','A-2')[0]['version_id']
    assert client.get(f'{base}/assets/{foreign}',params={'release':manifest['release_id']}).status_code==404
    assert client.get(f'{base}/search',params={'q':'','limit':51}).status_code==422
