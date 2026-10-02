"""Tests for the AML MCP client tools — the HTTP layer is mocked, so no live API.

Run:  cd mcp_server && uv run --locked --group dev pytest test_server.py -q
"""
import os
import asyncio

import httpx

import pytest

os.environ.setdefault("AML_API_BASE_URL", "http://test.local/api")

from aml_mcp import server  # noqa: E402


class _FakeResp:
    status_code = 200
    headers = {'content-type': 'application/json'}
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
        _FakeClient.options = k

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None, headers=None):
        _FakeClient.last = {"method": "GET", "url": url, "params": params, "headers": headers}
        return _FakeResp({"ok": "get", "url": url, "params": params})

    def post(self, url, headers=None, json=None):
        _FakeClient.last = {"method": "POST", "url": url, "headers": headers, "json": json}
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


def test_semantic_context_posts_governed_request():
    server.get_case_semantic_context("CUST-4", "score_explanation")
    assert _FakeClient.last["url"].endswith("/semantic/context")
    assert _FakeClient.last["json"] == {"customer_id": "CUST-4", "intent": "score_explanation"}


def test_semantic_discovery_paths():
    server.resolve_aml_concept("risk score")
    assert _FakeClient.last["url"].endswith("/semantic/concepts/risk%20score")
    server.query_case_facts("CUST-4", "kyc_review", ["expected turnover"])
    assert _FakeClient.last["url"].endswith("/semantic/query")
    assert _FakeClient.last["json"]["concepts"] == ["expected turnover"]
    server.find_aml_relationship_path("Customer", "Transaction")
    assert _FakeClient.last["params"] == {"from_concept": "Customer", "to_concept": "Transaction"}


def test_token_becomes_bearer_header(monkeypatch):
    monkeypatch.setenv("AML_API_TOKEN", "secret")
    server.is_customer_suspicious("CUST-1")
    assert _FakeClient.last["headers"]["Authorization"] == "Bearer secret"


def test_kyc_search_pins_release_and_preserves_bilingual_query():
    server.list_kyc_evidence("ALERT-1")
    assert _FakeClient.last["url"].endswith("/alerts/ALERT-1/knowledge")
    server.search_kyc_evidence("ALERT-1", "受益所有人 ultimate owner", "kyc-demo", limit=3)
    assert _FakeClient.last["url"].endswith("/alerts/ALERT-1/knowledge/search")
    assert _FakeClient.last["params"] == {
        "q": "受益所有人 ultimate owner", "release": "kyc-demo", "limit": 3,
    }


def test_missing_base_url_raises(monkeypatch):
    monkeypatch.delenv("AML_API_BASE_URL", raising=False)
    with pytest.raises(server.ToolError):
        server.is_customer_suspicious("CUST-1")


def test_kyc_controls_and_replay_are_scoped_reads():
    server.get_kyc_controls('ALERT-1')
    assert _FakeClient.last['url'].endswith('/alerts/ALERT-1/controls')
    server.replay_kyc_assessment('ALERT-1','assessment-123')
    assert _FakeClient.last['url'].endswith('/alerts/ALERT-1/controls/assessments/assessment-123/replay')
    assert _FakeClient.last['method']=='GET'


@pytest.mark.parametrize('name,args,path', [
    ('get_alert_context', ['ALERT-1'], '/alerts/ALERT-1'),
    ('get_latest_investigation', ['CASE-1'], '/cases/CASE-1/investigation/latest'),
    ('list_case_evidence', ['CASE-1'], '/cases/CASE-1/evidence'),
    ('get_investigation_evidence', ['CASE-1', 'EVD-1'], '/cases/CASE-1/evidence/EVD-1'),
    ('get_aml_semantic_model', [], '/semantic/model'),
    ('get_aml_semantic_contracts', [], '/semantic/contracts'),
    ('get_aml_regulations', [], '/semantic/regulations'),
    ('list_kyc_assessments', ['ALERT-1'], '/alerts/ALERT-1/controls/assessments'),
    ('get_kyc_assessment', ['ALERT-1', 'ASSESS-1'], '/alerts/ALERT-1/controls/assessments/ASSESS-1'),
])
def test_new_reads_use_exact_paths_without_mutation(name, args, path):
    getattr(server, name)(*args)
    assert _FakeClient.last['method'] == 'GET'
    assert _FakeClient.last['url'] == 'http://test.local/api' + path


def test_discovery_paginates_and_never_uses_case_creating_detail():
    server.list_alerts(limit=5, offset=10, sort='newest')
    assert _FakeClient.last['params'] == {'status': 'OPEN', 'limit': 5, 'offset': 10, 'sort': 'newest'}
    server.get_alert_context('ALERT-1')
    assert not _FakeClient.last['url'].endswith('/detail')


def test_release_pins_library_controls_and_page():
    server.list_kyc_evidence('ALERT-1', release_id='kyc-release')
    assert _FakeClient.last['params'] == {'release': 'kyc-release'}
    server.get_kyc_controls('ALERT-1', release_id='kyc-release')
    assert _FakeClient.last['params'] == {'release': 'kyc-release'}
    result = server.get_kyc_evidence_page('ALERT-1', 'VERSION-1', 2, 'kyc-release')
    assert _FakeClient.last['url'].endswith('/knowledge/pages/VERSION-1/2')
    assert _FakeClient.last['params'] == {'release': 'kyc-release'}
    assert result['document_url'] == 'http://test.local/api/alerts/ALERT-1/knowledge/assets/VERSION-1?release=kyc-release'


