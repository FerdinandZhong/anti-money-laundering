# aml-mcp

A stdio MCP server over the AML platform HTTP API. It has no database access or
independent investigation logic. Version **0.3.0** exposes **26 tools**, including
saved business reports, semantic/regulatory definitions and pinned KYC evidence.
It uses the MCP Python SDK v2 `MCPServer` API (`mcp>=2,<3`).

## Tools

All tools are annotated read-only except `trigger_investigation`.

| Area | Tools | API surface |
|---|---|---|
| Alert discovery | `list_alerts`, `get_alert_context` | `/alerts`, `/alerts/{id}` |
| Customer overview | `is_customer_suspicious`, `list_high_score_transactions`, `get_case_status`, `get_customer_network_graph` | `/customers/{id}/…` |
| Saved investigation | `get_latest_investigation`, `list_case_evidence`, `get_investigation_evidence` | `/cases/{id}/investigation/latest`, `/cases/{id}/evidence[/…]` |
| Semantic discovery | `get_aml_semantic_model`, `get_aml_semantic_contracts`, `get_aml_regulations`, `list_aml_investigation_intents` | `/semantic/model`, `/contracts`, `/regulations`, `/intents` |
| Meaning and facts | `resolve_aml_concept`, `get_aml_metric_definition`, `find_aml_relationship_path`, `get_case_semantic_context`, `query_case_facts` | `/semantic/concepts/…`, `/metrics/…`, `/relationships`, `/context`, `/query` |
| KYC evidence | `list_kyc_evidence`, `search_kyc_evidence`, `get_kyc_evidence_page` | `/alerts/{id}/knowledge[/…]` |
| Control assessments | `get_kyc_controls`, `list_kyc_assessments`, `get_kyc_assessment`, `replay_kyc_assessment` | `/alerts/{id}/controls[/…]` |
| Run investigation (**write**) | `trigger_investigation` | `POST /customers/{id}/investigate` |

Semantic context/query use POST but do not mutate business records. The
investigation tool creates a case if needed, retains evidence and updates the
saved analysis; it is not idempotent and is never automatically retried.
Disposition, labels, review submissions, assessment creation, retraining and
configuration changes are not exposed. `/alerts/{id}/detail` is intentionally
excluded because its GET creates a case. Use `get_alert_context` for discovery.

## Recommended agent workflow

1. Discover alerts with `list_alerts`, then call `get_alert_context` to obtain the
   exact account, cutoff and existing case ID. Browsing does not create a case.
2. If a case exists, read `get_latest_investigation` first. Present `business_report`
   before worker details. Recommended action and evidence completeness are separate:
   **escalation** can coexist with **additional information required**.
3. Explain data using model, metric, concept and regulatory definitions. For account
   facts, pass the selected `alert_id` to semantic context/query along with its
   customer and declared intent. Original contract YAML is available on request.
4. Follow `context_evidence_id` or worker `evidence_ids` into
   `get_investigation_evidence`; finding IDs are not evidence IDs. The API enforces
   case scope and retained-payload integrity. Missing evidence remains unavailable.
5. For document exploration, list the library, pin its `release_id`, run bilingual
   search, then read the returned document version/page. The page tool also returns
   an authenticated original-document URL; it does not return PDF bytes through JSON.
6. Request `trigger_investigation` when a new run is wanted. It returns the readable
   report, findings and verdicts. After a timeout, check saved status/report before
   deciding whether another run is needed.

Important source meanings:

- The legacy `is_customer_suspicious` flag means **active alerts exist**, not a
  conclusion that money laundering occurred.
- Customer transactions are a bounded recent outgoing sample, then sorted by
  model score. They are not the full historical account ledger or a global
  top-scoring transaction query. Use retained investigation metrics for that window.
- Customer network uses the primary account, which may differ from the selected
  alert. Use the saved investigation for its account/cutoff-specific network.
- The investigation POST selects the highest-risk active alert for the customer
  (otherwise the highest-risk alert). It cannot target an arbitrary selected alert.
- Document library/page reads may include later receipts. Search is cutoff-bound;
  use its returned version/page/release or a retained citation for historical claims.
- Regulatory meaning is discoverable even when documents are absent. Candidate
  relevance is not established applicability or proof of a violation.

## Configure in Agent Studio

Use the API root ending in `/api`, **not** `/api/docs`. Install from a release ref
containing these tools; a moving branch may require refreshing the client's uvx cache.

```json
{
  "mcpServers": {
    "aml-investigation": {
      "command": "uvx",
      "args": ["--from",
               "git+https://github.com/FerdinandZhong/anti-money-laundering@main#subdirectory=mcp_server",
               "aml-mcp"],
      "env": {
        "AML_API_BASE_URL": "https://aml-platform-vfcxn0.ml-16e5d8cb-7c9.qzhong-a.a465-9q4k.cloudera.site/api",
        "AML_API_TOKEN": "<credential accepted by this deployment, if required>"
      }
    }
  }
}
```

`AML_API_TOKEN` is sent only as a bearer header. Browser SSO is not inherited by
an Agent Studio MCP process. The deployment must accept the configured credential
on API requests. Login redirects, 401/403 and HTML responses produce actionable
MCP errors; the client does not follow redirects with its credential. Other API
errors (including integrity conflicts) are not converted into empty evidence.
Omit the token variable for an API that permits unauthenticated access.

## Contract check and tests

```bash
cd mcp_server
uv run --locked --group dev pytest test_server.py -q
# Reads OpenAPI only; does not run investigations or invoke business endpoints:
uv run --locked aml-mcp-check
# Or validate an exported schema when the hosted API requires browser SSO:
uv run --locked aml-mcp-check --schema /path/to/openapi.json
uv run --locked aml-mcp
```

The checker compares every registered tool's method/path and required input
coverage against OpenAPI. It does not certify authorization or response semantics.
Tests cover route wiring, selected-alert/release propagation, report preservation,
URL encoding, authentication errors, integrity/service errors, bounded inputs and
MCP read/write annotations. No investigation is triggered by the contract check.

On 2026-09-30, the supplied deployment redirected anonymous schema requests to
Cloudera login. Local API contract validation is available; deployed parity needs
an accepted API credential or an exported OpenAPI schema.
