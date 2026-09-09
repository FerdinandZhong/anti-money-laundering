# User Guide

Open `http://127.0.0.1:8100` (local) or the CML Application URL.

## Dashboard A — Investigation (`/investigation`)
For AML analysts working the daily queue.

1. **Alert queue** — risk-ranked `ALERT-ML-*` accounts, bucketed OPEN / PROPOSED /
   PENDING / ARCHIVED with live counts. Sort by risk score / newest / oldest.
2. **Open a case** — click an alert to see the account's **network graph** (source
   mules → collector → offshore beneficiaries; orange = aggregated fund flow, dashed =
   shared device) and its transactions. Expand a transaction row for raw fields +
   derived typology flags (near-threshold, off-hours, cross-border, repeat-counterparty).
3. **Investigate** — runs the agent swarm; returns findings, verification verdicts
   (confirmed / refuted / unverified, with sources), and a **SAR draft**.
4. **Disposition** — routes the alert out of OPEN:
   - Suspicious → **Proposed** (awaiting SAR/STR filing)
   - Needs more info → **Pending**
   - False positive → **Archived**
   Dispositions become training labels for the next retrain.

## Dashboard B — Model Ops / MRM (`/modelops`)
For data scientists and model-risk managers.

- **Model performance** — champion version, PR-AUC, Recall@2%, labelled-transaction
  counts.
- **Drift monitor** — Population Stability Index per feature (Compute on demand).
- **Risk-score distribution** and **PR-AUC across versions**.
- **Alert band breakdown** — open alerts by risk band.
- **Run retraining** — streams `PREPARE → TRAIN → CANARY → PROMOTE → SCORE → NARRATE`.
  After it completes, the champion is promoted, the queue is re-scored, and Dashboard A
  refreshes with new alerts.

## Demo flow
1. `/investigation` → work an alert → **Investigate** → review findings + SAR draft.
2. Disposition it.
3. `/modelops` → **Run retraining** → watch the pipeline; the new champion re-scores and
   the queue repopulates.

## If the queue is empty
Alerts are produced by scoring. Run the **Score Transactions** job (or **Run
retraining**, or relaunch the app — it self-scores an empty queue on startup). See
[development.md](development.md).
