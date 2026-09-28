# AML Investigation Platform — Handoff

_Last updated: 2026-09-02 (session 3)_

> **Session 3 in one line:** designed + built the human-in-the-loop retraining
> fix (transaction-level labels feed the transaction-level model) and CAII
> endpoint auto-discovery. Code is uncommitted on branch
> `feat/tx-labels-and-caii-endpoints` (design spec IS committed there). See
> **Session 3** section below before doing anything.

Turning the AML demo into a reusable **blueprint**: the same app runs on synthetic
data locally and on real Cloudera Impala/Iceberg data in prod, with no code change.
Full plan lives at `.omc/plans/aml-blueprint-hardening.md`.

---

## Architecture (current)

```
Frontend (React 19 + Vite 8 + Tailwind v4)  ── /api/* proxy ──►  FastAPI (02_backend/api/main.py, :7078)
  03_frontend/                                                     │
                                                                   ├─ SOURCE data (read-only): customers, accounts,
                                                                   │    transactions, devices
                                                                   │    → common/source.py : Impala (prod) → CSV fallback
                                                                   │      (NO SQLite for source)
                                                                   └─ OPERATIONAL state (writes): alerts, cases, evidence,
                                                                        annotations, model_runs, deployments
                                                                        → common/db.py : small local SQLite (ops-only)

Batch scoring job  02_backend/ml/scorer.py  (python -m ml.scorer)
  XGBoost.predict_proba per tx → account-level composite → INSERT ALERT-ML-* rows
```

**Key architectural decision (locked with user):** source data and operational
state are split across two stores. Source = Impala/Iceberg in prod, CSV fallback
locally, no SQLite. Operational writes stay in a small SQLite (frequent row
inserts/updates; wrong fit for Iceberg).

---

## How the data actually flows (answers to recurring questions)

**Where do alerts come from?** They are model-generated, not hand-authored.
`ml/scorer.py::score_transactions()` is the batch job: loads the CHAMPION XGBoost
model, scores every transaction (`predict_proba`), aggregates by account, flags
accounts (`max_score > 0.8` OR `>10% of tx above threshold`), dedupes by account,
and inserts one `ALERT-ML-…` row each. Current DB: **148 alerts = 144 `ALERT-ML-*`
+ 1 `ALERT-NIGHTFALL-001` + 3 `ALERT-STR-*`** (last two hand-seeded typologies).

**How is the risk score derived?** transaction → features (`FEATURE_COLS`) →
XGBoost prob → **account-level composite** (model signal + velocity + fund-flow +
shared-device + cross-border), percentile-ranked into the 0.65–0.95 band. Band:
CRITICAL ≥ 0.9, HIGH ≥ 0.7, MEDIUM ≥ 0.5.

**Prod story:** schedule `python -m ml.scorer` as a daily job (CML Job / cron /
Airflow) against the real DB. The app reads the same `alerts` table + assembles
detail on-read; nothing in the API or frontend changes.

---

## Completed work

### WS1 — Data contract + prod seam ✅
- **`GET /api/alerts/{id}/detail`** (`api/main.py`): flat, alert-driven case detail
  assembled from the alert's own customer + transactions; **creates the case on
  first open** so investigate/dispose work for any alert.
- Frontend rewired to alert-driven detail (`api.ts` `getAlertDetail`,
  `CaseWorkbench` keys off `alertId`, `App` passes `alertId`). `DEMO_DETAIL` is now
  a true network-error-only fallback. **Fixes the original "all alerts show the
  same details" bug at the root** (was a nested-vs-flat contract mismatch).
- `ml/scorer.py` made a runnable job + hardened against deploy-pointer/artifact
  drift (train.py records runs but never promotes CHAMPION → scorer falls back to
  the newest artifact).
- README documents the batch-job → prod-swap seam.

