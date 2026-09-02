# Design — Transaction-level labels + CAII endpoint auto-fill

_Date: 2026-09-02 · Branch: `feat/tx-labels-and-caii-endpoints`_

Two independent features that both close gaps between the running app and its
"foundation logic" (the two-sector Business ↔ MLOps loop).

---

## Feature A — Auto-fill the LLM endpoint from live CAII endpoints

### Problem
`config.yaml.example` ships the CAII endpoint as a placeholder:
`https://<workspace-domain>/namespaces/serving-default/endpoints/<endpoint-name>/v1`.
On CML the operator must hand-edit this before the agent works. We want it
resolved automatically after the app starts, and the provider dropdown in
`AgentPanel` populated with the workspace's **real** CAII inference endpoints.

### Reference (grounded in `CML_AMP_RAG_Studio/llm-service/app/services/caii/caii.py`)
- List: `POST https://{CDSW_DOMAIN}/api/v1alpha1/listEndpoints` with body
  `{"namespace": "serving-default"}` and `Authorization: Bearer <jwt>`.
  Returns `{"endpoints": [{"name": ..., "url": ..., ...}]}`.
- Each entry's `url` is the full chat-completions URL; the OpenAI **base_url**
  is `url.removesuffix("/chat/completions")` (RAG Studio `caii.py:350`).
- Auth token: JWT at `/tmp/jwt` (already read by our `llm_client.py:31-35`),
  falling back to `CDP_TOKEN` env.
- Domain: `CDSW_DOMAIN` env var.

### Design
New module `02_backend/common/caii.py`:
- `list_caii_endpoints() -> list[dict]` — POSTs `listEndpoints`, returns
  `[{"name", "base_url", "model"}]`. `base_url` = entry `url` minus
  `/chat/completions`; `model` from the entry (or `describeEndpoint` if the list
  entry lacks a model name). Returns `[]` on any failure (no domain, no token,
  network error) so local dev is unaffected.
- `caii_domain()` — `os.environ.get("CDSW_DOMAIN")`.

New backend route in `api/main.py`:
- `GET /api/config/llm/caii-endpoints` → `{"endpoints": [{name, base_url, model}]}`.
  Thin wrapper over `list_caii_endpoints()`.

Extend the existing `GET /api/config/llm`:
- When provider is `caii` and live endpoints are discoverable, include them so
  the UI can show real choices alongside the static `available_providers`.

Frontend `AgentPanel.tsx`:
- The gear dropdown already lists providers. Add a **CAII endpoint sub-list**:
  when `caii` is selected, fetch `/api/config/llm/caii-endpoints` and render each
  as a pickable row. Selecting one calls a new
  `POST /api/config/llm` variant that sets the active CAII `base_url` + `model`
  in-memory (extends `_provider_override` to also carry an endpoint override).

`llm_client.py`:
- `_make_client()` — when an endpoint override is set (from the UI selection),
  use it; else fall back to config yaml. Also substitute `<workspace-domain>`
  → `CDSW_DOMAIN` in any configured endpoint string at load time (cheap safety
  net for the yaml path).

### Scope / non-goals
- No persistence of the selected endpoint (in-memory, resets on restart — matches
  the existing provider-override behaviour).
- No new dependency; uses `requests` (already available) or `httpx`.

### Verify
- Local (no `CDSW_DOMAIN`): endpoint list returns `[]`, dropdown shows only the
  static providers, nothing breaks.
- Self-check in `common/caii.py __main__`: if `CDSW_DOMAIN` set, prints endpoint
  count; else prints "no CDSW_DOMAIN — skipped".

---

## Feature B — Transaction-level labels feed the (transaction-level) model

### Problem
The model is already transaction-level (`feature_engineering.build_feature_matrix`
trains per-transaction on the synthetic `is_suspicious` flag). But human
annotation is account/case-level (`annotations.case_id`), and `train.py` never
reads it. The human signal triggers retraining (`main.py:215-218`) but never
enters it — the "decisions become labels" loop is decorative.

