# AML Platform Walking Skeleton — SDD Progress Ledger

## Tasks
- [ ] Task 1: Infrastructure scaffold (manifest, config, requirements, Dockerfile, docker-compose, installer, start_app, README)
- [ ] Task 2: Backend common layer (db, config, evidence helpers; data_generation schema)
- [ ] Task 3: Synthetic data generator + Nightfall typology
- [ ] Task 4: Data pipeline + ML serving + scoring stream
- [ ] Task 5: Agent layer (state machine, supervisor, workers, tools, permissions, llm_client)
- [ ] Task 6: API layer (routers, api.py, start_backend.py)
- [ ] Task 7: Frontend (start_frontend.py + React app with /investigation + /modelops)

## Log
Task 1: complete (commits 17742ea..a9839b5, review clean)
Task 2: complete (commits a9839b5..0173ca1, review clean)
Task 3: complete (commit e81e235, review clean — 2k customers, 100k tx, Nightfall typology, 499 annotations)
Task 4: complete (commit 6bf8090, review clean — feature_engineering, train, scorer, drift_monitor)
Task 5: complete (commit 0a642fa, review clean — investigator agent, 7 tools, llm_client CAII/vLLM/Ollama)
Task 6: complete (commit bc7c9d4, review clean — FastAPI: /api/alerts, /api/cases, /api/stats, /api/model/*)
Task 7: complete (commit 8ac3a1c, review clean — React: Dashboard A (AlertQueue+CaseWorkbench+AgentPanel), Dashboard B (ModelDashboard))
Orchestration fix: commit 74bb8da — start_backend.py, start_frontend.py, vite proxy port, manifest paths
Final: commit eea1d6a — .gitignore .claude/.omc, frontend dist path
