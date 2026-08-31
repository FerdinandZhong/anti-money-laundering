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
python 02_backend/data_pipeline/feature_engineering.py
python 02_backend/model_serving/train.py

# 4. Run
python start_app.py
# → http://localhost:8100/investigation
# → http://localhost:8100/modelops
```

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
