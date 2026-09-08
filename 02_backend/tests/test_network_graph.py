def test_fund_flow_edges_aggregates_by_pair():
    from common.source import fund_flow_edges
    txns = [
        {"direction": "INBOUND", "from_account_id": "ACC-N-001", "to_account_id": "ACC-ROOT",
         "amount": 40000.0, "counterparty_name": "Sender_001", "counterparty_country": "SG"},
        {"direction": "INBOUND", "from_account_id": "ACC-N-001", "to_account_id": "ACC-ROOT",
         "amount": 8200.0, "counterparty_name": "Sender_001", "counterparty_country": "SG"},
        {"direction": "OUTBOUND", "from_account_id": "ACC-ROOT", "to_account_id": None,
         "amount": 190000.0, "counterparty_name": "Oversea Beneficiary 1 Ltd", "counterparty_country": "CN"},
    ]
    edges = fund_flow_edges(txns, "ACC-ROOT")
    inbound = [e for e in edges if e["target"] == "ACC-ROOT"]
    assert len(inbound) == 1
    assert inbound[0]["source"] == "ACC-N-001"
    assert inbound[0]["amount"] == 48200.0 and inbound[0]["count"] == 2
    outbound = [e for e in edges if e["source"] == "ACC-ROOT"]
    assert outbound[0]["target"] == "Oversea Beneficiary 1 Ltd"
    assert all(e["relation"] == "fund_flow" for e in edges)


def test_fund_flow_edges_empty():
    from common.source import fund_flow_edges
    assert fund_flow_edges([], "ACC-ROOT") == []


def test_get_network_graph_lone_account_is_failsoft(monkeypatch):
    from agents import tools
    monkeypatch.setattr(tools.source, "device_fingerprints", lambda a: [])
    monkeypatch.setattr(tools.source, "accounts_by_fingerprints", lambda f: [])
    monkeypatch.setattr(tools.source, "account_transactions", lambda a, limit=200: [])
    monkeypatch.setattr(tools.source, "get_account", lambda a: None)
    g = tools.get_network_graph(None, "ACC-LONE")
    assert g == {"nodes": [{"id": "ACC-LONE", "type": "collector", "is_root": True, "label": "ACC-LONE"}], "edges": []}


def test_get_network_graph_funnel(monkeypatch):
    from agents import tools
    monkeypatch.setattr(tools.source, "device_fingerprints", lambda a: ["FP-1"])
    monkeypatch.setattr(tools.source, "accounts_by_fingerprints", lambda f: ["ACC-ROOT", "ACC-N-001"])
    monkeypatch.setattr(tools.source, "account_transactions", lambda a, limit=200: [
        {"direction": "INBOUND", "from_account_id": "ACC-N-001", "to_account_id": "ACC-ROOT", "amount": 48200.0},
        {"direction": "OUTBOUND", "from_account_id": "ACC-ROOT", "to_account_id": None,
         "amount": 190000.0, "counterparty_name": "Oversea Beneficiary 1 Ltd"},
    ])
    g = tools.get_network_graph(None, "ACC-ROOT")
    types = {n["id"]: n["type"] for n in g["nodes"]}
    assert types["ACC-ROOT"] == "collector"
    assert types["ACC-N-001"] == "source"
    assert types["Oversea Beneficiary 1 Ltd"] == "beneficiary"
    relations = {e["relation"] for e in g["edges"]}
    assert relations == {"shared_device", "fund_flow"}
