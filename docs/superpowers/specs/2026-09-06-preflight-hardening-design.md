# Pre-flight hardening — make the blueprint forkable-on-real-data AND demo-credible

_Design spec · 2026-09-06_

## Context
Objective (confirmed): this is **both** a customer-forkable Cloudera AMP (others clone it and
run on THEIR Impala/Iceberg data) **and** a live sales/exec demo (a compelling agentic
investigation + human-in-the-loop retraining story on synthetic data). Before adding new
features (Iceberg-MCP, web-search verification — `.omc/plans/2026-09-04-…`), four gaps must be
closed. Production-pilot concerns (durable multi-replica ops store, secrets manager, probability
calibration, full audit) are **explicitly deferred** and documented as future "prod hardening,"
because the near-term objective is AMP + demo, not a production deployment.

Evidence these are real (observed this session): Impala was `unreachable → CSV fallback` on every
run (prod path never carried a real row); `train.py` records runs but never promotes, so champion
pointer drifts and `get_model_explanation` often loads a missing `v1.0.0` artifact and returns an
error the Pattern worker narrates over; PR-AUC printed an unchanging `0.656` across retrains (no
demonstrable lift); every regression (SQLite threading, `max_tokens` shim + race, proxy SSE 500,
`api.open.com` typo) was caught by hand — no tests; ~4 sessions are uncommitted.

## Scope — 4 workstreams (H1–H4). Deferred items listed at the end.

### H1 · Impala/Iceberg path real-runnable (config-only "no code change")
- `02_backend/common/source.py` + `config/config.yaml(.example)`: remove the hardcoded reliance on
  `database: default`; make schema/table names configurable (`source.impala.database` already
  exists — ensure ALL reads honor it and there are no `default`-qualified or unqualified table
  refs that assume the demo DB). Confirm every source read (`get_customer`, `get_accounts`,
  `account_transactions`, `customer_transactions`, `device_fingerprints`, `accounts_by_fingerprints`,
  `count_suspicious`, `count_transactions`) parameterizes the schema.
- Surface `02_backend/scripts/impala_smoke.py` as a callable connectivity check used by H2.
- Acceptance: with valid creds + `backend: impala`, a real `SELECT 1 FROM <db>.customers` succeeds
  and one real customer row flows to the detail endpoint; with no creds it falls back to CSV and
  says so. (Cannot be verified against a live warehouse from the dev box — deliverable is the
  correct config surface + self-test + honest fallback; verified via the smoke script's structure
  and a mocked/needs-network note.)

### H2 · First-run environment health
- New `GET /api/health/environment` (`api/main.py`): returns `{source_backend: "impala"|"csv",
  source_ok: bool, active_model: {alias, reachable: bool, message}, champion_artifact_present: bool}`.
  Reuses `source` backend resolution, `llm_client.probe()` on the active `llm_models` row, and a
  models-dir check for the champion artifact.
- Frontend: a compact **Environment** strip (header status dots already exist — wire them to this
  endpoint) or a small panel on ModelOps. Turns today's silent fallbacks (CSV-when-you-expected-
  Impala, unreachable model, missing champion file) into explicit, actionable status.
- Acceptance: endpoint returns correct booleans locally (source_backend csv, active model reachable
  after Test, champion present); UI reflects them.

### H3 · Real champion promotion + demonstrable retrain lift + honest model explanation
- **Promotion:** `ml/train.py` (or the retrain workflow) promotes the freshly trained version to a
  real `deployments` CHAMPION row **and** guarantees the artifact file exists for that version.
  Remove the "scorer falls back to newest artifact" crutch as the primary path (keep as safety).
- **Model explanation:** `agents/tools.py::get_model_explanation` must resolve a champion whose
  artifact exists (use the promoted version); on genuine absence, return an explicit
  "no explanation available" the worker prompt is told to respect — never fabricate.
- **Demonstrable lift:** seed the demo so retraining shows a visible before/after delta — e.g. seed
  a small set of human tx-labels (or corrupt a slice of synthetic labels that analyst labels then
  correct) so a retrain moves a headline metric. ModelOps "PR-AUC across versions" (already built)
  then shows a real trend. Fix the champion/PR-AUC card mismatch (it currently shows the seed run's
  0.847 regardless of the active champion).
- Acceptance: run retrain → new CHAMPION has an on-disk artifact → `get_model_explanation` returns
  real feature importances → the versions chart shows a non-flat metric line.

### H4 · Minimal smoke-test net + commit history
- `02_backend/tests/` (pytest, no framework beyond pytest): cover the seams that actually broke —
  db self-heal/`check_same_thread`, `source` CSV-fallback + `count_*`, `/api/stats` shape,
  `llm_client` token-param shim (max_tokens→max_completion_tokens, deterministic under threads),
  scorer alert-count/spread guard, and the SSE event contract shape from `run_investigation`
  (mocked `chat`). Keep them fast + offline (mock the LLM).
- Commit the ~4 uncommitted sessions into logical commits (source-layer/ops fixes, retraining
  workflow, WS3 UI, real-product pass, these hardening changes) on the current branch.
- Acceptance: `pytest 02_backend/tests -q` green; `git log` shows coherent atomic commits; working
  tree clean.

## Deferred (production-pilot — NOT in this pass)
Durable/shared ops store (Postgres/managed) instead of local SQLite · secrets manager for LLM/CDP
keys · probability-calibrated risk score · full immutable audit trail · multi-replica concerns.
Documented in README as "Prod hardening (beyond the AMP/demo scope)."

## Recommended sequence
H4 (commit + net first, so nothing regresses) → H2 (cheap, de-risks forks) → H1 (prod parity) →
H3 (demo lift). Each is independently shippable and independently verifiable.

## Verification (end-to-end)
`pytest 02_backend/tests -q` green · `GET /api/health/environment` correct locally · retrain →
champion artifact present + versions chart non-flat + model-explanation real · README documents the
Impala config steps + the deferred prod items · `git status` clean.