def test_semantic_posts_keep_selected_alert_scope():
    server.get_case_semantic_context('CUST-1', 'kyc_review', alert_id='ALERT-2')
    assert _FakeClient.last['json']['alert_id'] == 'ALERT-2'
    server.query_case_facts('CUST-1', 'kyc_review', ['beneficial owner'], alert_id='ALERT-2')
    assert _FakeClient.last['json']['alert_id'] == 'ALERT-2'


def test_identifiers_and_bilingual_terms_are_path_encoded():
    server.get_case_status('CUST?x=1#fragment')
    assert '/CUST%3Fx%3D1%23fragment/' in _FakeClient.last['url']
    server.resolve_aml_concept('受益所有人 / owner')
    assert _FakeClient.last['url'].endswith('/%E5%8F%97%E7%9B%8A%E6%89%80%E6%9C%89%E4%BA%BA%20%2F%20owner')


@pytest.mark.parametrize('status', [302, 307, 401, 403])
def test_authentication_redirect_is_not_followed_or_parsed_as_json(status):
    response = httpx.Response(status, headers={'location': 'https://login.example/'}, request=httpx.Request('GET', 'http://test.local/api/alerts'))
    with pytest.raises(server.ToolError, match='authentication'):
        server._json_response(response)
    server.list_alerts()
    assert _FakeClient.options['follow_redirects'] is False


def test_html_login_success_is_not_api_success():
    response = httpx.Response(200, headers={'content-type': 'text/html'}, text='<html>login</html>', request=httpx.Request('GET', 'http://test.local/api/alerts'))
    with pytest.raises(server.ToolError, match='non-JSON'):
        server._json_response(response)


@pytest.mark.parametrize('status', [404, 409, 422, 503])
def test_api_errors_are_not_replaced_with_empty_evidence(status):
    response = httpx.Response(status, json={'detail': 'unavailable'}, request=httpx.Request('GET', 'http://test.local/api/evidence'))
    with pytest.raises(server.ToolError, match=f'HTTP {status}'):
        server._json_response(response)


def test_saved_report_and_unavailability_pass_through(monkeypatch):
    payload = {'available': True, 'business_report': {'recommendation': 'Escalate for further investigation',
               'evidence_completeness': {'status': 'incomplete'}}, 'recommendation': {'disposition': 'SUSPICIOUS'}}
    monkeypatch.setattr(_FakeClient, 'get', lambda *args, **kw: _FakeResp(payload))
    assert server.get_latest_investigation('CASE-1') == payload
    payload['available'] = False
    assert server.get_latest_investigation('CASE-1')['available'] is False


@pytest.mark.parametrize('url', ['https://host/api/docs', 'https://host/api?token=secret', 'https://user:secret@host/api', 'file:///api'])
def test_base_url_rejects_docs_and_embedded_credentials(monkeypatch, url):
    monkeypatch.setenv('AML_API_BASE_URL', url)
    with pytest.raises(server.ToolError, match='API root'):
        server.list_alerts()


def test_mcp_schema_declares_one_mutation_and_bounded_reads():
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert len(tools) == 26
    assert [name for name, t in tools.items() if not t.annotations.read_only_hint] == ['trigger_investigation']
    assert tools['get_case_semantic_context'].annotations.read_only_hint
    assert tools['query_case_facts'].annotations.read_only_hint
    assert not tools['trigger_investigation'].annotations.idempotent_hint
    assert tools['search_kyc_evidence'].input_schema['properties']['limit']['maximum'] == 50
    assert tools['list_alerts'].input_schema['properties']['limit']['minimum'] == 1


def test_sdk_rejects_unbounded_request_before_http():
    _FakeClient.last = {}
    with pytest.raises(server.ToolError, match='greater than or equal to 1'):
        asyncio.run(server.mcp.call_tool('list_alerts', {'limit': -1}))
    assert _FakeClient.last == {}


def test_contract_check_detects_missing_routes_and_new_required_fields():
    from aml_mcp.contract import compare
    tools = asyncio.run(server.mcp.list_tools())
    document = {'openapi': '3.1.0', 'paths': {}}
    for t in tools:
        route = t.meta['aml_api']
        document['paths'].setdefault(route['path'], {})[route['method'].lower()] = {}
    assert asyncio.run(compare(document))['compatible']
    del document['paths']['/api/cases/{case_id}/investigation/latest']
    document['paths']['/api/semantic/query']['post']['parameters'] = [{'name': 'new_required_scope', 'required': True}]
    result = asyncio.run(compare(document))
    failed = {t['tool'] for t in result['tools'] if not t['compatible']}
    assert failed == {'get_latest_investigation', 'query_case_facts'}


def test_sdk_preserves_actionable_authentication_error(monkeypatch):
    monkeypatch.setattr(_FakeClient, 'get', lambda *a, **kw: httpx.Response(302))
    with pytest.raises(server.ToolError, match='AML_API_TOKEN'):
        asyncio.run(server.mcp.call_tool('list_alerts', {}))


def test_investigation_timeout_does_not_retry_the_write(monkeypatch):
    calls = []
    def timeout(*args, **kwargs):
        calls.append(kwargs)
        raise httpx.ReadTimeout('slow response')
    monkeypatch.setattr(_FakeClient, 'post', timeout)
    with pytest.raises(server.ToolError, match='before retrying a write'):
        server.trigger_investigation('CUST-1')
    assert len(calls) == 1
