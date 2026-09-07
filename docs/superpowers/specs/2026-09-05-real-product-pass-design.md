# Real-product pass — demo cleanup, labelled-tx metric, manual retrain, fewer alerts, live workflow graph

_Design spec · 2026-09-05_

## Context
Testing the demo surfaced several "demo-isms" that break the illusion of a real product,
plus one blocking bug (already fixed). The app should behave like a shipped AML tool: a
batch job flags a small daily queue of accounts, analysts open them, an agentic investigation
runs (now visualized live as a pipeline), analysts tag suspicious transactions, and retraining
is an explicit operator action. This spec covers six changes.

**Already fixed (context, not scope):** `llm_client` hard-coded `max_tokens`, which newer
OpenAI models (gpt-5.x/o-series) reject in favor of `max_completion_tokens` → 500 on investigate.
Fixed with a one-time compatibility shim (`_completion()` flips `max_tokens`↔`max_completion_tokens`
and drops `temperature` if the model restricts it). Verified against gpt-5.1.

## Confirmed decisions
- Alert volume: **~15–25** per batch run (from 148).
- "Labelled transactions" metric = **model-flagged (`is_suspicious=1`) + analyst-tagged (`transaction_labels`)**.
- Retrain trigger: **manual only** (button / endpoint); drop the ≥500-annotation auto-trigger.
- Daily-batch: **narration only** (README talking point), no code.
- Workflow viz: port the **`modularized_agent_ui` `WorkflowGraph.tsx`** SVG-DAG pattern, recolored to the Cloudera light theme, derived from our existing SSE events.

## Changes

### 1. Simplify demo logic → real product
- **`03_frontend/src/App.tsx`**: remove `DEFAULT_ALERT = NIGHTFALL`. On load, fetch the queue and auto-select the **first (highest-risk)** alert; empty queue → "No open alerts" state. Removes the "1 case on landing, refresh reveals the rest" artifact.
- **`CaseWorkbench.tsx` / `ModelDashboard.tsx`**: drop the fake fallbacks (`DEMO_DETAIL`, `DEMO_RUNS`, `DEMO_DRIFT`, `DEMO_DEP`) in favor of honest empty/error states (no silent fake data). Case-created-on-first-open stays (real workflow).
- **`data_generation/generate_synthetic_data.py`** + **`config/config.yaml(.example)`**: remove the hand-seeded `ALERT-NIGHTFALL-001` / `CASE-NIGHTFALL-001` rows and the `demo:` block (`label_count_preset`, `nightfall_case_id`, `auto_replay`). Keep the mule/structuring **typology transactions** (they surface as normal scored alerts).

### 2. Retraining card = "Labelled transactions"
- **`api/main.py`**: add labelled counts to `/api/stats` (or `/api/model/*`): `model_labelled = COUNT(transactions WHERE is_suspicious=1)`, `human_labelled = COUNT(transaction_labels)`, `labelled_total = model_labelled + human_labelled`.
- **`ModelDashboard.tsx`** + **`api.ts`**: replace the `499/500` card + progress bar with **Labelled transactions = labelled_total**, subtitle `model N · analyst M`. Remove `annotations_to_retrain` usage from the card.

### 3. Retrain trigger = manual only
- **`api/main.py`**: remove the `total_annotations >= 500 → _bg_retrain` block in `dispose_case`. Disposition still writes the annotation + closes the case. Retraining stays available via `POST /api/model/retrain` and `/api/model/retrain/stream` (the Run retraining button). `annotations_to_retrain` can be dropped from `/api/stats`.

### 4. Reduce alerts to ~15–25
- **`data_generation/generate_synthetic_data.py`**: reduce injected suspicious accounts (fewer typology/hard-negative accounts) and/or lower `data.suspicious_rate`.
- **`ml/scorer.py`**: tighten the account-flag rule (currently `max_score>0.8` OR `>10% tx above threshold`) so a batch yields ~20 accounts with a clean band spread (a few CRITICAL, some HIGH, a few MEDIUM). Keep the account dedupe + the `__main__` score-spread guard (update its expected range).
- Deterministic (seed=42) → reproducible. Update README counts.

### 5. Live WorkflowGraph pipeline viz (both workflows)
- **New `03_frontend/src/components/WorkflowGraph.tsx`** — hand-built SVG horizontal DAG adapted from `modularized_agent_ui/components/workflow/WorkflowGraph.tsx`:
  - left→right rounded-rect nodes + arrow edges; header "N/M done" + pulsing branch icon while running.
  - status → Cloudera light theme: `pending` surface-2/ink-faint · `running` accent + pulsing outline · `completed` aml-green · `abstained/skip` ink-faint · `error` aml-red. Node shows label, `1 LLM call`, status dot, tool chips below.
- **Derived from existing SSE state — no new backend contract:**
  - Investigation (`AgentPanel`): nodes `Profile · Pattern · Network · Screening · Narrate`; status from `worker_start`→running / `worker_done`→completed (error if findings start `Error:`); `Narrate` running during token stream, completed on `done`. Tool chips from the `WORKER_TOOLS` allow-list.
  - Retraining (`ModelDashboard`): nodes `PREPARE · TRAIN · CANARY · PROMOTE · NARRATE`; status folded from `phase` + `step` events (`ok`→completed, `skip`→abstained, `error`→error).
- **Placement:** render at the top of `PipelineStream.tsx` (both panels get it above the step cards), live as the run streams.

### 6. Daily-batch narration (docs only)
- **`README.md`**: a short talking point — "`python -m ml.scorer` runs as a daily CML Job; each run scores that day's transactions and inserts new `ALERT-ML-*` rows the analysts pick up the next morning." No code.

## Verification
1. Regenerate → train → score → **~15–25 alerts** with a spread across bands; scorer `__main__` guard passes.
2. Fresh landing (no refresh) auto-selects the top alert; **no Nightfall**; empty-state renders if queue empty.
3. ModelOps card shows **Labelled transactions** (`model N · analyst M`), not 499/500.
4. Recording a decision closes the case and does **not** trigger retraining; **Run retraining** still streams and promotes.
5. Running either workflow shows the **live WorkflowGraph** DAG: nodes light up running→completed, tool chips + LLM counts, "N/M done"; error nodes go red.
6. `npm run build` (tsc strict) clean; investigate + retrain run end-to-end on gpt-5.1.

## Risks / ceilings
- Fewer alerts must still include the seeded typologies so demos have rich cases — verify at least 1–2 CRITICAL land.
- Removing DEMO_* fallbacks means a backend-down state shows an error, not fake data (intended; document the empty states).
- WorkflowGraph is derived client-side from events; if an event is missed the node stays `pending` — acceptable (cosmetic), the step cards remain the source of truth.