### WS1.5 — Data-backend abstraction (Impala/Iceberg ↔ CSV) ✅
- **`common/source.py`** — typed source layer. `backend()` resolves once: `auto`
  does a 6s TCP preflight to Impala, falls back to CSV. Impala path uses impyla
  (`%s` params); CSV path uses pandas. Rows returned JSON-native.
- **`scripts/export_source_csv.py`** — exports source tables → `data/raw/*.csv`
  (ran: 2000 customers, 1888 accounts, 100254 txns, 2454 devices).
- **`scripts/impala_smoke.py`** — self-serve connectivity test (TCP preflight +
  http_path probe + `SELECT 1`).
- `config source:` block (backend/csv_dir/impala{host,port,http_path,user,...};
  password via `$IMPALA_PASSWORD` or `~/tokens/workload_password`, never in yaml).
- Rewired all source reads through the layer: `feature_engineering` (both
  builders), `scorer`, detail endpoint, agent tools, `drift_monitor`. Deleted the
  dead nested `/api/cases/{id}` endpoint. **Audit: zero source-table reads outside
  `source.py`.**

### Pre-WS2 fixes ✅
- **Two-pane scroll**: root `h-screen overflow-hidden` + `min-h-0` on
  AlertQueue/CaseWorkbench so each panel scrolls internally, not the whole page.
- **Risk-score realism**: root-caused the flat 0.86/HIGH to model collapse (near-
  binary per-tx output, `max` aggregation flattens) — features were already
  diverse. Replaced raw-max with a **continuous account composite**, percentile-
  ranked into 0.65–0.95 with deterministic jitter + signal-derived `reason_codes`.
  Result: 141 distinct scores; **CRITICAL 24 / HIGH 96 / MEDIUM 28**. Regression
  guard in `scorer.py` `__main__`.

### UI (earlier this session)
- Migrated to Tailwind v4 + Cloudera-branded light theme aligned to
  `modularized_agent_ui/app/analytics` (accent `#e35b1f`, header `#1c0f43` + orange
  bottom border, tokenized surfaces).

### WS2 — Multi-agent orchestration ✅
Replaced the single-agent ReAct loop + fake streaming with a real supervisor/worker system:

- **`agents/state_machine.py`** — `CaseState` enum + `transition()` guard; fails fast
  on illegal moves. Self-check in `__main__`.
- **`agents/workers.py`** — 4 focused workers in one file (ponytail: no subpackage).
  Each opens its own DB conn, calls its allow-listed tools, saves evidence via
  `common.evidence.create_evidence`, then does **one** LLM call to produce findings.
  Allow-lists: `profile` → alert+customer; `pattern` → tx history+model explanation;
  `network` → graph+device overlap; `screening` → customer profile.
- **`agents/supervisor.py`** — `run_investigation(case_id, alert_id, customer_id, account_id)`
  generator. Dispatches all 4 workers via `ThreadPoolExecutor(max_workers=4)`,
  yields structured events as workers complete, then streams the narrative compose
  via **real** LLM token streaming.
- **`api/main.py`** — `investigate_case` now passes `alert_id, customer_id, account_id`
  to supervisor; emits `data: {json}\n\n` SSE (structured, not raw text). Removed
  `stream: bool` branch — always streams.
- **`AgentPanel.tsx`** — parses JSON SSE events: `phase` → section headers
  (`▸ COLLECTING`), `worker_done` → worker findings block (`✓ profile …`),
  `token` → streaming narrative.

**SSE event contract:**
```
{"type": "phase",       "phase": "COLLECTING"|"ANALYZING"|"REVIEWED"}
{"type": "worker_start","worker": "profile"|"pattern"|"network"|"screening"}
{"type": "worker_done", "worker": str, "findings": str, "evidence_ids": [str]}
{"type": "token",       "text": str}
{"type": "done"}
```

### Bug fixes + UX (session 2)
- **Source layer 500 fix** (`common/source.py`): `_try_impala()` now probes
  `SELECT 1 FROM customers LIMIT 1` after the TCP check. Impala is TCP-reachable but
  tables aren't in `default` DB → now correctly falls back to CSV. **Root cause of
  "all alerts show Nightfall/DEMO data" bug.**
