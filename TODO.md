# TODO

Current tasks, priorities, and known issues. Newest first.

## In progress / next
- [ ] **Land the CAI-integration fixes on `main`** — all fixes are on
      `feature/cai_integration` (tip: pipeline restructure + docs). Cherry-pick / merge
      when approved. CML currently syncs the feature branch.
- [ ] **Decide single-path scoring** — scoring now lives in the dedicated **Score**
      job. The retraining `SCORE` step and the app startup self-heal remain as guarded
      safety nets (no-op once the queue is populated). Strip them for a single explicit
      path, or keep for resilience? (owner decision)

## Known issues
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
