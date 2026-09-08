# AML Investigation Platform

A Cloudera AI (CAI) AMP for intelligent anti-money-laundering investigation and continuous model learning. Ships two dashboards, a multi-agent investigation workbench, an XGBoost risk model, and a governed retrain/canary/rollback lifecycle — all in one CAI application.

## Dashboards

| Dashboard | Route | Audience |
|-----------|-------|----------|
| **Dashboard A — Investigation** | `/investigation` | AML investigators / analysts |
| **Dashboard B — Model Ops / MRM** | `/modelops` | Data scientists, model risk managers |

Dashboard A surfaces the case queue, transaction graph, agent findings, and disposition controls. Dashboard B exposes model performance metrics, the retrain pipeline, canary deployment status, and rollback controls.

## Architecture

```
CAI Application
├── FastAPI backend  (localhost:7078)   ← co-located, not exposed
│   ├── /api/cases        case management
│   ├── /api/investigate  multi-agent orchestration
│   ├── /api/model        scoring, retrain, canary, rollback
│   └── /api/alerts       real-time alert stream
└── React frontend  (CDSW_APP_PORT)    ← public-facing
    ├── /investigation    Dashboard A
    └── /modelops         Dashboard B
        (proxies /api/* → localhost:7078)
```

**Agent layer** — Supervisor + 4 specialist workers:
- `GraphAnalystAgent` — transaction network / entity resolution
- `PatternDetectorAgent` — typology matching (layering, structuring, smurfing)
- `RegulatoryAgent` — FATF / FinCEN red-flag cross-reference
- `NarrativeAgent` — SAR draft generation

**ML stack** — XGBoost classifier with SHAP explainability, SQLite feature store, versioned model registry, canary shadow-scoring.

## Quick Start

```bash
# 1. Install
python 01_installer/install.py

# 2. Configure
cp config/config.yaml.example config/config.yaml
# Edit config/config.yaml — set your CAII endpoint and model ID

# 3. Build data & model (first run only)
python 02_backend/data_generation/generate_synthetic_data.py
python 02_backend/scripts/export_source_csv.py   # source layer CSV fallback
cd 02_backend && python -m ml.train && cd ..     # trains + promotes to CHAMPION
cd 02_backend && python -m ml.scorer && cd ..    # scores transactions -> alerts

# 4. Run
python start_app.py
# → http://localhost:8100/investigation
# → http://localhost:8100/modelops
```

## Alert scoring (batch job → prod seam)

Alerts are **not** hand-authored — they are produced by a batch scoring job that
runs the champion XGBoost model over transactions:

```bash
python -m ml.scorer   # run from 02_backend/ ; idempotent (dedupes by account)
```

`ml/scorer.py` scores every transaction, aggregates by account into a composite
risk score (model signal + velocity + fund flow + shared-device + cross-border),
and inserts one `ALERT-ML-…` row for each of the **top `TARGET_ALERTS` (default 20)**
highest-composite accounts. Top-N (rather than a fixed score threshold) keeps the
daily queue a stable, reviewable size — a freshly retrained model scores more or
less aggressively run-to-run, so a hard threshold made the queue swing wildly.
The app reads the same `alerts` table and assembles case detail on-read
(`GET /api/alerts/{id}/detail`), joining `alerts → customers → transactions`.

**Prod:** schedule this command as a daily job (CML Job / cron / Airflow) against
the real database (point `config.model.model_dir` and the DB path at prod). No API
or frontend change is required — swapping the synthetic DB for the prod DB reuses
the same app end-to-end.

**Demo narration — where the alerts come from:** the queue is not hand-authored.
Each night the batch job (`python -m ml.scorer`) scores that day's transactions with
the champion model and inserts a fresh set of `ALERT-ML-*` rows. So every morning the
analyst opens the app to a new, risk-ranked queue of flagged accounts to work — the
same way a real CML Job would feed the platform daily.

### MCP tool servers + verification agent (the agent loop)

The four investigation workers each make a single LLM call over local tools. A
fifth **verification worker** turns the flow into a real agent loop: it extracts
the collectors' key factual claims (PEP/sanctions/adverse-media assertions, entity
links) and runs a bounded tool-calling loop against a configured **MCP server** to
confirm or refute each, returning per-claim verdicts (`confirmed` / `refuted` /
`unverified`) with sources.

Configure servers in the **Tools** tab (persisted in the ops `tool_config` table):

