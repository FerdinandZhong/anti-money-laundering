# Development

## Local setup & run
```bash
python 01_installer/install.py                              # deps + Node + frontend build
cp config/config.yaml.example config/config.yaml            # optional; example is the fallback
# first run: build data + model + queue
python 02_backend/data_generation/generate_synthetic_data.py   # writes aml.db + data/raw/*.csv
cd 02_backend && python -m ml.train && python -m ml.run_scoring && cd ..
python start_app.py                                          # → http://127.0.0.1:8100
```
`generate` now exports the source CSVs at the end, so `data/raw/*.csv` always exists.
For a clean dataset, `rm -rf data/aml.db data/raw` before regenerating (generate
appends across runs).

## Config
`config/config.yaml` (git-ignored) or, if absent, `config/config.yaml.example`.
Keys: `llm.provider` (caii|vllm|ollama), `model.decision_threshold`, `source.backend`
(auto|impala|csv), `data.db_path`. Secrets go in `.env` (never committed).

## CML deploy
```bash
export CML_HOST=... CML_API_KEY=... GIT_URL=... RUNTIME_IDENTIFIER=<py3.11 runtime>
python cai_integration/setup_project.py                      # → /tmp/project_id.txt
PID=$(cat /tmp/project_id.txt)
python cai_integration/create_jobs.py  --project-id "$PID"   # register the chain
python cai_integration/trigger_jobs.py --project-id "$PID"   # run it (or run Git Repository Sync in the UI)
```
Chain: `git_sync → install → generate → features → train → score → launch`.

> **Adding/renaming a job requires re-running `create_jobs.py`** — editing
> `jobs_config.yaml` alone does not register it in CML.

### Launch job behaviour
`launch_app.py` is **keep-alive**: after the app reaches `running` it holds the job in
the running state so the chain ends in a live dashboard. Env knobs:
- `APP_KEEP_RUNNING` (default `1`) — set `0` to exit as soon as the app is running (CI).
- `APP_MONITOR_INTERVAL` (default `60`) — heartbeat poll seconds.
- `APP_PUBLIC` (default `1`) — public app; `0` requires Workbench SSO.
- `BACKEND_PORT` (default `7078`).

## Smoke test (run before deploying)
```bash
python 02_backend/scripts/smoke_test.py     # exit 0 = all green
```
Covers, against a temp copy of `data/aml.db` (never mutates real data): config fallback,
LLM client timeout, scoring fills the queue + dedup, weak-model composite fallback, and
the `train→score→launch` chain wiring.

## Regression checklist
- [ ] `python 02_backend/scripts/smoke_test.py` → ALL GREEN
- [ ] `python start_app.py` → `http://127.0.0.1:8100/investigation` shows alerts
- [ ] `/api/alerts/counts` non-zero; `/api/model/score-histogram` populated
- [ ] `/api/health/environment` → expected `source_backend`
- [ ] Any new job script guards `__file__` and appears in `jobs_config.yaml` **and**
      `.project-metadata.yaml`

## CML gotchas
- The installer resolves base and enabled KYC requirements in one pip invocation.
  NumPy is pinned to the OCR runtime version, and pandas/scikit-learn/XGBoost
  minimums exclude versions without NumPy 2 support. A fresh subprocess imports
  the data/ML stack, round-trips an Arrow table and fits tiny sklearn/XGBoost models;
  PDF/OCR mode also validates OpenCV and initializes the bundled OCR models.
- `__file__` is undefined in the CML kernel — guard `PROJECT_ROOT`.
- `config.yaml` is git-ignored — the example is the fallback.
- Alerts require the **score** step; a champion alone does not create alerts.
- LLM/Impala/Workbench absent → must fail soft (LLM client has a 20s timeout).

### Recovering an AMP pandas/NumPy ABI failure after generation

`ValueError: numpy.dtype size changed ... Expected 96 ... got 88` during pandas
import indicates incompatible compiled packages. Earlier installation could keep
an existing pandas 2.1 binary, then upgrade NumPy to 2.2.6 for OCR. The corrected
installer requires pandas >=2.2.3,<3 and resolves all enabled requirements together.
See [NumPy's ABI troubleshooting](https://numpy.org/doc/stable/user/troubleshooting-importerror.html)
and [pandas NumPy 2 support](https://pandas.pydata.org/docs/whatsnew/v2.2.2.html).

After syncing the fix, rerun **Install Dependencies** (AMP step 1), with the same
KYC environment settings. It must finish with the runtime-ready check. End the
failed generation session and start a fresh one so cached native modules cannot
survive the package change. If the log already reports all rows generated and
fails only at CSV export, finish step 2 with these commands from the project root:

```bash
python 02_backend/scripts/export_source_csv.py
# For the default multimodal AMP configuration:
python 02_backend/scripts/prepare_kyc_pipeline.py
```

Then continue from **Feature Engineering and Train** (AMP step 3), followed by
training, scoring and launch. Do not rerun the full generator to recover an export
failure: it can append another batch of transactions. Export uses Python's CSV
writer, streams rows without pandas and atomically replaces each output file.
`Alerts: 0, Cases: 0` is expected before scoring and is unrelated to this error.
