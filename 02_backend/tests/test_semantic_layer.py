"""Tests for the governed AML semantic contract and HTTP surface."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def _seed(conn):
    now = datetime.now(timezone.utc).isoformat()
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