- **LLM provider switcher**: `GET /api/config/llm` returns active provider/model +
  available providers; `POST /api/config/llm` switches in-memory. `llm_client.py`
  has `set_provider()` + `_provider_override`. `AgentPanel` shows a gear badge with
  current model; clicking opens a provider dropdown.
- **Account Risk Score label**: clarified in `CaseWorkbench` — it's a composite
  account-level score, not per-transaction.
- **Suspicious tx sort**: table now sorts `is_suspicious=1` rows to the top (they
  were already red-highlighted; now also appear first).
- **Dispose UX**: renamed "Dispose Case" → "Record Decision"; disposition options are
  radio cards with plain-English descriptions; submit button full-width.

---

## Session 3 — human-in-the-loop retraining + CAII endpoints + diagrams

**Branch:** `feat/tx-labels-and-caii-endpoints`. The design spec is committed
(`docs/superpowers/specs/2026-09-02-tx-labels-and-caii-endpoints-design.md`);
the implementation code is **uncommitted** (working tree) because my changes sit
in files that also carry prior-session uncommitted work, and `git add -p` isn't
available to split them. Decide how to commit (see "Committing" below).

### The design discussion (why these changes exist)

Recurring question: **how does human review actually retrain the model?** We
traced it and found the loop was decorative:
- Model is **transaction-level** (`feature_engineering.build_feature_matrix`
  trains per-tx on the synthetic `is_suspicious` flag).
- Human annotation was **account/case-level** (`annotations.case_id`), and
  `train.py` never read it. Dispositions triggered retraining but never entered it.

We considered two ways to fix the grain mismatch:
1. Make the model account-level (train on the SAR/clear disposition). Rejected —
   needs a new model + feature builder + cold-start bootstrap of a new grain.
2. **Move the human label to the transaction level** (chosen). The model already
   learns per-transaction, so the fix is just: swap the label source. Analyst
   tags individual suspicious transactions in the case workbench; those become
   the training labels.

**Confirmed decisions:**
- Yes, a disposition means "is this account a money mule?" — but for *training*
  the analyst also tags the specific suspicious **transactions**.
- The **AI investigation stays account-level** (LLM narrative on why the account
  is risky). The **business disposition stays account-level** (SAR/clear + retrain
  trigger). Only the **ML training label** moves to the transaction grain.
- Training label = `COALESCE(human_tx_label, synthetic is_suspicious)` — human
  overrides where present; synthetic fills the rest (handles cold start).
- Labeling UX = 3-state per-row control + bulk, **manual only** (no auto-propagation
  from the account disposition — weak labels would poison the training set).

### What was implemented (Feature B — tx labels)
- **`transaction_labels`** ops table (`schema.py`, self-heal in `common/db.py`).
  Table count 11 → 12.
- **`api/main.py`**: detail endpoint now returns `transaction_id` + current `label`
  per row; new `POST /api/cases/{case_id}/transaction-labels` upserts labels
  (`label: null` clears one).
- **`feature_engineering.py`**: `build_feature_matrix` label is now
  `COALESCE(human_tx_label, is_suspicious)` via `_load_human_labels()` (reads ops
  `transaction_labels`) + `_apply_human_labels()`. `train.py` unchanged otherwise.
- **Frontend** (`CaseWorkbench.tsx`, `api.ts`): per-row **S / C** control (3-state,
  click-active-to-unset) beside the Score column, "Mark all suspicious / clean"
  bulk buttons, auto-save per change.

### What was implemented (Feature A — CAII endpoint auto-fill)
- **`common/caii.py`**: `list_caii_endpoints()` calls
  `POST https://$CDSW_DOMAIN/api/v1alpha1/listEndpoints` (bearer from `/tmp/jwt`
  JSON `access_token`/plain, or `CDP_TOKEN`), returns `[{name, base_url, model}]`
  (`base_url` = endpoint url minus `/chat/completions`). Fails soft → `[]` locally.
  Pattern mirrors `CML_AMP_RAG_Studio/llm-service/.../caii`.
