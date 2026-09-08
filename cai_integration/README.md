# Deploying to Cloudera AI (CML) Workbench

Runs the **AML Investigation Platform** on CML: a Job chain builds the app and
trains the model, then a CML **Application** serves the React UI + FastAPI backend
as one app. Same `cai_integration/` automation pattern as the sibling
`use_case_discovery` repo, adapted to this Python project.

**Flow:** create the project from git → CML Job chain
`git_sync → install → generate → features → train` (pre-installs deps, builds the
frontend, generates data, trains the model on project storage) → launch the
Application (`03_frontend/start_frontend.py` on `$CDSW_APP_PORT`, starting in
seconds because the build + model already exist).

These jobs mirror the `tasks` in the root `.project-metadata.yaml` (the AMP catalog
file); this directory just drives them via the CML API for git-backed / CI deploys.

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

python cai_integration/setup_project.py                     # → /tmp/project_id.txt
PID=$(cat /tmp/project_id.txt)
python cai_integration/create_jobs.py  --project-id "$PID"  # register the 5-job chain
python cai_integration/trigger_jobs.py --project-id "$PID"  # run git_sync; CML runs the rest
# after "Train Risk Model" succeeds:
python cai_integration/deploy_application.py \
  --host "$CML_HOST" --api-key "$CML_API_KEY" --project-id "$PID" \
  --runtime-identifier "$RUNTIME_IDENTIFIER" --subdomain aml-platform
```

Re-running `deploy_application.py` **restarts** the existing Application
(idempotent), so it also picks up a fresh build / newly-trained model.
`trigger_jobs.py` waits through the whole chain and fails if any job fails.
`deploy_application.py` **waits for `running`** (`--wait-timeout`, `--no-wait` to
skip) and prints the URL (also `/tmp/app_url.txt` for CI), so a green run means a
reachable app. `create_jobs.py` **fails fast** if `RUNTIME_IDENTIFIER` is unset.

### What each file does
| File | Role |
|---|---|
| `setup_project.py` | Find/create the CML project from `GIT_URL`; wait for clone; write `/tmp/project_id.txt`. |
| `jobs_config.yaml` | The Job chain: `git_sync → install → generate → features → train`. |
| `create_jobs.py` | Create/update the Jobs from the yaml; resolves parent→UUID; runtime from `$RUNTIME_IDENTIFIER`. |
| `trigger_jobs.py` | Trigger `git_sync`; wait through each auto-triggered job to `train`. |
| `git_sync.py` | Job: `git fetch && git reset --hard origin/<branch>`. |
| `deploy_application.py` | Create (or restart) the Application via CML API v2. Run externally / from a CML Session. |

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
