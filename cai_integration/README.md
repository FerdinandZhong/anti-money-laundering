# Deploying to Cloudera AI (CML) Workbench

Runs the **AML Investigation Platform** on CML: a Job chain builds the app and
trains the model, then a CML **Application** serves the React UI + FastAPI backend
as one app. Same `cai_integration/` automation pattern as the sibling
`use_case_discovery` repo, adapted to this Python project.

**Flow:** create the project from git → **CML Job chain**
`git_sync → install → generate → features → train → launch`: the first five jobs
pre-install deps, build the frontend, generate data and train the model on project
storage; **`launch`** (Launch Application) then creates/replaces the CML Application
(pointing at `03_frontend/start_frontend.py`, frontend + backend on `$CDSW_APP_PORT`)
and waits for it to run. Because the launch is itself a CML Job, an end user can **run
the whole chain from the CML Jobs UI** — run "Git Repository Sync" and it cascades to
a live Application, no external script needed.

The build+train jobs mirror the `tasks` in the root `.project-metadata.yaml` (the AMP
catalog file); this directory drives them (plus `launch`) via the CML API for
git-backed / CI deploys.

## Prerequisite: a Python 3.11 ML Runtime
All jobs and the Application run on a **standard Python 3.11 ML Runtime** — the
`install` job fetches Node/npm itself (via nvm) to build the frontend. Copy the
runtime **identifier** from the CML **Runtime Catalog** (Workbench → Runtime
Catalog) and pass it as `RUNTIME_IDENTIFIER`. Everything keys off that identifier.

## One-command bootstrap (git-backed)
From any machine with Python + `requests` + `pyyaml` (local or CI):

```bash
export CML_HOST=https://ml-xxxx.cloudera.site
export CML_API_KEY=<API v2 key>                  # User Settings → API Keys
export GIT_URL=https://github.com/<org>/<repo>   # or GITHUB_REPOSITORY=org/repo
export PROJECT_NAME="AML Investigation Platform"
export RUNTIME_IDENTIFIER=<your-python-3.11-runtime>

export APP_SUBDOMAIN=aml-platform                          # optional (default aml-platform)

python cai_integration/setup_project.py                     # → /tmp/project_id.txt
PID=$(cat /tmp/project_id.txt)
python cai_integration/create_jobs.py  --project-id "$PID"  # register git_sync → … → train → launch
python cai_integration/trigger_jobs.py --project-id "$PID"  # run the chain; the launch job starts the app
```

`create_jobs.py` bakes the app config (`RUNTIME_IDENTIFIER`, `APP_SUBDOMAIN`,
`LLM_PROVIDER`, `BACKEND_PORT`, `IMPALA_PASSWORD`) into the **Launch Application**
job's environment, so `trigger_jobs.py` running the chain produces a live app — and
so does running the chain from the CML Jobs UI. Re-running the chain **replaces** the
Application with the current config (delete-all + create, which also frees the app
port). `create_jobs.py` **fails fast** if `RUNTIME_IDENTIFIER` is unset.

You can also launch/replace the Application directly (outside the chain, e.g. from a
CML Session where `CDSW_*` are injected): `python cai_integration/deploy_application.py
--subdomain aml-platform` — it waits for `running` and writes the URL to `/tmp/app_url.txt`.

### What each file does
| File | Role |
|---|---|
| `setup_project.py` | Find/create the CML project from `GIT_URL`; wait for clone; write `/tmp/project_id.txt`. |
| `jobs_config.yaml` | The Job chain: `git_sync → install → generate → features → train → launch`. |
| `create_jobs.py` | Create the Jobs from the yaml (delete+create); resolves parent→UUID; injects the launch job's app-config env. |
| `trigger_jobs.py` | Run the chain: trigger `git_sync`, then wait-or-explicitly-trigger each child through `launch`. Also `--sync-only`. |
| `git_sync.py` | Job: `git fetch && git reset --hard origin/<branch>`. |
| `launch_app.py` | Job (**Launch Application**, parent=train): create/replace the CML Application + wait for running. |
| `deploy_application.py` | Shared CML-API helpers + a standalone CLI to create/replace the Application (used by `launch_app.py`; also runnable manually). |

## LLM / CAII configuration
The app reads `config/config.yaml`. The `<workspace-domain>` placeholder in the
CAII endpoint is substituted from CML's `CDSW_DOMAIN` at runtime, so **no LLM
endpoint is passed by these scripts** — just set the CAII **endpoint name** and
**model id** in `config/config.yaml`. In CML the CAII JWT is read from `/tmp/jwt`
automatically. Switch provider with `LLM_PROVIDER` (`caii` | `vllm` | `ollama`).

## Source data (Impala/Iceberg)
The backend reads reference bank data from Impala/Iceberg and falls back to local
CSV when unreachable (`source.backend: auto` in `config/config.yaml`). For live
reads, set `IMPALA_PASSWORD` in the Application environment (it is passed through
by `deploy_application.py` if present) or provide `~/tokens/workload_password`.

## Security first (investigation data)
Keep **`bypass_authentication = False`** (the default) so the app sits behind
Workbench SSO — only authenticated Workbench users reach it. `--public` flips it
(not recommended). Data (SQLite `data/aml.db`, models) persists in project storage.

## Option B — deploy via the CML UI (no scripts)
Run the Jobs from `.project-metadata.yaml` (or create them from `jobs_config.yaml`),
then Project → **Applications → New Application**:
- **Script:** `03_frontend/start_frontend.py`
- **Runtime:** your Python 3.11 runtime
- **Subdomain:** `aml-platform` · **Resources:** 2 vCPU / 8 GB
- **Environment:** `BACKEND_PORT=7078`, optionally `LLM_PROVIDER=caii`
- Leave **Enable Unauthenticated Access** OFF.

## GitHub Actions (CI/CD)
`.github/workflows/deploy-to-cml.yml` runs the whole chain on push to `main` (or
manual dispatch). Required repo secrets: `CML_HOST`, `CML_API_KEY`,
`RUNTIME_IDENTIFIER`. Optional: `GH_PAT` (clone a private repo), `IMPALA_PASSWORD`.
