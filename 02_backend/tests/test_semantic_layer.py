"""Tests for the governed AML semantic contract and HTTP surface."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def _seed(conn):
    now = datetime(2026, 9, 11, 12, tzinfo=timezone.utc).isoformat()
    conn.execute("INSERT INTO customers (customer_id, name) VALUES ('CUST-S1','Semantic Test Ltd.')")
    conn.execute("INSERT INTO accounts (account_id, customer_id) VALUES ('ACC-S1','CUST-S1')")
    conn.execute(
        "INSERT INTO alerts (alert_id, customer_id, account_id, risk_score, risk_band, status, "
        "reason_codes, triggered_rules, top_features, data_cutoff_at, created_at) "
        "VALUES ('ALERT-S1','CUST-S1','ACC-S1',0.91,'CRITICAL','OPEN',?,?,?,?,?)",
        ('["HIGH_MODEL_SCORE"]', '["SUSTAINED_RISK"]',
         '{"score_breakdown":{"signals":[{"name":"model","weight":45}]}}', now, now),
    )
    conn.commit()


def _source(monkeypatch):
    import semantic.resolver as resolver

    monkeypatch.setattr(resolver.source, "get_customer", lambda customer_id: {
        "customer_id": customer_id, "name": "Semantic Test Ltd.", "industry": "TRADING",
        "risk_rating": "LOW", "expected_monthly_turnover": 1000.0,
        "beneficial_owner": "Owner", "kyc_last_updated": "2026-09-01",
    } if customer_id == "CUST-S1" else None)
    monkeypatch.setattr(resolver.source, "get_accounts", lambda customer_id: [
        {"account_id": "ACC-S1", "customer_id": customer_id}
    ] if customer_id == "CUST-S1" else [])
    monkeypatch.setattr(resolver.source, "account_transactions", lambda account_id, limit=5000: [
        {"transaction_id": "TX-S1", "from_account_id": account_id,
         "to_account_id": "EXT-1", "amount": 1500.0,
         "event_time": "2026-09-10T10:00:00"}
    ])


def _client():
    import api.main as main
    return TestClient(main.app)


def test_semantic_model_and_concept_discovery(tmp_db_path):
    c = _client()
    model = c.get("/api/semantic/model").json()
    assert model["name"] == "aml_investigation"
    assert "transaction" in model["datasets"]
    concept = c.get("/api/semantic/concepts/risk%20score").json()
    assert concept["id"] == "account_priority_score"
    assert "not a probability" in concept["definition"]
    assert c.get("/api/semantic/metrics/account_priority_score").status_code == 200
    assert c.get("/api/semantic/concepts/no-such-term").status_code == 404


def test_semantic_context_is_time_scoped_and_read_only(tmp_db_path, monkeypatch):
    from common.db import get_connection
    conn = get_connection(); _seed(conn)
    _source(monkeypatch)
    before = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    response = _client().post("/api/semantic/context", json={
        "customer_id": "CUST-S1", "intent": "score_explanation",
    })
    assert response.status_code == 200
    body = response.json()
    facts = {fact["concept"]: fact for fact in body["facts"]}
    assert facts["account_priority_score"]["value"] == 0.91
    assert facts["observed_outbound_flow_30d"]["value"] == 1500.0
    assert body["scope"]["selected_account_id"] == "ACC-S1"
    assert any("not a probability" in x for x in body["claim_limitations"])
    assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == before


def test_semantic_query_enforces_intent_allow_list(tmp_db_path, monkeypatch):
    from common.db import get_connection
    conn = get_connection(); _seed(conn)
    _source(monkeypatch)
    response = _client().post("/api/semantic/query", json={
        "customer_id": "CUST-S1", "intent": "kyc_review",
        "concepts": ["expected turnover", "risk score"],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["requested_concepts"] == ["kyc_declaration"]
    assert body["unavailable_concepts"] == ["risk score"]
    assert [fact["concept"] for fact in body["facts"]] == ["kyc_declaration"]


def test_semantic_relationship_path(tmp_db_path):
    response = _client().get("/api/semantic/relationships", params={
        "from_concept": "Customer", "to_concept": "Transaction",
    })
    assert response.status_code == 200
    path = response.json()["paths"][0]
    assert [step["id"] for step in path] == ["owns", "sends"]


def test_semantic_contract_sources_are_exact_and_fixed(tmp_db_path):
    from semantic.model_loader import SEMANTIC_ROOT
    response = _client().get('/api/semantic/contracts')
    assert response.status_code == 200
    contracts = response.json()['contracts']
    assert {item['filename'] for item in contracts} == {
        'aml_semantic_model.ossie.yaml', 'aml_ontology.yaml', 'aml_context_registry.yaml', 'aml_regulation.ossie.yaml',
    }
    for item in contracts:
        assert item['content'] == (SEMANTIC_ROOT / item['filename']).read_text(encoding='utf-8')
        assert item['title'] and item['description']


def test_context_explains_meaning_and_missing_coverage(tmp_db_path, monkeypatch):
    from common.db import get_connection
    conn = get_connection(); _seed(conn)
    _source(monkeypatch)
    body = _client().post('/api/semantic/context', json={
        'customer_id': 'CUST-S1', 'intent': 'kyc_review', 'alert_id': 'ALERT-S1',
    }).json()
    facts = {fact['concept']: fact for fact in body['facts']}
    assert facts['kyc_declaration']['label'] == 'Recorded onboarding profile'
    assert facts['kyc_declaration']['source_ref'] == 'customers.expected_monthly_turnover'
    assert 'not proof' in facts['kyc_declaration']['definition']
    assert facts['observed_outbound_flow_30d']['source_ref'] == 'transactions.amount'
    assert 'account' in body['declared_concepts']
    assert 'account' in body['unavailable_fact_concepts']
    assert 'account_priority_score' not in facts
    assert any('5,000' in note for note in body['retrieval_notes'])


def test_demo_queries_and_distinct_kyc_concepts(tmp_db_path, monkeypatch):
    from common.db import get_connection
    conn = get_connection(); _seed(conn)
    _source(monkeypatch)
    c = _client()
    assert c.get('/api/semantic/concepts/source%20of%20wealth').status_code == 404
    for intent, terms, expected in [
        ('kyc_review', ['expected turnover', 'observed outflow'], {'kyc_declaration', 'observed_outbound_flow_30d'}),
        ('score_explanation', ['risk score', 'model signal', 'sustained pattern'], {'account_priority_score', 'model_signal', 'sustained_pattern'}),
    ]:
        response = c.post('/api/semantic/query', json={
            'customer_id': 'CUST-S1', 'alert_id': 'ALERT-S1', 'intent': intent, 'concepts': terms,
        })
        assert response.status_code == 200
        body = response.json()
        assert set(body['requested_concepts']) == expected
        assert not body['unavailable_concepts']
        assert all(fact['definition'] for fact in body['facts'])
    assert c.post('/api/semantic/context', json={
        'customer_id': 'CUST-S1', 'alert_id': 'OTHER', 'intent': 'kyc_review',
    }).status_code == 404


def test_regulatory_meaning_does_not_require_account_evidence(tmp_db_path):
    response = _client().get('/api/semantic/regulations')
    assert response.status_code == 200
    requirements = response.json()['requirements']
    assert {r['jurisdiction'] for r in requirements} == {'SG', 'HK'}
    assert len(requirements) == 5
    assert all(r['applicability_status'] == 'conditions_only' for r in requirements)
    assert all(r['fields'] and r['meaning'] and r['source_url'].startswith('https://') for r in requirements)
    owner = next(r for r in requirements if r['id'] == 'sg-owner')
    assert 'declaration.UBO' in owner['fields']
    assert owner['mapping_relation'] == 'related'