- **`common/config.py`**: substitutes `<workspace-domain>` → `$CDSW_DOMAIN` in LLM
  endpoints at load.
- **`api/main.py`**: `GET /api/config/llm/caii-endpoints`; `POST /api/config/llm`
  accepts optional `base_url`+`model` to pin a live endpoint.
- **`agents/llm_client.py`**: `set_endpoint()` + `_endpoint_override` (in-memory).
- **Frontend** (`AgentPanel.tsx`, `api.ts`): gear menu shows a "Live CAII endpoints"
  sub-list; picking one pins base_url+model.

### Smoke test (all passed, 2026-09-02)
schema=12 tables · db self-heal OK · detail carries tx_id+label · label POST
persists + clears · `_load_human_labels` reads them · `build_feature_matrix`
runs end-to-end (100,254 rows) · `/api/config/llm/caii-endpoints` → `200 []`
locally (no 500) · domain-sub unit OK · `npm run build` (tsc strict) OK ·
frontend serves fresh bundle. Smoke-test label rows cleaned up (0 left).

### Self-checks (runnable)
- `cd 02_backend && python -m data_generation.schema`  → "12 tables"
- `cd 02_backend && python -m ml.feature_engineering`   → override self-check
- `cd 02_backend && python -m common.caii`              → skips w/o CDSW_DOMAIN

### Diagrams (fireworks-tech-graph)
`docs/` now has four business/architecture diagrams (svg+png+editable json):
- `architecture-overview.*` (engineers)
- `business-flow-overview.*` (detailed 5-stage ops)
- `business-simple.*` (layman linear)
- `business-two-sector.*` (**Business ↔ IT/MLOps loop** — updated this session to
  show tx-level labels: green = IT hands flagged accounts to Business; blue =
  analyst-labelled transactions retrain the model). Edit spec:
  `docs/aml-two-sector.json`.

### Excalidraw MCP
Registered at **`user` scope** (all projects), connected. (`global` scope doesn't
exist in this CLI — valid: local/user/project/…). **Tools load only after a Claude
Code restart** — after restart, ask to render `docs/aml-two-sector.json` into an
editable Excalidraw canvas.

### Committing (decision needed)
The 10 changed files are listed in the design-spec rollout. My edits are
intermixed with prior uncommitted WS2/source-layer work in 6 shared files
(`main.py`, `feature_engineering.py`, `llm_client.py`, `api.ts`, `AgentPanel.tsx`,
`CaseWorkbench.tsx`). Options discussed: (1) commit my 10 files (pulls prior edits
in shared files too), (2) commit everything as one snapshot, (3) leave uncommitted.
Not yet decided.

### Still open (not built)
- **Retrain still uses `COALESCE`, but the trigger** (`main.py` dispose → ≥500
  annotations → `_bg_retrain`) is unchanged — fine, but note retraining only
  improves once real tx-labels accumulate.
- Frontend `dist/` was rebuilt this session; if you change frontend code, rebuild
  (`npm run build`) before prod-mode relaunch.

---

## Pending / next

### WS3 — Frontend polish (Cloudera brand + DESIGN.md rigor, NEXT)
- Adopt `modularized_agent_ui/DESIGN.md` discipline (systematic type scale + tight
  tracking, borderless surfaces via contrast, one soft shadow, strict radius, 8px
  spacing) while keeping Cloudera identity (indigo header + single orange accent).
- Single-accent + one-radius + one-shadow locks; tokenize ad-hoc font sizes.
- `AgentPanel`: upgrade terminal to structured phase cards + evidence chips using
  WS2's JSON SSE event stream (phase/worker_done/token events already emitted).

