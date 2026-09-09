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
