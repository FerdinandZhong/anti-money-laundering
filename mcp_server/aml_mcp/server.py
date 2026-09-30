"""MCP (stdio) server for the AML Investigation Platform.

A thin HTTP client over the platform's customer-centric API — it holds NO data
logic and NO DB access. Configure it inside Cloudera AI Studio (or any agent
framework) with the deployed API's base URL, e.g.:

    {
      "mcpServers": {
        "aml-investigation": {
          "command": "uvx",
          "args": ["--from",
                   "git+https://github.com/FerdinandZhong/anti-money-laundering#subdirectory=mcp_server",
                   "aml-mcp"],
          "env": {
            "AML_API_BASE_URL": "https://aml-platform.<domain>/api",
            "AML_API_TOKEN": "<optional bearer token>"
          }
        }
      }
    }

READ-ONLY CONTRACT: every tool is read-only EXCEPT `trigger_investigation`, which
runs the multi-agent analysis and persists it to the case (the API's only mutation
on this surface). Disposition / labels / retrain / config are not exposed.
"""
import os
from urllib.parse import quote, urlencode, urlsplit
from typing import Annotated, Literal

from pydantic import Field
from mcp.types import ToolAnnotations

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# MCP Python SDK v2 renamed FastMCP to MCPServer.  Keep the server name stable:
# Agent Studio and other MCP hosts show this during their initialization handshake.
mcp = MCPServer("aml-investigation")

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
INVESTIGATION_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)
Limit = Annotated[int, Field(ge=1, le=100)]
SearchLimit = Annotated[int, Field(ge=1, le=50)]

_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


def api_tool(method: str, path: str, write: bool = False):
    return mcp.tool(annotations=INVESTIGATION_WRITE if write else READ_ONLY,
                    meta={'aml_api': {'method': method, 'path': '/api' + path}})


def _base_url() -> str:
    url = os.environ.get("AML_API_BASE_URL", "").rstrip("/")
    if not url:
        raise ToolError("AML_API_BASE_URL is not set (e.g. https://aml-platform.<domain>/api)")
    parsed = urlsplit(url)
    if parsed.scheme not in {'https', 'http'} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.path.endswith('/api'):
        raise ToolError('AML_API_BASE_URL must be an HTTP(S) API root ending in /api, without credentials, query or fragment; do not use /api/docs.')
    return url


def _segment(value: str) -> str:
    if not value or value in {'.', '..'}:
        raise ToolError('A nonempty identifier or semantic term is required.')
    return quote(value, safe='')


def _limit(value: int, maximum: int = 100):
    if not 1 <= value <= maximum:
        raise ToolError(f'limit must be between 1 and {maximum}')