### Open follow-ups (not blocking)
- **Impala prod connection** — TCP reaches the gateway but tables aren't in `default`
  DB (now correctly falls back to CSV via the stricter table probe). When running from
  an allow-listed network, confirm the correct `database:` value in
  `config.yaml source.impala` and run `python 02_backend/scripts/impala_smoke.py` to
  verify. The `auto` backend works without it locally.
- **CHAMPION deploy pointer drift** — `train.py` records model_runs but never
  updates the CHAMPION deployment; scorer works around it. Fix `train.py` to
  promote, or add a promote step.
- **Model calibration** — the composite risk score is a within-batch relative
  ranking (demo). A production model would be probability-calibrated.

---

## Decisions log (from discussion)

| Topic | Decision |
|---|---|
| Case detail source | Alert-driven; case created on first open (no cases backfill) |
| Source data store | Impala/Iceberg (prod) → CSV fallback; **no SQLite for source** |
| Operational store | Small local **SQLite** (ops-only: alerts/cases/evidence/annotations/registry) |
| Agent topology | Blueprint §5.1: **1 Supervisor + 4 workers**, hand-rolled over existing `llm_client` (no framework dep) |
| Frontend direction | **Cloudera brand + DESIGN.md rigor** (not full Apple language) |
| iceberg-mcp-server | Agent warehouse tool (WS2), not the app's own data access |

---

## Run / verify

```bash
# Bootstrap (first run): generate data, train, export CSVs, score
python 02_backend/data_generation/generate_synthetic_data.py
python 02_backend/ml/train.py                 # (path may be ml/train.py)
python 02_backend/scripts/export_source_csv.py
cd 02_backend && python -m ml.scorer          # idempotent; prints score spread

# Run app
python start_app.py                            # frontend :8100 → backend :7078
# backend only (dev): cd 02_backend && uvicorn api.main:app --port 7078

# Impala connectivity (from an allow-listed network)
python 02_backend/scripts/impala_smoke.py

# Self-checks
cd 02_backend && python -m common.source       # CSV backend self-check
cd 02_backend && python -m ml.scorer           # score-spread regression guard
```

Note: `start_app.py` launches its own backend on :7078 — kill any stray
`uvicorn` on that port first (`lsof -ti:7078 | xargs kill -9`).

---

## Key files

| Path | Role |
|---|---|
| `02_backend/api/main.py` | FastAPI routes; `/api/alerts/{id}/detail` (WS1) |
| `02_backend/common/source.py` | Source layer: Impala ↔ CSV (WS1.5) |
| `02_backend/common/db.py` | Ops SQLite connection |
| `02_backend/ml/scorer.py` | Batch scoring job + account composite risk |
| `02_backend/ml/feature_engineering.py` | `FEATURE_COLS`, feature builders (via source) |
| `02_backend/ml/drift_monitor.py` | PSI drift (via source) |
| `02_backend/agents/supervisor.py` | WS2 orchestrator — 4 workers in parallel, yields SSE events |
| `02_backend/agents/workers.py` | 4 worker functions (profile/pattern/network/screening) |
| `02_backend/agents/state_machine.py` | CaseState enum + transition guard |
| `02_backend/agents/{investigator,tools,llm_client}.py` | investigator kept; tools + llm_client used by WS2 |
| `02_backend/scripts/{export_source_csv,impala_smoke}.py` | Bootstrap + connectivity |
| `03_frontend/src/{App,api}.tsx/ts` | Shell + API client |
| `03_frontend/src/components/{AlertQueue,CaseWorkbench,AgentPanel,ModelDashboard,Badge}.tsx` | UI |
| `config/config.yaml` | `source:` (Impala/CSV) + ops db + model + llm |
| `.omc/plans/aml-blueprint-hardening.md` | Full plan + changelog |

## KYC continuation — 2026-09-26

