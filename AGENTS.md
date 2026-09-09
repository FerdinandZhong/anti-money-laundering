# AGENTS.md — start here

AI-facing entry point for this repo. Read this first, then jump to the doc you need.

## What this is
**AML Investigation Platform** — a Cloudera AI (CAI) application for anti-money-laundering:
a nightly ML-ranked alert queue, a multi-agent investigation workbench, and a governed
retrain/canary/rollback loop. One FastAPI backend + React frontend, deployed as a single
CML Application. Runs on synthetic data locally and on real Impala/Iceberg data in prod
with no code change.

## Repo map
| Path | What |
|------|------|
| `01_installer/install.py` | Installs Python deps + Node/npm, builds the frontend |
| `02_backend/api/main.py` | FastAPI app (`:7078`); all `/api/*` routes |
| `02_backend/agents/` | Supervisor + workers, retraining workflow, LLM client |
| `02_backend/ml/` | `train.py`, `scorer.py`, `run_scoring.py`, `feature_engineering.py` |
| `02_backend/common/` | `config.py`, `db.py`, `source.py` (Impala↔CSV) |
| `02_backend/data_generation/` | synthetic data generator |
| `03_frontend/` | React 19 + Vite + Tailwind; `start_frontend.py` serves prod + proxies `/api` |
| `cai_integration/` | CML job chain + Application deploy automation |
| `mcp_server/` | `aml-mcp` — stdio MCP server over the customer-centric API |
| `config/` | `config.yaml` (git-ignored) + `config.yaml.example` (shipped default) |
| `data/`, `models/` | SQLite ops DB + source CSVs; model artifacts (persisted in project storage) |

## Run it locally
```bash
python start_app.py          # → http://127.0.0.1:8100  (/investigation, /modelops)
```
First run needs data + model: `generate_synthetic_data.py` → `ml/train.py` → `ml/run_scoring.py`.
See [docs/development.md](docs/development.md).

## Non-obvious things that WILL bite you
- **Alerts come only from the scorer** (`ml/scorer.py`). `gen_alerts()` returns `[]`. If the
  dashboard is empty, scoring hasn't run — not a data problem.
- **CML runs job scripts in a Jupyter kernel where `__file__` is undefined.** Every job-entry
  script guards `PROJECT_ROOT` with `try/except NameError → os.getcwd()`. Do the same for any
  new job script.
- **Source vs ops split**: reference tables (customers/accounts/transactions/devices) come from
  `common/source.py` (Impala, or `data/raw/*.csv` fallback). Ops tables (alerts/cases/…) live in
  the SQLite `data/aml.db`. Generate writes both; `export_source_csv` bridges SQLite→CSV.
- **`config.yaml` is git-ignored** — `get_config()` falls back to `config.yaml.example` so a fresh
  CML checkout runs.
- **Fail-soft is the rule**: no LLM / no Impala / no Workbench must degrade gracefully, never crash.
- **App binds `127.0.0.1:8100` on CML** (the Workbench proxy is loopback); `0.0.0.0` locally.

## Before you touch the pipeline
CML chain: `git_sync → install → generate → features → train → score → launch`.
Adding/renaming a job means **re-running `create_jobs.py`** to register it in CML.

## The docs
- [docs/project-overview.md](docs/project-overview.md) — what & why
- [docs/architecture.md](docs/architecture.md) — components, data flow, job chain
- [docs/development.md](docs/development.md) — setup, run, deploy, smoke test, gotchas
- [docs/user-guide.md](docs/user-guide.md) — how to use the two dashboards
- [docs/component-api.md](docs/component-api.md) — API routes + MCP tools
- [docs/DESIGN.md](docs/DESIGN.md) — brand/visual rules (deck + UI)
- [TODO.md](TODO.md) — current tasks & known issues
- `README.md` — user-facing quickstart · `HANDOFF.md` — session history