- **Embedded Cloudera MCP servers** — two parameter cards:
  [iceberg-mcp-server](https://github.com/cloudera/iceberg-mcp-server) (Impala
  host/port/user/password/database) feeds the investigation agents' Iceberg
  reads, and [CAI_Workbench_MCP_Server](https://github.com/cloudera/CAI_Workbench_MCP_Server)
  (Workbench host/API key/project ID) drives the retraining workflow's training
  job + canary deployment. Both are spawned on demand over stdio via `uvx`.
  **Leave a card blank and the app runs fully locally** — investigation reads
  the CSV dataset, retraining trains in-process with a simulated canary.
- **Custom verification servers** — remote streamable-HTTP MCP servers the
  verification worker calls to confirm/refute findings, as before.

When it runs, the investigation stream adds a `VERIFYING` phase and renders verdict
chips + source links. **Everything fails soft:** with no MCP server configured (or
a model that can't tool-call), the workflow behaves exactly as before — no
`VERIFYING` phase, no errors.

```bash
python -m common.mcp_client   # lists tools for each enabled server, or "not configured"
```

### Case lifecycle & network graph

Dispositioning a case now routes its alert out of the **Open** queue: `SUSPICIOUS`
→ **Proposed** (awaiting SAR/STR filing), `NEEDS_MORE_INFO` → **Pending**,
`FALSE_POSITIVE` → **Archived**. The Alert Queue has a bucket bar with live counts;
a legacy DB is backfilled idempotently on startup.

Opening a case draws the account's **network graph** (source mules → collector →
offshore beneficiaries) from `/api/alerts/{id}/detail` — orange arrows are
aggregated fund-flow, dashed links are shared devices. Clicking a transaction row
expands raw fields plus derived typology flags (near-threshold, off-hours,
cross-border, repeat-counterparty). Flags are honest heuristics, not model output.

### Investigation MCP server (agent-facing)

Agent frameworks (Cloudera AI Studio, Claude Code) drive investigations through a
small **MCP server** (`mcp_server/`) that is a thin HTTP client over the
platform's customer-centric API — no DB access of its own. It runs as a `uvx`
stdio process wherever the agent lives; the **API is the hosted CAI Application**
(the existing `aml-platform` app, whose Swagger UI is at `/api/docs`).

Five tools; **only `trigger_investigation` mutates** (the API persists the
analysis to the case) — everything else is read-only. Disposition / labels /
retrain / config are not exposed.

| Tool | API route | |
|------|-----------|--|
| `is_customer_suspicious(customer_id)` | `GET /api/customers/{id}/suspicious` | suspicious if any OPEN/PROPOSED/PENDING alert |
| `list_high_score_transactions(customer_id, limit=20)` | `GET /api/customers/{id}/transactions` | ranked by model score |
| `get_case_status(customer_id)` | `GET /api/customers/{id}/case-status` | never creates a case |
| `get_customer_network_graph(customer_id)` | `GET /api/customers/{id}/network` | `{nodes, edges}` |
| `trigger_investigation(customer_id)` | `POST /api/customers/{id}/investigate` | runs the workflow, persists + returns the analysis (needs an LLM) |

Configure it in Cloudera AI Studio (or any MCP client) — points at the deployed API:

```json
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
```

Browse/​test the API directly at `https://aml-platform.<domain>/api/docs` (Swagger).
`trigger_investigation` needs an LLM configured (CAII/local), same as the app. See
`mcp_server/README.md` for local dev.

## Retraining (agent workflow → Workbench canary)

Retraining is an agent workflow (`02_backend/agents/retraining.py`), same
supervisor/SSE backbone as the investigation flow. A disposition at the ≥500-annotation
threshold — or `POST /api/model/retrain` (fire-and-forget) / `POST /api/model/retrain/stream`
(SSE progress for Dashboard B) — runs a deterministic pipeline:

`PREPARE` (count human tx-labels + annotations) → `TRAIN` → `CANARY` → `PROMOTE` → `NARRATE`.

When a Cloudera AI Workbench is configured (`config.workbench` or
`$CAI_WORKBENCH_HOST/_PROJECT_ID/_API_KEY`), `TRAIN` creates + runs a CML training
job and `CANARY` builds + deploys the model via CML API v2 (`common/workbench.py`,
direct REST — no MCP subprocess); the new deployment is mirrored into the ops
`deployments` table as `CANARY` then flipped to `CHAMPION` (what `ml/scorer.py` and
`/api/model/deployments` read). **Locally (no Workbench) it fails soft**: trains via
`train_model()` and simulates the canary/promote in the `deployments` table.

> Seam: a real CML Job runs `ml/train.py` **on the Workbench**, which must reach the
> ops annotations/`transaction_labels` (same source=Impala / ops=SQLite split the
> blueprint already documents). CML API v2 has no traffic-split canary, so "canary" =
> a fresh deployment promoted to CHAMPION.

## CAI Workbench Setup

Run the five AMP tasks in order from the Workbench UI (or via the CML API):

| # | Task | Script | Resources |
|---|------|--------|-----------|
| 1 | Install Dependencies | `01_installer/install.py` | 2 CPU / 4 GB / 1 GPU |
| 2 | Generate Synthetic Data | `02_backend/data_generation/generate_synthetic_data.py` | 2 CPU / 4 GB |
| 3 | Feature Engineering & Train | `02_backend/data_pipeline/feature_engineering.py` | 2 CPU / 8 GB / 1 GPU |
| 4 | Train Risk Model | `02_backend/model_serving/train.py` | 2 CPU / 8 GB / 1 GPU |
| 5 | **Start AML Platform** | `03_application/start_frontend.py` | 2 CPU / 8 GB |

## Configuration

```bash
cp config/config.yaml.example config/config.yaml
```

Key settings in `config/config.yaml`:

```yaml
llm:
  provider: caii          # caii | vllm | ollama
  caii:
    endpoint: https://<workspace>/namespaces/serving-default/endpoints/<name>/v1
    model: <model-id>
    api_key: ""           # JWT auto-read from /tmp/jwt in CML

data:
  n_transactions: 100000  # scale up for larger demos
  suspicious_rate: 0.04

demo:
  nightfall_case_id: "CASE-NIGHTFALL-001"  # pre-loaded showcase case
```

Secrets go in `.env` (never committed — see `config/.env.example`).

### Source data (Impala/Iceberg ↔ CSV) — forking onto a real warehouse

Reference data (`customers`/`accounts`/`transactions`/`devices`) is read through
`02_backend/common/source.py`, which resolves once per process to either a live
Impala/Iceberg connection or the local CSV fallback in `data/raw/`:

```yaml
source:
  backend: auto            # auto (try Impala, fall back to CSV) | impala | csv
  csv_dir: data/raw
  impala:
    host: <datahub-gateway-host>
    port: 443
    http_path: <datahub>/cdp-proxy-api/impala
    user: <workload-username>
    database: <your_schema>   # every source query runs unqualified against this DB
    auth_mechanism: LDAP
    # password from $IMPALA_PASSWORD or ~/tokens/workload_password — never in yaml
```

To point the app at your own warehouse: set `source.impala.database` to your
schema and confirm connectivity before flipping `backend: impala`:

```bash
python 02_backend/scripts/impala_smoke.py   # tries each candidate http_path, prints the working one
```

`backend: auto` (the default) needs no manual flip — it TCP-preflights Impala on
first use and silently falls back to CSV when unreachable, logging which
backend it picked. `GET /api/health/environment` reports this at runtime
(`source_backend`, `source_ok`) instead of leaving it silent.

**Prod hardening — explicitly deferred (not in this AMP/demo scope):** a
durable/shared ops store (Postgres or similar) in place of local SQLite, a
secrets manager for LLM/CDP credentials (MCP + model API keys are currently
plaintext in the ops DB), probability-calibrated risk scores (today's score is a
within-batch percentile rank, see `ml/scorer.py`), and a full immutable audit
trail. These matter for a production pilot, not for forking the blueprint onto
real data or running the live demo.

**Agentic stretch — designed, not built:** Iceberg history/peer-baseline tools
wired into the Pattern/Network workers (needs a live warehouse), stdio-spawn MCP
transport (the Tools tab supports remote HTTP servers only — CML sandboxes may
block subprocess spawn), and a direct web-search verification path (verification
currently routes through MCP tools only).

## Demo Flow

1. Open `/investigation` → load the **Nightfall** case (`CASE-NIGHTFALL-001`)
2. Click **Investigate** — the agent swarm runs and returns findings + SAR draft
3. Disposition the case (Suspicious / Not Suspicious)
4. The 500th disposition triggers an automatic **retrain** notification on `/modelops`
5. Review the new model's metrics → **Deploy to Canary** (shadow-scores live alerts)
6. Compare canary vs. champion metrics → **Promote** or **Rollback**

## Tech Stack

- **Python 3.11**, FastAPI, Uvicorn
- **React 19**, Vite, Tailwind CSS
- **XGBoost** (risk model), SHAP (explainability)
- **SQLite** (feature store + case DB)
- **Multi-agent**: Supervisor + 4 specialist workers via OpenAI-compatible API
- **LLM**: Cloudera AI Inferencing (CAII) — swap to vLLM or Ollama via config

## Docker

```bash
cp config/.env.example .env
# Set CAII_ENDPOINT and CDP_TOKEN in .env
docker compose up -d --build
open http://localhost:8100
```
