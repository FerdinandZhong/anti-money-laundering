"""Worker controls preserve scope, cutoff, retained evidence and fail-soft behavior."""
from common.db import get_connection
from compliance import investigation, audit
from knowledge.kb import build
from knowledge.demo_records import entries


def setup_alert(monkeypatch, tmp_path):
    monkeypatch.setenv('AML_ENABLE_KYC_DEMO_CONTROLS', '1')
    monkeypatch.setenv('AML_KNOWLEDGE_DIR', str(tmp_path / 'knowledge'))
    build(entries(), root=tmp_path / 'knowledge')
    conn = get_connection()
    conn.execute("INSERT INTO customers (customer_id,name) VALUES ('CUST-000294','Demo')")
    conn.execute("INSERT INTO accounts (account_id,customer_id) VALUES ('ACC-0000294','CUST-000294')")
    conn.execute("INSERT INTO alerts (alert_id,customer_id,account_id,data_cutoff_at) VALUES ('A','CUST-000294','ACC-0000294','2026-09-12T10:31:21Z')")
    conn.commit()
    return conn


def test_worker_retains_replayable_scoped_controls(tmp_db_path, tmp_path, monkeypatch):
    conn = setup_alert(monkeypatch, tmp_path)
    try:
        assert not investigation.collect(conn, 'A', 'CUST-000295')['available']
        result = investigation.collect(conn, 'A', 'CUST-000294')
        assert result['available']
        assert 'CONFLICTING_EVIDENCE' in investigation.summary(result)
        assert 'INSUFFICIENT_EVIDENCE' in investigation.summary(result)
        assert audit.replay(conn, 'A', result['assessment_id'])['matches']
        assert investigation.collect(conn, 'A', 'CUST-000294')['assessment_id'] == result['assessment_id']
        monkeypatch.setattr(investigation, 'evaluate', lambda *a, **kw: (_ for _ in ()).throw(OSError('missing')))
        assert not investigation.collect(conn, 'A', 'CUST-000294')['available']
        monkeypatch.delenv('AML_ENABLE_KYC_DEMO_CONTROLS')
        assert 'disabled' in investigation.collect(conn, 'A', 'CUST-000294')['reason']
    finally:
        conn.close()


def test_profile_keeps_deterministic_summary_outside_llm(tmp_db_path, tmp_path, monkeypatch):
    from agents import workers
    conn = setup_alert(monkeypatch, tmp_path)
    conn.close()
    for name in ('get_alert_detail', 'get_customer_profile', 'get_customer_kyc_documents'):
        monkeypatch.setitem(workers.TOOLS, name, lambda *args: {})
    monkeypatch.setattr(workers, 'build_case_context', lambda *a: {})
    evidence = []
    monkeypatch.setattr(workers, '_ev', lambda *a: evidence.append(a) or str(len(evidence)))
    monkeypatch.setattr(workers, 'chat', lambda *a, **kw: 'Model narrative')
    result = workers.run_profile_worker('CASE', 'A', 'CUST-000294')
    assert result['findings'].startswith('Model narrative')
    assert result['findings'].endswith(result['control_summary'])
    assert result['control_assessment']['assessment_id'] in result['findings']
    assert evidence[-1][1] == 'get_kyc_controls'
    assert evidence[-1][3]['available']