### Decision (confirmed with user)
Move the **training label** to the transaction grain — matching the model. Keep:
- **AI investigation** account-level (LLM narrative on *why the account is risky*)
  — unchanged.
- **Business disposition** account/case-level (SAR / close + retrain trigger)
  — unchanged.
- **ML label** transaction-level — NEW, from analyst per-row tagging.

Confirmed sub-decisions:
1. Keep the account disposition AND add tx labels (different purposes). ✓
2. Training label = `COALESCE(human_tx_label, synthetic is_suspicious)`. ✓
3. Labeling UX = 3-state per-row control + bulk, manual only (no auto-propagation
   from the account disposition — weak labels would poison the training set). ✓

### Data
New ops table (`data_generation/schema.py` + self-heal in `common/db.py`):
```sql
CREATE TABLE IF NOT EXISTS transaction_labels (
    transaction_id TEXT PRIMARY KEY,
    label INTEGER NOT NULL,          -- 1 = suspicious, 0 = clean
    case_id TEXT REFERENCES cases(case_id),
    labeled_by TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```
`annotations` unchanged. Bump `TABLE_NAMES` (11 → 12) and the schema self-check.

### Backend (`api/main.py`)
- Detail endpoint (`get_alert_detail`): include `transaction_id` in each returned
  transaction dict (currently omitted) so the UI can key labels; also join the
  existing human label so the control shows current state.
- `POST /api/cases/{case_id}/transaction-labels` — body
  `{"labels": [{"transaction_id", "label"}], "labeled_by"}`; upsert
  `INSERT OR REPLACE` into `transaction_labels`. `label ∈ {0,1}`; a `null`/absent
  label deletes the row (un-set).

### Frontend (`CaseWorkbench.tsx`, `api.ts`)
- Add `transaction_id` and `label` to the `Transaction` interface.
- New column in the transaction table: a 3-state control per row
  **— / Suspicious / Clean** (default `—`). Sits alongside the existing Score
  column.
- Bulk actions above the table: "Flag all shown" / "Clear all shown".
- Save: debounced or on explicit "Save labels" → POST to the new endpoint.
  (Decision for the plan: auto-save per change vs explicit save button — lean
  auto-save per change, simplest and matches a review flow.)

### ML (`ml/feature_engineering.py`, `ml/train.py`)
- `build_feature_matrix`: change the label to
  `COALESCE(human_tx_label, is_suspicious)`. Load `transaction_labels` (via
  `common.db`, ops store) keyed by `transaction_id`; `is_suspicious` (source
  layer) fills the rest. Everything else — `FEATURE_COLS`, split, XGBoost — is
  unchanged.
- `train.py` unchanged beyond the label source; retrain trigger unchanged.
- Guard: `__main__` self-check asserts that when human labels exist they appear
  in the training label vector (i.e. COALESCE actually overrides).

### Scope / non-goals
- No change to the scorer's account-level aggregation or the alert grain.
- No change to the agent/LLM report.
- Cold start handled implicitly by COALESCE: synthetic labels train the model
  until human tx-labels accumulate; humans override where present.

### Verify
- `python -m ml.feature_engineering` (add a small `__main__`): prints
  `#rows, #human-overrides` and asserts overrides are reflected.
- Manual: label a few rows in the UI → confirm rows persist in
  `transaction_labels` → run `python -m ml.train` → dataset positives count
  reflects the overrides.
- Existing scorer regression guard still passes.

---

## Rollout order
1. Feature B data + backend + ML (self-contained, testable via CLI).
2. Feature B frontend (per-row control + bulk + save).
3. Feature A backend (`common/caii.py` + routes).
4. Feature A frontend (endpoint sub-list in the gear dropdown).

Each step ends with its own runnable check before moving on.
