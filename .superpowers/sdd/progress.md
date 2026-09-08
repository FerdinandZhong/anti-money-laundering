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
