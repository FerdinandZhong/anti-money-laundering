# TODO

Current tasks, priorities, and known issues. Newest first.

## Release preparation — 2026-09-27
- [x] User verified the new features in the local application.
- [x] Four-section semantic UI with neutral meaning cards; removed review/retention controls from the main UI.
- [x] Independent regulation semantic model and endpoint, visible without account document evidence.
- [x] Onboarding-profile labels and Markdown fallback for accounts without indexed documents.
- [x] Align AMP and registered CML job defaults; forward selected Git sync branch.
- [ ] Expand indexed documents to the rest of the active alert queue (current release covers one of 20 open alerts).
- Remote AMP/Impala verification remains deferred; this release does not claim either ran.

## KYC continuation — 2026-09-26
- [x] AMP enables PDF/OCR preparation and demo controls by default; installer provisions the CPU OCR runtime. Fresh-project real-OCR test passes; current full backend suite: 142 passed, one skipped.
- [x] Profile worker retains deterministic, cutoff-scoped control assessments and cites them in findings/final narrative.
- [x] Optional knowledge preparation in the existing generation job; CML environment forwarding tested locally.
- [x] Link 12 generated customers/30 accounts/120 document versions to AMP source IDs and semantic CSVs, including 12 real OCR scans.
- [x] Frozen 40-query retrieval benchmark; first hybrid run passes 36 retrieval and four exclusion checks.
- [x] Eight-table CSV/Impala read adapter, typed local publication, retry-safe isolated SQL and validation/activation handoff.
- [x] Seven linked-account DEMO controls per SG/HK context: five PDF evidence concepts, ownership paths and 30-day activity; hash-linked analyst review events.
- [x] Frozen linked 168-query and 60-paraphrase benchmarks; hybrid clears the challenge, keyword exposes a 60% Recall@5 gap.
- [x] Extend ownership and activity rows to all 30 accounts; shared FX fixture remains available for the original cross-currency case.
- [x] Bind private-CML review writes to signed Workbench `RW` identity; HMAC-seal snapshots and review chain with an independent key; block public-CML review writes.
- [x] Verify current MAS Notice 626 and HKMA AML-2 edition/clause locations; retain candidate-only regulatory links and a clause review packet.
- [x] Fail closed if an executable control pack is reclassified or loses its `DEMO-` control IDs.
- [ ] Institutionally approve regulatory applicability/interpretation; provision protected audit key and external retention/legal-hold controls.
- [ ] Verify actual CML deployment (user-deferred).
- [ ] Remote Impala validation remains user-deferred; local publication scripts are available.

Details: [current KYC guide](docs/kyc_audit_and_multimodal_demo.md).

## Semantic demonstration enhancement (Phase 1.5)
- [x] Foldable exact-source YAML viewer for the Ossie-style model and AML extensions, distinct from runtime output.
- [x] Dedicated Semantic context tab with live, read-only intent/query previews.
- [x] Two query presets: KYC comparison and score explanation; API intent exclusion remains tested.
- [x] Show definitions, source lineage, account/time scope, interpretation limits and declared relationships.
- [x] Expose missing fact coverage and retrieval limits without implying full ontology execution.
- [x] Remove misleading source-of-wealth synonym for expected turnover; add API regression tests.
- [x] EN/ZH presenter walkthrough: `docs/semantic-demo-walkthrough.md`.
- [ ] Later: compare persisted worker input snapshots with generated findings, and validate claim compliance.
- [ ] Later: complete declared account/transaction/evidence/case fact providers and replace capped flow retrieval with complete source-side aggregation.

## In progress / next
- [ ] **Part 1 — immediate demo improvement**
  - [ ] **1A · Credible chronology + synthetic story**
    - [x] Make `Corp_0294` the deterministic structuring anchor.
    - [x] Generate normal history → early behavioural change → 3-day alert pattern.
    - [x] Persist data cutoff, monitoring window, pattern start, latest contributing
          transaction, and scoring-run time on every new alert.
    - [x] Align scoring eligibility to the stated monitoring window; do not claim a
          historical threshold crossing unless it is persisted.
    - [x] Rebuild a clean reproducible dataset/model/queue and refresh EN/ZH talk tracks.
  - [ ] **1B · Polished Investigation workspace**
    - [x] Add Overview / Transactions / Network / Findings navigation.
    - [x] Add Why this alert?, Why now?, expected-vs-observed, and monitoring timeline.
    - [x] Rename the account metric to **Account Priority Score** and expected turnover
          explicitly; remove synthetic truth from analyst row styling/sorting.
    - [x] Replace `S` / `C` controls with labelled actions and surface save state.
    - [x] Use the dedicated Network tab as a full investigation canvas with a
          relationship legend, instead of a compact/collapsible chart.
    - [x] Persist and show the weighted account-evidence inputs, daily queue
          percentile, and priority mapping for every newly scored alert.
    - [x] Recover and show the verifiable queue-rank arithmetic for older local
          alerts whose original weighted signal values were never stored.
    - [x] Derive observed flow and network links from account endpoints, rather
          than the transaction direction label alone.
    - [ ] Replace global model feature importance in AI findings with per-alert
          stored score evidence; reserve TreeSHAP for Part 2.
    - [ ] Browser-review the regenerated Corp_0294 journey at demo resolution.
  - [ ] **1C · Lightweight KYC context**
    - [x] Add a Documents tab and local source-of-wealth retrieval worker without
          expanding into the production-grade knowledge base planned for Part 2.
  - [x] **1.5 · Governed AML semantic layer and MCP discovery**
    - [x] Add an Ossie-aligned, versioned YAML semantic model, AML ontology, and
          investigation-context registry under `semantic/`.
    - [x] Add a bounded resolver over existing source/ops APIs: concept and metric
          definitions, declared relationship paths, time-scoped case context, and
          intent-allow-listed fact retrieval—never arbitrary SQL.
    - [x] Expose read-only `/api/semantic/*` routes and six corresponding `aml-mcp`
          tools for Agent Studio discovery and governed case retrieval.
    - [x] Supply the same exact-alert semantic context to internal profile, pattern,
          network, and screening workers; persist it as investigation evidence.
    - [x] Show the model version, data cutoff, supplied facts, sources, evidence
          count, and a claim limitation in the AI Findings “Analysis basis” panel.
