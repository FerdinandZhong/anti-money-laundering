# Embedded MCP Servers + Tools-Tab Parameters — SDD Progress Ledger

Plan: docs/superpowers/plans/2026-09-08-embedded-mcp-tools-tab.md
Branch: feat/tx-labels-and-caii-endpoints
Baseline commit: ab4f843

## Tasks
- [x] Task 1: tool_config.params column + migration
- [x] Task 2: stdio transport + embedded server registry (mcp_client.py)
- [x] Task 3: embedded-config API endpoints (main.py)
- [x] Task 4: source.py 'mcp' backend (iceberg MCP)
- [x] Task 5: workbench.py MCP mode (retraining)
- [x] Task 6: ToolsView redesign (embedded cards + custom registry)
- [x] Task 7: regression + README

## Log
(baseline: ab4f843 — clean tree, 62 backend tests green, frontend build clean)
Task 1: complete (commit c33f2a4, review clean — params TEXT column via self-heal ALTER, 64 tests)
Task 2: complete (commits 12cadab..be8b166, review Approved — 2 Important findings fixed in be8b166: stdio-stack close on partial spawn + race doc; 70 tests. NOTE: reviewer edited tree mid-run, reverted + redone via fix subagent for clean provenance)
Task 3: complete (commit f103310, review Approved — 75 tests. Minor findings deferred to final review: (a) parallel _SECRET_KEYS vs existing _mask_key helper in main.py; (b) str() coercion of param values. "Important" finding re get_connection() in test is a false concern — conftest tmp_db_path patches get_db_path on both common.config and common.db.)
Task 4: complete (commits 88551bf..ec05594, review Approved — 12 impala-branch functions routed via _sql_df, param inlining left-to-right escaped, CSV branches untouched; Important finding fixed in ec05594 (test now asserts inlined SQL); 81 tests)
Task 5: complete (commits 3f44e4a..6eec5c0, review Approved — mode() mcp/rest/local, 4 fns route via _mcp_call, REST paths unchanged, retraining mode!=local; Important finding fixed in 6eec5c0 (_mcp_call raises on unexpected type); 86 tests + retraining self-check OK. Minor deferred: no routing tests for run_job/get_job_run/canary_deploy MCP paths.)
Task 6: complete (commits d2a68f5..a00b2dc, review Needs-fixes→fixed — embedded cards + preserved custom section, build clean; Important finding fixed in a00b2dc (form omits masked secrets) + Minor meta guard. Minor deferred: loading-vs-empty state conflation.)
Task 7: complete (commit d3c3049, README updated + 86 backend tests green + frontend build clean)

ALL 7 TASKS COMPLETE. Plan range: ab4f843..d3c3049. Deferred Minors for final review: (T3a) parallel _SECRET_KEYS vs _mask_key; (T3b) str() param coercion; (T5) no routing tests for run_job/get_job_run/canary MCP; (T6) loading-vs-empty state.
Final whole-branch review (opus): Ready-to-merge-with-fixes. Important #1 (_req guard dead in mcp mode) + Rec #4 (canary_deploy routing test) fixed in ce24223 (87 tests, retraining OK, frontend build clean). Remaining deferred Minors non-blocking: T3a parallel maskers, workbench __main__ cosmetic, T6 loading-vs-empty state, _sql_df %s-literal positional note.
DONE. Plan HEAD: ce24223.

## Post-merge / post-review fixes
- ad77249: committed this SDD ledger (plan complete).
- Runtime bug (user hit 404 + perpetual "Loading…" in Tools tab): root cause = stale backend process (started 11:33, before Task 3 added /api/config/embedded → fast 404) + frontend treating empty list as "loading forever". Restarted backend (endpoint now 200 in ~8ms). Fixed the UX in b52aa0e — Tools tab now tracks loading/error/ready and shows an error+Retry instead of hanging (resolves deferred T6 loading-vs-empty Minor).
- b847e9e: gitignore SQLite WAL sidecar files (data/aml.db-shm, -wal).

## Final state
- Branch feat/tx-labels-and-caii-endpoints @ b847e9e. Tree clean.
- 87 backend tests pass; frontend builds clean; retraining self-check OK.
- This-plan commit range: ab4f843..b847e9e (15 commits).
- PUSH PENDING: repo has NO git remote configured — cannot push / open PR until `git remote add origin <url>` is set. All work committed locally.
- Carry-forward: Workbench MCP tool names resolved at runtime (candidate-match + fail-soft) — confirm via Tools tab Test connection on first live connection.
- Remaining non-blocking Minors: T3a parallel maskers in main.py; T3b str() param coercion; T5 no routing tests for run_job/get_job_run MCP paths; workbench __main__ cosmetic; _sql_df %s-literal positional note.

