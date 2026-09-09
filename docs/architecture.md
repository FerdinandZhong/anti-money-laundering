# Architecture & Data Flow

## Runtime shape
```
React frontend (Vite build)  ──/api/* reverse-proxy──►  FastAPI backend
   served by 03_frontend/start_frontend.py                02_backend/api/main.py
   on $CDSW_APP_PORT (8100)                                on 127.0.0.1:7078
        └─ one CML Application; backend is co-located, never public
```
Both processes run inside a single CML Application, so there is no cross-app
JWT/networking. On CML the app binds `127.0.0.1` (the Workbench proxy is loopback);
locally it binds `0.0.0.0:8100` (still reachable at `127.0.0.1:8100`).

## Source vs Ops (the key split)
- **Source / reference data** (`customers`, `accounts`, `transactions`, `devices`) is
  read through `common/source.py`, which resolves once per process to **Impala/Iceberg**
  or, when unreachable, the **CSV fallback** in `data/raw/`. `GET /api/health/environment`
  reports which backend is live.
- **Ops data** (`alerts`, `cases`, `evidence`, `annotations`, `transaction_scores`,
  `transaction_labels`, model registry) lives in the SQLite **`data/aml.db`** via
  `common/db.py`.
- `generate_synthetic_data.py` writes both, then calls `export_source_csv` to bridge the
  source tables SQLite→CSV so `source.py`'s CSV backend can read them off-warehouse.

## Alert pipeline (where alerts come from)
`gen_alerts()` seeds **nothing** — the queue is produced entirely by `ml/scorer.py`:
1. `build_scored_df` computes features on the fly from the source layer.
2. The champion model scores every transaction (`transaction_scores`).
3. Scores are aggregated per account into a **composite** (model + velocity + fund-flow +
   shared-device + cross-border).
4. The top `TARGET_ALERTS` (20) accounts become `ALERT-ML-*` rows (status `OPEN`),
   deduped by account (already-OPEN accounts are excluded).
5. **Floor fallback**: if no transaction crosses the 0.5 decision threshold (weak model /
   rare positives), ranking falls back to composite over *all* accounts so the queue is
   never silently empty.

## Agent layer (investigation)
Supervisor orchestrates 4 workers over local tools (single LLM call each):
`GraphAnalyst` (network/entity), `PatternDetector` (layering/structuring/smurfing),
`Regulatory` (FATF/FinCEN red flags), `Narrative` (SAR draft). A 5th **Verification**
worker runs a bounded MCP tool-calling loop to confirm/refute claims. Everything
fails soft: no LLM or no MCP → the workflow degrades, never errors.

## Retraining (Dashboard B "Run retraining")
`agents/retraining.py` streams: `PREPARE → TRAIN → CANARY → PROMOTE → SCORE → NARRATE`.
Local mode trains via `train_model()` and simulates canary/promote in the `deployments`
table; with a Workbench configured, TRAIN/CANARY use CML API v2. **SCORE** runs the
scorer so the queue refreshes after promotion. NARRATE is one LLM call (fails soft).

## CML job chain (deploy)
```
git_sync → install → generate → features → train → score → launch
```
Defined in `cai_integration/jobs_config.yaml` (mirrors `.project-metadata.yaml`).
`create_jobs.py` builds the jobs and resolves the parent chain; run "Git Repository
Sync" and CML cascades to a live app. **Launch is keep-alive**: after the app reaches
`running` it holds the job in the running state (`APP_KEEP_RUNNING=1`) rather than
marking the chain finished, so the pipeline visibly ends in a live, ready dashboard.

## External integration (MCP)
`mcp_server/` (`aml-mcp`) is a thin stdio HTTP client over the customer-centric API —
5 tools, only `trigger_investigation` mutates. Any MCP client (Cloudera AI Agent
Studio, Claude Code) points at the deployed API. See [component-api.md](component-api.md).

## CML execution note
Job scripts run in a Jupyter kernel where `__file__` is undefined and `sys.exit` is a
failure. Job-entry scripts therefore guard `PROJECT_ROOT` (`try/except NameError`) and
call `main()` unguarded / raise on error.