- [ ] **Part 2 — later pilot implementation**
  - [ ] Stateful bounded plan → collect → critique → verify loop with targeted re-entry.
  - [ ] Governed customer knowledge base with versioned, page-level citations.
  - [ ] Approved-source external verification and counterparty identity resolution.
  - [ ] Incremental event-time detection, watermarks, threshold-crossing history,
        suppression/reopen policy, and SLA measurement.
  - [ ] Replace batch-relative presentation scoring with calibrated customer-level
        mule probability (temporal split, calibration/ECE monitoring, analyst-capacity
        threshold) and TreeSHAP top-feature attribution.
  - [ ] Use the OCBC-style five-domain feature catalogue across transaction patterns,
        account demographics, network/graph, temporal behaviour, and device/channel;
        assess proxy-discrimination and feature fairness explicitly.
  - [ ] Constrain LLM narratives to cited attribution/evidence fields in a fixed schema;
        add analyst fidelity rating and periodic review rather than treating LLM output
        as an independent basis for adverse action.
  - [ ] Track live analyst yield rate, queue volume, and short-term monitoring outcomes
        alongside offline PR-AUC/recall, using confirmed dispositions as feedback labels.
  - [ ] Candidate/champion evaluation gates, real canary period, verified rollback,
        and pilot outcome evaluation.
  - [ ] Defer authentication/authorization and platform-wide tracing to the following phase.
- [ ] **Land the CAI-integration fixes on `main`** — all fixes are on
      `feature/cai_integration` (tip: pipeline restructure + docs). Cherry-pick / merge
      when approved. CML currently syncs the feature branch.
- [ ] **Decide single-path scoring** — scoring now lives in the dedicated **Score**
      job. The retraining `SCORE` step and the app startup self-heal remain as guarded
      safety nets (no-op once the queue is populated). Strip them for a single explicit
      path, or keep for resilience? (owner decision)

## Known issues
- [ ] **Frontend lint baseline** — `ToolsView.tsx` has five pre-existing
      `react-hooks/rules-of-hooks` errors. The Part 1 investigation files pass
      scoped `oxlint`; fix ToolsView separately so the repository-wide lint gate is green.
- [ ] **CAII LLM broken** — `/api/health/environment` → `active_model … AttributeError:
      'str' object has no attribute 'choices'`. Investigation, verification and NARRATE
      fall back to canned output until a reachable CAII endpoint + valid model are
      configured in the Models/Tools tab. Root-cause the client/health path. *(Stale
      locally as of 12 Sep 2026: the active-model health probe succeeds; retain this
      only until the deployed environment is retested.)*
- [ ] **Data quality** — `data.suspicious_rate` in config is **dead** (never used);
      positives come only from injected typologies (~119), so the positive rate falls as
      transactions grow and PR-AUC stays ~0.6. The composite floor-fallback keeps the
      queue full regardless. Optional: make `suspicious_rate` real so positives scale
      with `n_transactions` for a stronger model / PR-AUC trend.
- [ ] **Generate accumulates** — re-running `generate` appends transactions (new random
      ids). Wipe `data/aml.db` + `data/raw/` for a clean 100k baseline.

## Done (this CAI-integration pass)
- [x] Guard `__file__` in CML job-entry scripts (kernel has no `__file__`).
- [x] `config.yaml` → `config.yaml.example` fallback for fresh checkouts.
- [x] `generate` exports source CSVs so `feature`/`train`/`score` find `data/raw/*.csv`.
- [x] Scorer composite floor-fallback → queue never silently empty on a weak model.
- [x] Dedicated **Score** job between Train and Launch (`ml/run_scoring.py`).
- [x] Launch job **keep-alive** (`APP_KEEP_RUNNING`) + `trigger_jobs` tolerates it.
- [x] Retraining workflow scores after promote (`SCORE` phase).
- [x] Backend self-heals an empty queue on startup (guarded).
- [x] LLM client 20s timeout → no NARRATE / investigation hang.
- [x] Executive deck on the v5 Cloudera template (`docs/aml-overview.pptx`).
- [x] Project docs organized per the Vibe-Coding guideline (AGENTS.md + docs/).
- [x] Smoke test `02_backend/scripts/smoke_test.py` — ALL GREEN.