## CAI Workbench integration (2026-09-08, branch feature/cai_integration)
Git-backed CML deploy, adapted from the sibling `use_case_discovery` repo.
- Remote: added `origin` https://github.com/FerdinandZhong/anti-money-laundering.git (was PUSH PENDING above). Pushed `main` (b54796c) + `feat/tx-labels-and-caii-endpoints` (815e027). Author already qzhong@cloudera.com; push auth via gh (FerdinandZhong, repo owner).
- New `cai_integration/`: setup_project, jobs_config, create_jobs, git_sync, trigger_jobs, launch_app, deploy_application, README. New `.github/workflows/deploy-to-cml.yml`.
- CML Job chain (cascades from the CML Jobs UI): git_sync → install → generate → features → train → **launch**. `launch` is a CML Job (launch_app.py, parent=train) that creates/replaces the Application pointing at 03_frontend/start_frontend.py and waits for running. Jobs mirror .project-metadata.yaml tasks; Python 3.11 runtime (install.py fetches Node via nvm).
- Ported fixes from use_case_discovery latest commits:
  - install.py: `npm install --no-audit --no-fund` (not `npm ci`) — macOS lockfile omits linux optional deps (@emnapi/*). Also fixed frontend_dir `03_application/frontend` → `03_frontend` (build was silently skipped — blocking bug found while porting).
  - deploy_application/launch_app: delete ALL matching Applications then create (CML PATCH rejects create payload; frees app port → EADDRINUSE). find_applications returns every match; pure _build_payload.
  - create_jobs: delete+create jobs (job PATCH rejects `environment` object) + _launch_env bakes launch job env (RUNTIME_IDENTIFIER/APP_SUBDOMAIN/LLM_PROVIDER/BACKEND_PORT/IMPALA_PASSWORD; no ADMIN_TOKEN — app has none).
  - trigger_jobs: `--sync-only` presync + explicit-trigger fallback (AUTO_TRIGGER_WINDOW=120s) if CML doesn't auto-fire a child.
  - start_frontend.py (`6a85c38 "update the address"`): bind 127.0.0.1 on CML (Workbench proxy is loopback; 0.0.0.0 unreachable), 0.0.0.0 locally. `_bind_host()` detects CML via HOME==/home/cdsw OR CDSW_APP_PORT set.
  - workflow: preflight → setup-project → presync → create-jobs (baked env) → run-chain.
- Deliberately NOT ported: use_case_discovery's start_app.py/start-app.sh bash-wrapper + ensure_node.sh — our Application entry is already Python (start_frontend.py) and install.py installs Node via nvm.
- Verified: py_compile all; deploy_application --selfcheck; 6-job chain order + scripts exist; _launch_env vars; _bind_host (local 0.0.0.0 / CML 127.0.0.1). No CML round-trip tested (no live workspace here).
- Commits 815e027..86aab9d on feature/cai_integration. PR #2 → main (open): https://github.com/FerdinandZhong/anti-money-laundering/pull/2
- Carry-forward: on first live CML deploy confirm the launch job creates a reachable app (127.0.0.1 bind, CAII endpoint/model set in config/config.yaml, RUNTIME_IDENTIFIER points at a Python 3.11 runtime).

## Investigation MCP server (2026-09-08, branch feature/cai_integration)
Architecture (final, after redirect): the **API** is the hosted CAI Application; the **MCP server** is a uvx-installable stdio package that runs inside Cloudera AI Studio and calls the API over HTTP. (First cut was an in-process stdio server reaching into SQLite/source directly — discarded: won't work when the MCP process runs in Studio via uvx, separate from the app.)
- Backend `02_backend/api/main.py`: Swagger moved under the proxy — `docs_url=/api/docs`, `openapi_url=/api/openapi.json` (frontend proxy only forwards /api/*). 5 customer-centric routes: GET `/api/customers/{id}/{suspicious,transactions,case-status,network}` (read-only; case-status never creates a case) + POST `/api/customers/{id}/investigate` (non-streaming JSON; THE ONLY MUTATION — persists analysis+analyzed_at). Helpers `_resolve_alert_and_case(create=)` + `_customer_transactions` (score DESC, unscored last). suspicious = any OPEN/PROPOSED/PENDING alert.
- New `mcp_server/` (repo-root, own minimal pyproject: mcp+httpx only, entry `aml-mcp`): `aml_mcp/server.py` FastMCP stdio, thin httpx client over the 5 routes; env `AML_API_BASE_URL` (req) + `AML_API_TOKEN` (opt Bearer). Installed via `uvx --from git+<repo>#subdirectory=mcp_server aml-mcp`. Reuses existing `aml-platform` app's /api (no new CAI app).
- Removed the first-cut artifacts: `02_backend/mcp_server/`, `02_backend/tests/test_mcp_server.py`, `.mcp.json`, `cai_integration/launch_mcp_app.py`.
- Tests: `02_backend/tests/test_customer_endpoints.py` (6, TestClient — suspicious t/f, case-status read-only asserts NO case created, processed+annotations, tx sorted, investigate is-only-writer via stubbed run_investigation, Swagger reachable at /api/docs). `mcp_server/test_server.py` (6, httpx mocked — path/param/method routing, Bearer header, missing-base-url raises). Backend suite 93 green; mcp package 5 tools list OK.
- Docs: README "Investigation MCP server" section rewritten (Studio uvx JSON + Swagger URL); new `mcp_server/README.md`.