Latest update: AMP `.project-metadata.yaml` now defaults to `AML_PREPARE_KYC=1`,
`AML_ENABLE_KYC_DEMO_CONTROLS=1` and `AML_KYC_DOCUMENT_MODE=pdf`. Installer adds
`requirements-kyc-runtime.txt` and initializes the packaged OCR models as a preflight.
Without a supplied manifest, pipeline generates five control PDFs (two scanned)
plus 120 linked corpus PDFs, runs real OCR and builds LanceDB; local output is
`artifacts/kyc_poc/amp_documents/` and `artifacts/kyc_poc/amp_corpus/`.
It excludes unrelated extraction POC artifacts. Explicit markdown mode remains
available, and embeddings remain optional. Preparation variables now reach the
separate CML install job as well as generation. Fresh-project generation,
OCR, index and control evaluation passed in the OCR environment; the current
full backend suite is 142 passed, one skipped.
No actual CML deployment or Linux runtime validation was performed.

Further continuation: linked corpus customer IDs `CUST-000296`–`CUST-000307`
and 30 deterministic account IDs now appear in generation, the 120-document PDF
corpus, and generated eight-table semantic source. Default AMP expanded-corpus
flag is `AML_KYC_EXPANDED_CORPUS=1`. Local combined release with 127 documents
is `kyc-ba41967fd7d110b8c7ff`; hybrid release is
`kyc-3bcfd88a84784154f434`. Semantic runtime source has 32 accounts and
234 assertion metadata rows. Local publication validates typed Parquet and
generates retry-safe `INSERT OVERWRITE`/`validate.sql`/activation settings for
eight Iceberg tables. Five document-evidence DEMO control families per SG/HK
context execute through exact bilingual term mappings. Analyst review events
are scoped, idempotent, hash-linked and separate from computed results; actor IDs
remain self-declared. Regulatory source candidates are recorded in
`semantic/regulatory_source_register.yaml` and are non-executable. Frozen linked
benchmark v2: 144/144 positives and 24/24 exclusions; frozen paraphrase
challenge: keyword 36/60, hybrid 60/60. See
`docs/kyc_audit_and_multimodal_demo.md` and `docs/kyc_audit_concept_linkage.md`.

Final linked-data extension: the 30 accounts also receive ownership roots/edges,
natural/legal parties and complete demo activity profiles/transactions. Local
eight-table publication now has row counts 32/234/54/94/32/32/34/1 in the
order accounts/assertions/parties/edges/roots/profiles/transactions/FX.
`KYC_CORPUS` evaluates seven controls per jurisdiction; a full main account
can pass seven, a synthetic outflow anomaly reports GAP, and a secondary
account correctly reports missing mandate/funding evidence. The browser smoke
check passed retention, replay, analyst review and JSON export on a temporary
ops DB copy. Reviewer identity remains self-declared; official clauses remain
candidate-only; remote Impala and CML Linux execution were not performed.

Security/regulatory continuation: private CML Applications are now the default.
Review writes derive Workbench `RW` identity from `REMOTE-USER` and a signed
loopback proxy assertion; public CML deployments disable review writes.
Assessment/review rows and a review head use HMAC seals when a separately
provisioned key is present; private mode requires a 32+ character key via
`AML_KYC_AUDIT_HMAC_KEY_FILE`. MAS Notice 626's 30 June 2025 edition and
selected clauses were verified from MAS; HKMA AML-2 clause 4.4.1 was checked.
Both remain non-executable `SOURCE_REVIEW_ONLY` links. Full backend suite:
142 passed, one skipped; frontend build, deploy selfcheck and local browser
retention/replay/review/export pass. Institution approval and external
WORM/retention policy are still outstanding. See
`docs/kyc_regulatory_review_packet.md`.

