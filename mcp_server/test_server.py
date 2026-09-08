"""Tests for the AML MCP client tools — the HTTP layer is mocked, so no live API.

Run:  cd mcp_server && python -m pytest test_server.py -q
"""
import os

import pytest

os.environ.setdefault("AML_API_BASE_URL", "http://test.local/api")

from aml_mcp import server  # noqa: E402


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """Records the last request and returns a canned payload."""
    last = {}

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None, headers=None):
        _FakeClient.last = {"method": "GET", "url": url, "params": params, "headers": headers}
        return _FakeResp({"ok": "get", "url": url, "params": params})

    def post(self, url, headers=None):
        _FakeClient.last = {"method": "POST", "url": url, "headers": headers}
        return _FakeResp({"ok": "post", "url": url})


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(server.httpx, "Client", _FakeClient)
    monkeypatch.setenv("AML_API_BASE_URL", "http://test.local/api")
    monkeypatch.delenv("AML_API_TOKEN", raising=False)


def test_suspicious_hits_right_path():
    server.is_customer_suspicious("CUST-1")
    assert _FakeClient.last["url"] == "http://test.local/api/customers/CUST-1/suspicious"
    assert _FakeClient.last["method"] == "GET"


def test_transactions_passes_limit():
    server.list_high_score_transactions("CUST-1", limit=5)
    assert _FakeClient.last["url"].endswith("/customers/CUST-1/transactions")
    assert _FakeClient.last["params"] == {"limit": 5}


def test_case_status_and_network_paths():
    server.get_case_status("CUST-2")
    assert _FakeClient.last["url"].endswith("/customers/CUST-2/case-status")
    server.get_customer_network_graph("CUST-2")
    assert _FakeClient.last["url"].endswith("/customers/CUST-2/network")


def test_trigger_investigation_is_a_post():
    server.trigger_investigation("CUST-3")
    assert _FakeClient.last["method"] == "POST"
    assert _FakeClient.last["url"].endswith("/customers/CUST-3/investigate")


def test_token_becomes_bearer_header(monkeypatch):
    monkeypatch.setenv("AML_API_TOKEN", "secret")
    server.is_customer_suspicious("CUST-1")
    assert _FakeClient.last["headers"]["Authorization"] == "Bearer secret"


def test_missing_base_url_raises(monkeypatch):
    monkeypatch.delenv("AML_API_BASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        server.is_customer_suspicious("CUST-1")
