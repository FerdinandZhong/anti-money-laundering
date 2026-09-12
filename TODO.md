# TODO

Current tasks, priorities, and known issues. Newest first.

## In progress / next
- [ ] **Part 1 — immediate demo improvement**
  - [ ] **1A · Credible chronology + synthetic story**
    - [x] Make `Corp_0294` the deterministic structuring anchor.
    - [x] Generate normal history → early behavioural change → 3-day alert pattern.
    - [x] Persist data cutoff, monitoring window, pattern start, latest contributing
          transaction, and scoring-run time on every new alert.
    - [ ] Regenerate the clean demo dataset/model/queue and refresh EN/ZH talk tracks.
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
    - [ ] Browser-review the regenerated Corp_0294 journey at demo resolution.
  - [ ] **1C · Lightweight KYC context**
    - [ ] Add a Documents tab and local source-of-wealth retrieval worker without
          expanding into the production-grade knowledge base planned for Part 2.
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
      configured in the Models/Tools tab. Root-cause the client/health path.
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
