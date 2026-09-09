# Project Overview

## What it does
The **AML Investigation Platform** turns a nightly, ML-ranked alert queue into
agent-assisted anti-money-laundering investigations, and retrains its risk model
from every analyst decision — all inside one Cloudera AI application, on your own
data, with no egress.

## Who it's for
- **AML investigators / analysts** — work the alert queue, review the transaction
  graph and agent findings, file a SAR draft, and disposition cases (Dashboard A).
- **Data scientists / model-risk managers** — watch model performance and drift,
  retrain, canary-deploy, and promote or roll back (Dashboard B).
- **External agent frameworks** (Cloudera AI Agent Studio, Claude Code) — drive
  investigations through the MCP server over the customer-centric API.

## The two dashboards
| Dashboard | Route | Audience |
|-----------|-------|----------|
| A — Investigation | `/investigation` | analysts |
| B — Model Ops / MRM | `/modelops` | data scientists, MRM |

## Core loop
Nightly batch scoring (champion XGBoost) → risk-ranked **Alert Queue** → analyst
opens a case → **agent swarm** (Supervisor + Graph / Pattern / Regulatory /
Narrative + MCP Verification) produces findings + a **SAR draft** → **disposition**
→ human labels feed **retraining** → canary → promote/rollback → new champion scores
the next queue.

## Why it's a blueprint, not just a demo
The same app runs on synthetic data locally and on real **Impala/Iceberg** data in
prod. Forking onto a real warehouse is a config change (`source.impala.database` +
prod DB path) — no API or frontend change. See [architecture.md](architecture.md).

## Tech stack
Python 3.11 · FastAPI · React 19 + Vite + Tailwind · XGBoost + SHAP · SQLite (ops
store) · Impala/Iceberg (source) · LLM via Cloudera AI Inferencing (CAII), swappable
to vLLM/Ollama · MCP (stdio) for agent access.
