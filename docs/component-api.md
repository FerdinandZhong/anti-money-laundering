# Component & API Reference

Swagger UI: `${API}/api/docs` · OpenAPI: `${API}/api/openapi.json`
(`${API}` = `http://127.0.0.1:8100` locally, or the CML app URL).

## Customer-centric API (what agents/MCP use)
| Route | Method | Notes |
|-------|--------|-------|
| `/api/customers/{id}/suspicious` | GET | suspicious if any OPEN/PROPOSED/PENDING alert |
| `/api/customers/{id}/transactions` | GET | ranked by model score |
| `/api/customers/{id}/case-status` | GET | never creates a case |
| `/api/customers/{id}/network` | GET | `{nodes, edges}` graph |
| `/api/customers/{id}/investigate` | POST | runs the workflow, persists + returns analysis (needs LLM) |

## Governed semantic API

The semantic layer is a versioned, Ossie-aligned YAML contract in `semantic/`.
It maps AML terms to the existing source/ops data and returns bounded context;
it does **not** expose raw SQL or direct database access.

| Route | Method | Purpose |
|---|---|---|
| `/api/semantic/regulations` | GET | regulatory meanings, applicability conditions and related business concepts |
| `/api/semantic/contracts` | GET | exact published semantic YAML sources |
| `/api/semantic/model` | GET | published model/version and discoverable datasets, metrics, relationships |
| `/api/semantic/intents` | GET | supported investigation intents and allowed concept scope |
| `/api/semantic/concepts/{term}` | GET | resolve a declared term or synonym, with definition/caveat |
| `/api/semantic/metrics/{metric}` | GET | governed metric definition and AI-use guidance |
| `/api/semantic/relationships?from_concept=&to_concept=` | GET | declared ontology path(s), not customer graph data |
| `/api/semantic/context` | POST | case-scoped facts, cutoff, evidence refs, allowed conclusions and limitations |
| `/api/semantic/query` | POST | approved facts for a customer, intent, and declared concepts |

`/context` and `/query` require `{ "customer_id", "intent" }`; `/query` also
requires `concepts`. Unknown or out-of-intent concepts are reported as
`unavailable_concepts` rather than guessed.

## MCP tools (`mcp_server/`, `aml-mcp` 0.3.0)
Thin stdio HTTP client with 26 tools. Configure Agent Studio with the `/api` root
and a credential the deployment accepts. Browser SSO is not inherited. Only
`trigger_investigation` mutates business records; read-only annotations also cover
semantic POST queries. See [MCP setup and workflow](../mcp_server/README.md).

| Tool | API route |
|------|-----------|
| `list_alerts(status, limit, offset, sort)` | `GET /api/alerts` |
| `get_alert_context(alert_id)` | `GET /api/alerts/{alert_id}`; no case creation |
| `is_customer_suspicious(customer_id)` | `GET /api/customers/{id}/suspicious`; active-alert presence |
| `list_high_score_transactions(customer_id, limit)` | `GET /api/customers/{id}/transactions`; bounded recent sample sorted by score |
| `get_case_status(customer_id)` | `GET /api/customers/{id}/case-status` |
| `get_customer_network_graph(customer_id)` | `GET /api/customers/{id}/network`; primary account |
| `trigger_investigation(customer_id)` | `POST /api/customers/{id}/investigate` (**write**, returns `business_report`) |
| `get_latest_investigation(case_id)` | `GET /api/cases/{id}/investigation/latest` |
| `list_case_evidence(case_id)` | `GET /api/cases/{id}/evidence` |
| `get_investigation_evidence(case_id, evidence_id)` | `GET /api/cases/{id}/evidence/{evidence_id}` |
| `get_aml_semantic_model()` | `GET /api/semantic/model` |
| `get_aml_semantic_contracts()` | `GET /api/semantic/contracts` |
| `get_aml_regulations()` | `GET /api/semantic/regulations` |
| `resolve_aml_concept(term)` | `GET /api/semantic/concepts/{term}` |
| `get_aml_metric_definition(metric)` | `GET /api/semantic/metrics/{metric}` |
| `list_aml_investigation_intents()` | `GET /api/semantic/intents` |
| `get_case_semantic_context(customer_id, intent, alert_id?)` | `POST /api/semantic/context` (read-only) |
| `query_case_facts(customer_id, intent, concepts, alert_id?)` | `POST /api/semantic/query` (read-only) |
| `find_aml_relationship_path(from_concept, to_concept)` | `GET /api/semantic/relationships` |
| `list_kyc_evidence(alert_id, release_id?)` | `GET /api/alerts/{id}/knowledge` |
| `search_kyc_evidence(alert_id, query, release_id, limit)` | `GET /api/alerts/{id}/knowledge/search` |
| `get_kyc_evidence_page(alert_id, version_id, page, release_id)` | `GET /api/alerts/{id}/knowledge/pages/{version_id}/{page}` plus original asset URL |
| `get_kyc_controls(alert_id, release_id?)` | `GET /api/alerts/{id}/controls` |
| `list_kyc_assessments(alert_id)` | `GET /api/alerts/{id}/controls/assessments` |
| `get_kyc_assessment(alert_id, assessment_id)` | `GET /api/alerts/{id}/controls/assessments/{assessment_id}` |
| `replay_kyc_assessment(alert_id, assessment_id)` | `GET /api/alerts/{id}/controls/assessments/{assessment_id}/replay` |

Read the saved business report before launching another investigation. It keeps
recommended action separate from evidence completeness. Use selected-alert
semantic context, cutoff-bound search and pinned document versions for historical
claims. Customer transaction/network shortcuts do not share that historical scope.
The customer investigation POST chooses the highest-risk active alert first; it
does not accept a selected alert ID. Alert detail GET creates a case and is excluded
from MCP reads. Disposition/reviews/retraining/configuration writes remain outside
this MCP surface.

`aml-mcp-check` compares the tools against deployed OpenAPI (or `--schema` JSON)
without invoking business tools. It checks route and required input coverage;
runtime authentication, integrity and response behavior need separate tests.

## Dashboard A — alerts & cases
| Route | Method |
|-------|--------|
| `/api/alerts?status=&limit=&sort=` · `/api/alerts/counts` | GET |
| `/api/alerts/{id}` · `/api/alerts/{id}/detail` | GET |
| `/api/cases/{id}/investigate` · `/dispose` · `/evidence` · `/transaction-labels` | POST/GET |

## Dashboard B — model ops
| Route | Method | Notes |
|-------|--------|-------|
| `/api/model/deployments` | GET | champion/canary rows |
| `/api/model/runs` | GET | training runs + metrics |
| `/api/model/score-histogram` | GET | transaction-score distribution (empty ⇒ scoring hasn't run) |
| `/api/model/alert-bands` | GET | open alerts by risk band |
| `/api/model/drift` | GET | PSI per feature |
| `/api/model/retrain` · `/api/model/retrain/stream` | POST | fire-and-forget / SSE |

## Config & health
| Route | Notes |
|-------|-------|
| `/api/health` · `/api/health/environment` | liveness; `source_backend`, `active_model`, `champion_artifact_present` |
| `/api/stats` | alert/case/label counts |
| `/api/config/llm[...]`, `/api/config/embedded[...]`, `/api/config/tools[...]` | Models / embedded MCP / verification servers |

## Frontend components
React 19 + Vite + Tailwind under `03_frontend/src/`. Key: `components/AgentPanel.tsx`
(agent findings/SSE), the alert queue + network graph views, and the ModelOps charts.
The frontend only ever calls `/api/*` (reverse-proxied to the backend).