def _headers() -> dict:
    token = os.environ.get("AML_API_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _json_response(response: httpx.Response) -> dict:
    if response.status_code in {401, 403} or 300 <= response.status_code < 400:
        raise ToolError('AML API authentication is required or access was redirected. Configure AML_API_TOKEN with a credential accepted by the deployment; a browser login is not an MCP API session.')
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ToolError(f'AML API returned HTTP {response.status_code}. The requested scope, evidence integrity or service availability could not be confirmed; this is not an empty or clear result.') from exc
    if 'json' not in response.headers.get('content-type', '').lower():
        raise ToolError('AML API returned non-JSON content, possibly a login page. Check the API root and deployment authentication.')
    try:
        return response.json()
    except ValueError as exc:
        raise ToolError('AML API returned invalid JSON.') from exc


def _request(method: str, path: str, **kwargs) -> dict:
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as c:
            call = c.get if method == 'GET' else c.post
            return _json_response(call(f"{_base_url()}{path}", headers=_headers(), **kwargs))
    except httpx.TimeoutException as exc:
        raise ToolError('AML API request timed out. An investigation may still be running; check case status and the saved report before retrying a write.') from exc
    except httpx.RequestError as exc:
        raise ToolError('Cannot reach the configured AML API. Check its URL and network access.') from exc


def _get(path: str, params: dict | None = None) -> dict:
    return _request('GET', path, params=params)


def _post(path: str, body: dict | None = None) -> dict:
    # Do not automatically retry: investigation creates retained records.
    return _request('POST', path, **({'json': body} if body is not None else {}))


@api_tool("GET", "/alerts/{alert_id}/knowledge")
def list_kyc_evidence(alert_id: str, release_id: str | None = None) -> dict:
    """List versioned KYC documents in this alert's customer/account scope.

    The library may include later receipts and illustrative fixtures; these are
    not verified customer facts. Use search_kyc_evidence for cutoff-bound search.
    """
    return _get(f"/alerts/{_segment(alert_id)}/knowledge", params={"release": release_id} if release_id else None)


@api_tool("GET", "/alerts/{alert_id}/knowledge/search")
def search_kyc_evidence(alert_id: str, query: str, release_id: str, limit: SearchLimit = 10) -> dict:
    """Read-only bilingual evidence search using the alert's recorded cutoff.

    Pass release_id from list_kyc_evidence to pin citations. Results include page,
    source version and OCR evidence. Similarity is not proof of correctness;
    illustrative fixtures must never be presented as verified customer records.
    """
    _limit(limit, 50)
    if not query.strip() or len(query) > 1000 or not release_id.strip():
        raise ToolError("Provide a query of 1–1000 characters and the release ID from the document library.")
    return _get(f"/alerts/{_segment(alert_id)}/knowledge/search",
                params={'q':query,'release':release_id,'limit':limit})


@api_tool("GET", "/alerts/{alert_id}/controls")
def get_kyc_controls(alert_id: str, release_id: str | None = None) -> dict:
    """Read deterministic synthetic KYC controls and cited evidence at the alert cutoff.

    Requires explicit demo enablement. Outcomes include missing sources, ownership
    paths and decimal activity calculations; they are not legal certification.
    """
    return _get(f"/alerts/{_segment(alert_id)}/controls", params={"release": release_id} if release_id else None)


@api_tool("GET", "/alerts/{alert_id}/controls/assessments/{assessment_id}/replay")
def replay_kyc_assessment(alert_id: str, assessment_id: str) -> dict:
    """Read-only replay of a previously retained assessment from its saved inputs."""
    return _get(f"/alerts/{_segment(alert_id)}/controls/assessments/{_segment(assessment_id)}/replay")


@api_tool("GET", "/customers/{customer_id}/suspicious")
def is_customer_suspicious(customer_id: str) -> dict:
    """Check whether the customer has active alerts (OPEN, PROPOSED, PENDING).
    The API's suspicious flag means active alert presence, not an investigation
    conclusion or proof of wrongdoing. Returns alerts and prioritisation scores.
    Read-only."""
    return _get(f"/customers/{_segment(customer_id)}/suspicious")


@api_tool("GET", "/customers/{customer_id}/transactions")
def list_high_score_transactions(customer_id: str, limit: Limit = 20) -> dict:
    """Return the API's bounded customer transaction sample, sorted by model score.
    Not a complete alert-cutoff ledger or a global top-score guarantee. For full
    historical activity calculations use the saved investigation. Read-only."""
    _limit(limit)
    return _get(f"/customers/{_segment(customer_id)}/transactions", params={"limit": limit})


@api_tool("GET", "/customers/{customer_id}/case-status")
def get_case_status(customer_id: str) -> dict:
    """Current analyst-processing status for the customer's case: state, disposition,
    whether an AI analysis exists, and any analyst annotations. Read-only — does not
    create a case if none exists yet."""
    return _get(f"/customers/{_segment(customer_id)}/case-status")


@api_tool("GET", "/customers/{customer_id}/network")
def get_customer_network_graph(customer_id: str) -> dict:
    """Fund-flow + shared-device network graph around the customer's primary account:
    {nodes, edges}. The primary account may differ from a selected alert account;
    use retained investigation findings for that alert's historical network. Read-only."""
    return _get(f"/customers/{_segment(customer_id)}/network")


@api_tool("GET", "/semantic/concepts/{term}")
def resolve_aml_concept(term: str) -> dict:
    """Resolve a governed AML business term by name or synonym. Returns its
    definition, semantic type, permitted use, and caveats. Use this before
    interpreting terms such as risk score, expected turnover, or observed flow.
    Read-only."""
    return _get(f"/semantic/concepts/{_segment(term)}")


@api_tool("GET", "/semantic/metrics/{metric}")
def get_aml_metric_definition(metric: str) -> dict:
    """Return the governed definition of an AML metric, including its intended
    scope and AI-use guidance. For example, account_priority_score is a daily
    analyst-prioritisation score, not a probability of financial crime.
    Read-only."""
    return _get(f"/semantic/metrics/{_segment(metric)}")


@api_tool("GET", "/semantic/intents")
def list_aml_investigation_intents() -> dict:
    """List supported AML investigation intents and the concepts each may use:
    score_explanation, kyc_review, pattern_analysis, network_review, and
    case_narration. Read-only."""
    return _get("/semantic/intents")


@api_tool("POST", "/semantic/context")
def get_case_semantic_context(customer_id: str, intent: str, alert_id: str | None = None) -> dict:
    """Return the governed, case-scoped fact bundle for one customer and one
    declared investigation intent. Includes cutoff, account scope, definitions,
    evidence references, allowed conclusions, and claim limitations. Read-only."""
    body = {"customer_id": customer_id, "intent": intent}
    if alert_id:
        body["alert_id"] = alert_id
    return _post("/semantic/context", body)


@api_tool("POST", "/semantic/query")
def query_case_facts(customer_id: str, intent: str, concepts: list[str], alert_id: str | None = None) -> dict:
    """Retrieve only approved semantic facts for a customer and investigation
    intent. This is not a free-form SQL interface: unavailable concepts are
    returned explicitly rather than inferred. Read-only."""
    body = {
        "customer_id": customer_id, "intent": intent, "concepts": concepts,
    }
    if alert_id:
        body["alert_id"] = alert_id
    return _post("/semantic/query", body)


@api_tool("GET", "/semantic/relationships")
def find_aml_relationship_path(from_concept: str, to_concept: str) -> dict:
    """Explain declared AML ontology paths between two concepts, for example
    Customer to Transaction. Returns semantic relationships, not customer data.
    Read-only."""
    return _get("/semantic/relationships", {
        "from_concept": from_concept, "to_concept": to_concept,
    })


@api_tool("POST", "/customers/{customer_id}/investigate", write=True)
def trigger_investigation(customer_id: str) -> dict:
    """Run the multi-agent AI investigation for the customer's case and return the
    analysis. THE ONLY MUTATING TOOL: creates a case if needed, retains evidence,
    and updates the saved analysis. Chooses the customer's highest-risk active
    alert first (otherwise the highest-risk alert); cannot select an arbitrary alert.
    Returns {case_id, analysis, business_report, verdicts, worker_findings}.
    business_report separates recommended action from evidence completeness.
    May take several minutes. Read an existing report before requesting a new run;
    after a timeout inspect saved status/report before retrying."""
    return _post(f"/customers/{_segment(customer_id)}/investigate")


@api_tool("GET", "/alerts")
def list_alerts(status: Literal['OPEN', 'PROPOSED', 'PENDING', 'CLOSED'] = 'OPEN',
                limit: Limit = 20, offset: Annotated[int, Field(ge=0)] = 0,
                sort: Literal['risk_score', 'newest', 'oldest'] = 'risk_score') -> dict:
    """Discover alerts and their customer/account IDs, with pagination. Read-only.
    Scores prioritise review; they are not probabilities of financial crime.
    """
    _limit(limit)
    if offset < 0:
        raise ToolError('offset must be nonnegative')
    return _get('/alerts', {'status': status, 'limit': limit, 'offset': offset, 'sort': sort})


@api_tool("GET", "/alerts/{alert_id}")
def get_alert_context(alert_id: str) -> dict:
    """Read the selected alert's account, cutoff and existing case, if any.
    Never creates a case. Use its case_id for saved investigation/evidence reads.
    """
    return _get(f'/alerts/{_segment(alert_id)}')


@api_tool("GET", "/cases/{case_id}/investigation/latest")
def get_latest_investigation(case_id: str) -> dict:
    """Read a saved investigation without rerunning workers or changing the case.
    Includes business_report, recommendation, supporting-information status,
    recorded worker findings and retained context reference. available=false
    means no saved report, not that the account is clear. Source integrity errors
    remain errors. Present the business report first, with evidence on demand.
    """
    return _get(f'/cases/{_segment(case_id)}/investigation/latest')


@api_tool("GET", "/cases/{case_id}/evidence")
def list_case_evidence(case_id: str) -> dict:
    """List retained evidence metadata for a case. Fetch a selected payload with
    get_investigation_evidence; metadata alone does not establish its contents.
    """
    return _get(f'/cases/{_segment(case_id)}/evidence')


@api_tool("GET", "/cases/{case_id}/evidence/{evidence_id}")
def get_investigation_evidence(case_id: str, evidence_id: str) -> dict:
    """Read an integrity-checked retained input or finding payload within its case.
    Use evidence_id/context_evidence_id, not a finding ID. The backend enforces
    case scope and hash checks. Legacy payloads may be unavailable. Read-only.
    """
    return _get(f'/cases/{_segment(case_id)}/evidence/{_segment(evidence_id)}')


@api_tool("GET", "/semantic/model")
def get_aml_semantic_model() -> dict:
    """Discover published AML datasets, metrics, relationships and model version.
    Definitions explain data meaning; fetch scoped facts separately. Read-only.
    """
    return _get('/semantic/model')


@api_tool("GET", "/semantic/contracts")
def get_aml_semantic_contracts() -> dict:
    """Read original published Ossie-style YAML and AML semantic extensions.
    These are model definitions, not account evidence or compliance conclusions.
    """
    return _get('/semantic/contracts')


@api_tool("GET", "/semantic/regulations")
def get_aml_regulations() -> dict:
    """Read regulatory meanings, conditions, evidence types and business mappings.
    Available independently of an account's KYC evidence. Candidate relevance
    does not establish applicability, an approved interpretation or a violation.
    """
    return _get('/semantic/regulations')


@api_tool("GET", "/alerts/{alert_id}/knowledge/pages/{version_id}/{page}")
def get_kyc_evidence_page(alert_id: str, version_id: str,
                          page: Annotated[int, Field(ge=1)], release_id: str) -> dict:
    """Read extracted text/OCR chunks for one document page in a pinned release.
    Use version/page/release from cutoff-bound search or a retained citation.
    This page endpoint enforces account scope, not the alert cutoff; later
    receipts must remain later context. OCR text is not verified fact. Returns
    the original document URL for inspection (requires deployment authentication).
    """
    if page < 1 or not release_id.strip():
        raise ToolError('A positive page number and pinned release ID are required.')
    result = _get(f'/alerts/{_segment(alert_id)}/knowledge/pages/{_segment(version_id)}/{page}',
                  {'release': release_id})
    return {**result, 'document_url': f'{_base_url()}/alerts/{_segment(alert_id)}/knowledge/assets/{_segment(version_id)}?'
            + urlencode({'release': release_id})}


@api_tool("GET", "/alerts/{alert_id}/controls/assessments")
def list_kyc_assessments(alert_id: str) -> dict:
    """Discover saved control assessment IDs and dates for this alert. Read-only.
    Does not save a new assessment or change a review decision.
    """
    return _get(f'/alerts/{_segment(alert_id)}/controls/assessments')


@api_tool("GET", "/alerts/{alert_id}/controls/assessments/{assessment_id}")
def get_kyc_assessment(alert_id: str, assessment_id: str) -> dict:
    """Read a retained control assessment and review events in this alert's scope.
    Preserves original evidence and integrity checks; does not create or review it.
    """
    return _get(f'/alerts/{_segment(alert_id)}/controls/assessments/{_segment(assessment_id)}')


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
