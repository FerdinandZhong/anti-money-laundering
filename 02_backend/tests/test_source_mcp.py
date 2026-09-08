# 02_backend/tests/test_source_mcp.py
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fake_params(monkeypatch, present=True):
    from common import mcp_client
    monkeypatch.setattr(mcp_client, "embedded_params",
                        lambda name: {"impala_host": "h"} if present else None)


def test_backend_resolves_mcp_when_configured(monkeypatch):
    from common import source, mcp_client
    source.reset_backend()
    _fake_params(monkeypatch, True)
    monkeypatch.setattr(mcp_client, "list_embedded_tools",
                        lambda name: [{"name": "execute_query"}])
    assert source.backend() == "mcp"
    source.reset_backend()


def test_backend_falls_back_when_unconfigured(monkeypatch):
    from common import source
    source.reset_backend()
    _fake_params(monkeypatch, False)
    assert source.backend() in ("csv", "impala")   # existing auto logic
    source.reset_backend()


def test_backend_falls_back_when_probe_fails(monkeypatch):
    from common import source, mcp_client
    source.reset_backend()
    _fake_params(monkeypatch, True)
    monkeypatch.setattr(mcp_client, "list_embedded_tools", lambda name: None)
    assert source.backend() in ("csv", "impala")
    source.reset_backend()


def test_mcp_df_parses_json_rows(monkeypatch):
    from common import source, mcp_client
    rows = [{"account_id": "A1", "amount": 5.0}]
    monkeypatch.setattr(mcp_client, "call_embedded",
                        lambda name, tool, args: json.dumps(rows))
    df = source._mcp_df("SELECT 1")
    assert list(df["account_id"]) == ["A1"]


def test_mcp_df_error_raises(monkeypatch):
    from common import source, mcp_client
    monkeypatch.setattr(mcp_client, "call_embedded",
                        lambda name, tool, args: {"error": "boom"})
    import pytest
    with pytest.raises(RuntimeError):
        source._mcp_df("SELECT 1")


def test_get_account_via_mcp(monkeypatch):
    from common import source, mcp_client
    source.reset_backend()
    _fake_params(monkeypatch, True)
    monkeypatch.setattr(mcp_client, "list_embedded_tools",
                        lambda name: [{"name": "execute_query"}])
    captured = {}
    def fake_call(name, tool, args):
        captured["query"] = args["query"]
        return json.dumps([{"account_id": "ACC-1", "customer_id": "CUST-1"}])
    monkeypatch.setattr(mcp_client, "call_embedded", fake_call)
    acc = source.get_account("ACC-1")
    assert acc["customer_id"] == "CUST-1"
    assert "'ACC-1'" in captured["query"]  # param was inlined + single-quoted for MCP
    source.reset_backend()
