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

## MCP tools (`mcp_server/`, `aml-mcp`)
Thin stdio HTTP client over the API — configure in Cloudera AI Agent Studio / any MCP
client pointing at the deployed API. Only `trigger_investigation` mutates.

| Tool | API route |
|------|-----------|
| `is_customer_suspicious(id)` | `GET /api/customers/{id}/suspicious` |
| `list_high_score_transactions(id, limit=20)` | `GET /api/customers/{id}/transactions` |
| `get_case_status(id)` | `GET /api/customers/{id}/case-status` |
| `get_customer_network_graph(id)` | `GET /api/customers/{id}/network` |
| `trigger_investigation(id)` | `POST /api/customers/{id}/investigate` (write) |
| `resolve_aml_concept(term)` | `GET /api/semantic/concepts/{term}` |
| `get_aml_metric_definition(metric)` | `GET /api/semantic/metrics/{metric}` |
| `list_aml_investigation_intents()` | `GET /api/semantic/intents` |
| `get_case_semantic_context(id, intent)` | `POST /api/semantic/context` |
| `query_case_facts(id, intent, concepts)` | `POST /api/semantic/query` |
| `find_aml_relationship_path(from, to)` | `GET /api/semantic/relationships` |

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