- Profile worker now evaluates and retains deterministic demo controls using alert-derived scope/cutoff. Results become investigation evidence; the same summary is appended outside the LLM to findings and the final streamed narrative. Missing inputs/disabled controls/retention failure are explicit unavailable results.
- `prepare_kyc_pipeline.py` is enabled by the AMP template via `AML_PREPARE_KYC=1`. It consumes `AML_KYC_MANIFEST` or generates PDF/OCR evidence and optional hybrid embeddings. CML registration and launch forward relevant environment values. Local preparation tested; no CML API calls made.
- `prepare_kyc_corpus.py` builds 12 linked groups/30 operational accounts with 120 PDF versions (108 native, 12 real OCR scans). The eight-table semantic source includes these identities, ownership paths and activity.
- Current frozen benchmarks are `data/kyc_benchmark/queries_v2.json` and `queries_challenge_v1.json`; runner `benchmark_kyc_retrieval.py`. The linked suite passes 144/144 positives and 24/24 exclusions. On the paraphrase challenge, keyword passes 36/60 and hybrid 60/60 Recall@5.
- Active audit release remains `kyc-6aa2ce87ede353d2bd0f`; expanded hybrid release `kyc-b466ad7410c80cbd6aef` is isolated under the corpus directory. Local pipeline proof uses another isolated index.
- Validation: 139 backend tests pass, one skipped; frontend production build and browser review/export smoke pass; `git diff --check` clean. Remote Impala execution remains user-deferred.
- Next: verify actual CML/Linux execution and remote Impala parity when available; institutionally approve regulatory applicability/interpretations and provision protected audit-key/retention infrastructure. See `docs/kyc_audit_and_multimodal_demo.md`.


## Local acceptance and origin release — 2026-09-27

User verified the new features locally and authorized a push with AMP updates.
Release branch: `feature/semantic-demo-explorer` (no merge to main requested).
Semantic context now uses Context / Lineage / Query / Original Ossie files,
neutral interactive concept cards, separate regulatory meaning and applicability
conditions, and accurate onboarding-profile provenance. Review/retention actions
remain backend APIs, not controls in the semantic UI. Missing indexed documents
fall back to existing Markdown or a clearly labeled customer-profile view.

The AMP template and `cai_integration/jobs_config.yaml` both default to PDF/OCR,
expanded corpus preparation and the matching runtime semantic paths. Job
registration forwards `GIT_SYNC_BRANCH` and the audit-key file setting; set the
sync branch to this release and re-register existing jobs before running them.
Generated indexes, publication outputs, credentials and unrelated decks are not
part of the feature commit. Remote CML/AMP and Impala runs remain user-deferred.

Release validation: an isolated export of the staged files passes 144 backend
tests (one OCR dependency skip) after the normal source-data generation step.
The skipped real PDF/OCR bootstrap passes separately in the OCR environment;
all 10 MCP tests pass with the locked dependencies. Frontend production build,
deployment self-check and staged whitespace checks pass.

## Semantic investigation stages A/B — 2026-09-27

Added a retained alert-scoped investigation context, uncapped event-time source
retrieval, currency-separated Decimal metrics, dated device observations and
recorded alert model signals. Regulatory Ossie concepts now drive bilingual KYC
searches against one pinned release; configured controls preserve conflicts and
missing evidence. Workers return deterministic observations with separately
labelled, ID-bound AI interpretations. Retained JSON evidence and structured
reports support clickable inputs and saved finding cards. Both investigation
entry points now select the actual alert account.

No AMP variables/jobs/dependencies added. Frontend rebuild + application restart
required. Browser acceptance uses a temporary DB and stubbed LLM; it does not
establish live-model quality. See `docs/semantic_investigation.md` for contracts,
limitations and remaining stage C (bounded adaptive follow-up/model evaluation).

Validation: 161 backend tests passed, one existing optional OCR test skipped;
production frontend build passed. Isolated real-API browser acceptance passed
live findings, owner-conflict evidence links, retained-payload integrity, saved
report reload and browser-error checks (LLM stubbed). The local app was restarted
on port 8100 with the existing full_integration knowledge/semantic directories;
health and the new latest-report endpoint return 200. Current launcher session:
71813. On 2026-09-28, the user authorized committing and pushing these changes
to `origin/feature/semantic-demo-explorer`.
