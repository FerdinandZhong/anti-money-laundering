# Embedded MCP Servers + Tools-Tab Parameters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Tools tab collects user parameters for two embedded Cloudera MCP servers (iceberg-mcp-server, CAI_Workbench_MCP_Server); the investigation workflow reads Iceberg data through the iceberg MCP server and the retraining workflow drives Workbench jobs through the Workbench MCP server — falling back to local CSV / local training when parameters are absent.

**Architecture:** Add stdio transport to `common/mcp_client.py` with a persistent session per embedded server (spawned via `uvx`, params passed as env vars). Route two existing seams through MCP when configured: `source.py` gains an `mcp` backend (all investigation data flows through it), `workbench.py` gains an MCP mode (retraining job/deploy ops flow through it). The Tools tab becomes two fixed parameter cards + the existing custom-server registry for the verification worker. Every fallback that exists today keeps working.

**Tech Stack:** Python 3.11, FastAPI, SQLite, `mcp` SDK (already a dependency), pandas; React 19 + Vite frontend. **No new dependencies** — `uvx` must be on PATH for embedded servers to launch (fail-soft when missing).

## Global Constraints

- Branch: `feat/tx-labels-and-caii-endpoints` (continue on it, no new branch)
- No new pip/npm dependencies
- Fail-soft everywhere: missing params → local mode; `uvx` missing / spawn fails / server errors → local mode with a visible status, never a crash
- Backend tests run from `02_backend/`: `python -m pytest -q`
- Frontend gate: `cd 03_frontend && npm run build`
- Existing behavior preserved: verification worker's custom HTTP MCP servers, `config.yaml` impala backend, env-var Workbench REST mode all keep working (MCP mode takes precedence when Tools-tab params exist)
- Embedded server launch commands (from the repos' READMEs):
  - iceberg: `uvx --from git+https://github.com/cloudera/iceberg-mcp-server@main run-server` with env `IMPALA_HOST, IMPALA_PORT, IMPALA_USER, IMPALA_PASSWORD, IMPALA_DATABASE` (stdio is the server's default transport)
  - workbench: `uvx --from git+https://github.com/cloudera/CAI_Workbench_MCP_Server.git --with <host>/api/v2/python.tar.gz cai-workbench-mcp-stdio` with env `CAI_WORKBENCH_HOST, CAI_WORKBENCH_API_KEY, CAI_WORKBENCH_PROJECT_ID`

---

### Task 1: `tool_config.params` column + embedded-row helpers

**Files:**
- Modify: `02_backend/common/db.py` (ALTER-TABLE self-heal loop, ~line 79)
- Test: `02_backend/tests/test_embedded_config.py` (new)

**Interfaces:**
- Produces: `tool_config` gains a nullable `params` TEXT column (JSON dict). Embedded servers are rows with `kind='embedded'`, `name` in `('iceberg-mcp','workbench-mcp')`, `transport='stdio'`, `url` NULL, `params` JSON. Later tasks read them via `mcp_client.embedded_params(name)`.

- [ ] **Step 1: Write the failing test**

```python
# 02_backend/tests/test_embedded_config.py
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_tool_config_has_params_column(tmp_path, monkeypatch):
    monkeypatch.setenv("AML_DB_PATH", str(tmp_path / "ops.db"))
    from common.db import get_connection
    conn = get_connection()
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(tool_config)")]
    assert "params" in cols
    conn.execute(
        "INSERT INTO tool_config (kind, name, transport, params) "
        "VALUES ('embedded', 'iceberg-mcp', 'stdio', ?)",
        (json.dumps({"impala_host": "h", "impala_user": "u"}),))
    conn.commit()
    row = conn.execute("SELECT params FROM tool_config WHERE name='iceberg-mcp'").fetchone()
    assert json.loads(row["params"])["impala_host"] == "h"
    conn.close()


def test_params_column_migration_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("AML_DB_PATH", str(tmp_path / "ops.db"))
    from common.db import get_connection
    get_connection().close()
    get_connection().close()  # second connect must not raise
```

Note: check how tests in `tests/test_status_backfill.py` point the DB at a temp path — reuse that fixture pattern verbatim if it differs from `AML_DB_PATH` (it may monkeypatch `common.db.get_db_path`). Match the existing pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 02_backend && python -m pytest tests/test_embedded_config.py -v`
Expected: FAIL — `params` not in columns.

- [ ] **Step 3: Add the column to the self-heal loop in `db.py`**

In `get_connection()`, next to the existing `ALTER TABLE cases ADD COLUMN` loop:

```python
    for col in ("params TEXT",):
        try:
            conn.execute(f"ALTER TABLE tool_config ADD COLUMN {col}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd 02_backend && python -m pytest tests/test_embedded_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add 02_backend/common/db.py 02_backend/tests/test_embedded_config.py
git commit -m "feat: tool_config.params column for embedded MCP server parameters"
```

---

### Task 2: stdio transport + embedded server registry in `mcp_client.py`

**Files:**
- Modify: `02_backend/common/mcp_client.py`
- Test: `02_backend/tests/test_mcp_embedded.py` (new)

**Interfaces:**
- Produces (all in `common.mcp_client`):
  - `EMBEDDED_SERVERS: dict[str, dict]` — registry: `{"iceberg-mcp": {...}, "workbench-mcp": {...}}` with keys `repo`, `entry`, `env_map` (param key → env var), `required` (param keys), `extra_args` (callable `params -> list[str]`)
  - `embedded_params(name: str) -> dict | None` — params dict from the enabled `kind='embedded'` row when ALL required keys are non-empty; else None
  - `call_embedded(name: str, tool: str, args: dict | None) -> str | dict` — call a tool on the embedded server; `{"error": ...}` on failure, never raises
  - `list_embedded_tools(name: str) -> list[dict] | None`
  - `probe_embedded(name: str, params: dict) -> tuple[bool, list[dict] | str]` — explicit-params test for the Tools view
  - `reset_embedded(name: str | None = None)` — drop cached stdio session(s); called after params change
- Existing HTTP functions (`list_tools_sync`, `call_tool_sync`, `probe`, `enabled_servers`) unchanged.

- [ ] **Step 1: Write the failing tests (mock the MCP SDK — no real spawn)**

```python
# 02_backend/tests/test_mcp_embedded.py
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import mcp_client


def _seed_embedded(conn, name, params, enabled=1):
    conn.execute(
        "INSERT INTO tool_config (kind, name, transport, params, enabled) "
        "VALUES ('embedded', ?, 'stdio', ?, ?)",
        (name, json.dumps(params), enabled))
    conn.commit()


def test_embedded_params_none_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setenv("AML_DB_PATH", str(tmp_path / "ops.db"))
    from common.db import get_connection
    get_connection().close()
    assert mcp_client.embedded_params("iceberg-mcp") is None


def test_embedded_params_none_when_required_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("AML_DB_PATH", str(tmp_path / "ops.db"))
    from common.db import get_connection
    conn = get_connection()
    _seed_embedded(conn, "iceberg-mcp", {"impala_host": "h"})  # missing user/password/database
    conn.close()
    assert mcp_client.embedded_params("iceberg-mcp") is None


def test_embedded_params_returns_complete_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AML_DB_PATH", str(tmp_path / "ops.db"))
    from common.db import get_connection
    conn = get_connection()
    _seed_embedded(conn, "iceberg-mcp", {
        "impala_host": "h", "impala_port": "443", "impala_user": "u",
        "impala_password": "p", "impala_database": "db"})
    conn.close()
    p = mcp_client.embedded_params("iceberg-mcp")
    assert p and p["impala_host"] == "h"


def test_embedded_params_none_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("AML_DB_PATH", str(tmp_path / "ops.db"))
    from common.db import get_connection
    conn = get_connection()
    _seed_embedded(conn, "workbench-mcp",
                   {"host": "https://ml-x", "api_key": "k", "project_id": "pid"},
                   enabled=0)
    conn.close()
    assert mcp_client.embedded_params("workbench-mcp") is None


def test_call_embedded_unconfigured_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("AML_DB_PATH", str(tmp_path / "ops.db"))
    from common.db import get_connection
    get_connection().close()
    res = mcp_client.call_embedded("iceberg-mcp", "execute_query", {"query": "SELECT 1"})
    assert isinstance(res, dict) and "error" in res


def test_registry_launch_spec():
    ice = mcp_client.EMBEDDED_SERVERS["iceberg-mcp"]
    assert ice["env_map"]["impala_host"] == "IMPALA_HOST"
    assert "impala_password" in ice["required"]
    wb = mcp_client.EMBEDDED_SERVERS["workbench-mcp"]
    assert wb["env_map"]["api_key"] == "CAI_WORKBENCH_API_KEY"
    # workbench needs the --with cmlapi tarball derived from host
    extra = wb["extra_args"]({"host": "https://ml-x.site"})
    assert "--with" in extra and "https://ml-x.site/api/v2/python.tar.gz" in extra
```

(Adapt the DB-path fixture to whatever `tests/test_status_backfill.py` uses, same as Task 1.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 02_backend && python -m pytest tests/test_mcp_embedded.py -v`
Expected: FAIL — `EMBEDDED_SERVERS` / `embedded_params` not defined.

- [ ] **Step 3: Implement in `mcp_client.py`**

Append after the existing HTTP config-lookup section:

```python
# ── embedded stdio servers (Cloudera iceberg / workbench MCP) ────────────────

EMBEDDED_SERVERS: dict[str, dict] = {
    "iceberg-mcp": {
        "repo": "git+https://github.com/cloudera/iceberg-mcp-server@main",
        "entry": "run-server",
        "env_map": {"impala_host": "IMPALA_HOST", "impala_port": "IMPALA_PORT",
                    "impala_user": "IMPALA_USER", "impala_password": "IMPALA_PASSWORD",
                    "impala_database": "IMPALA_DATABASE"},
        "required": ["impala_host", "impala_user", "impala_password", "impala_database"],
        "extra_args": lambda params: [],
    },
    "workbench-mcp": {
        "repo": "git+https://github.com/cloudera/CAI_Workbench_MCP_Server.git",
        "entry": "cai-workbench-mcp-stdio",
        "env_map": {"host": "CAI_WORKBENCH_HOST", "api_key": "CAI_WORKBENCH_API_KEY",
                    "project_id": "CAI_WORKBENCH_PROJECT_ID"},
        "required": ["host", "api_key", "project_id"],
        # cmlapi SDK ships from the workbench itself
        "extra_args": lambda params: ["--with", f"{params['host'].rstrip('/')}/api/v2/python.tar.gz"],
    },
}


def embedded_params(name: str) -> dict | None:
    """Params for an enabled embedded server, or None unless ALL required keys set."""
    spec = EMBEDDED_SERVERS.get(name)
    if not spec:
        return None
    try:
        import json as _json
        from common.db import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT params FROM tool_config "
                "WHERE name=? AND enabled=1 AND kind='embedded' LIMIT 1",
                (name,)).fetchone()
        finally:
            conn.close()
        if not row or not row["params"]:
            return None
        params = _json.loads(row["params"])
        if not all(str(params.get(k) or "").strip() for k in spec["required"]):
            return None
        return params
    except Exception:
        return None


# Persistent stdio session per embedded server: uvx re-resolves the git dep on
# every spawn, so spawn-per-call would cost seconds per query. Sessions live on
# the background loop and are torn down + re-opened on any error.
# ponytail: no health-check/idle-timeout; a wedged server heals on next call's
# error path. Add keepalive pings if long-lived sessions prove flaky.
_stdio_sessions: dict[str, tuple] = {}   # name -> (session, AsyncExitStack)


async def _aopen_stdio(name: str, params: dict):
    import os as _os
    from contextlib import AsyncExitStack
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    spec = EMBEDDED_SERVERS[name]
    env = {v: str(params[k]) for k, v in spec["env_map"].items()
           if str(params.get(k) or "").strip()}
    args = ["--from", spec["repo"], *spec["extra_args"](params), spec["entry"]]
    stack = AsyncExitStack()
    read, write = await stack.enter_async_context(stdio_client(
        StdioServerParameters(command="uvx", args=args, env={**_os.environ, **env})))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session, stack


async def _aembedded_session(name: str, params: dict):
    if name not in _stdio_sessions:
        _stdio_sessions[name] = await _aopen_stdio(name, params)
    return _stdio_sessions[name][0]


async def _aembedded_close(name: str):
    entry = _stdio_sessions.pop(name, None)
    if entry:
        try:
            await entry[1].aclose()
        except Exception:
            pass


def reset_embedded(name: str | None = None) -> None:
    """Drop cached stdio session(s) — call after params change."""
    names = [name] if name else list(_stdio_sessions)
    for n in names:
        try:
            _run(_aembedded_close(n), timeout=10)
        except Exception:
            _stdio_sessions.pop(n, None)


def list_embedded_tools(name: str) -> list[dict] | None:
    params = embedded_params(name)
    if not params:
        return None

    async def _do():
        session = await _aembedded_session(name, params)
        resp = await session.list_tools()
        return [{"name": t.name, "description": t.description or "",
                 "input_schema": t.inputSchema or {"type": "object", "properties": {}}}
                for t in resp.tools]
    try:
        return _run(_do(), timeout=120)   # first call may uvx-resolve the package
    except Exception:
        _run_silent_close(name)
        return None


def call_embedded(name: str, tool: str, args: dict | None = None):
    """Call a tool on an embedded server. {'error': ...} on any failure."""
    params = embedded_params(name)
    if not params:
        return {"error": f"embedded server '{name}' not configured"}

    async def _do():
        session = await _aembedded_session(name, params)
        result = await session.call_tool(tool, arguments=args or {})
        return _content_to_text(result)
    try:
        return _run(_do(), timeout=120)
    except Exception as e:
        _run_silent_close(name)
        return {"error": f"embedded mcp call failed: {e}"}


def probe_embedded(name: str, params: dict) -> tuple[bool, "list[dict] | str"]:
    """Explicit-params connectivity test for the Tools view (fresh session,
    torn down after)."""
    async def _do():
        session, stack = await _aopen_stdio(name, params)
        try:
            resp = await session.list_tools()
            return [{"name": t.name} for t in resp.tools]
        finally:
            await stack.aclose()
    try:
        return True, _run(_do(), timeout=120)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _run_silent_close(name: str) -> None:
    try:
        _run(_aembedded_close(name), timeout=10)
    except Exception:
        _stdio_sessions.pop(name, None)
```

Also extend the `__main__` block to print embedded-server status:

```python
    for name in EMBEDDED_SERVERS:
        p = embedded_params(name)
        if not p:
            print(f"mcp_client: {name} not configured (local fallback)")
        else:
            tools = list_embedded_tools(name)
            print(f"mcp_client: {name} — "
                  + (f"OK, tools: {[t['name'] for t in tools]}" if tools else "FAILED to connect"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 02_backend && python -m pytest tests/test_mcp_embedded.py tests/test_mcp_client.py -v`
Expected: PASS (new + existing HTTP-client tests untouched).

- [ ] **Step 5: Commit**

```bash
git add 02_backend/common/mcp_client.py 02_backend/tests/test_mcp_embedded.py
git commit -m "feat: stdio transport + embedded Cloudera MCP server registry"
```

---

### Task 3: embedded-config API endpoints

**Files:**
- Modify: `02_backend/api/main.py` (after the existing `/api/config/tools` section, ~line 656)
- Test: `02_backend/tests/test_embedded_api.py` (new)

**Interfaces:**
- Consumes: `mcp_client.EMBEDDED_SERVERS`, `embedded_params`, `probe_embedded`, `reset_embedded` (Task 2)
- Produces:
  - `GET /api/config/embedded` → `{"servers": [{name, enabled, configured, params: {<key>: <value-or-masked>}, required: [...], fields: [...]}]}` — secret-ish keys (`impala_password`, `api_key`) masked as `"•••"` when set
  - `PUT /api/config/embedded/{name}` body `{"params": {...}, "enabled": true}` → upsert row; masked/blank secret values keep the stored secret; calls `reset_embedded(name)` and `source.reset_backend()` (Task 4 — guard with `getattr` until then)
  - `POST /api/config/embedded/{name}/test` body `{"params": {...}}` (optional; falls back to stored) → `{"ok": bool, "tools": [...], "count": n}` or `{"ok": false, "message": str}`

- [ ] **Step 1: Write the failing tests**

```python
# 02_backend/tests/test_embedded_api.py
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("AML_DB_PATH", str(tmp_path / "ops.db"))
    from api.main import app
    return TestClient(app)


def test_get_embedded_lists_both_servers(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/config/embedded")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["servers"]}
    assert names == {"iceberg-mcp", "workbench-mcp"}
    ice = next(s for s in r.json()["servers"] if s["name"] == "iceberg-mcp")
    assert ice["configured"] is False


def test_put_then_get_masks_secrets(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.put("/api/config/embedded/iceberg-mcp", json={"enabled": True, "params": {
        "impala_host": "h", "impala_port": "443", "impala_user": "u",
        "impala_password": "secret", "impala_database": "db"}})
    assert r.status_code == 200
    ice = next(s for s in c.get("/api/config/embedded").json()["servers"]
               if s["name"] == "iceberg-mcp")
    assert ice["configured"] is True
    assert ice["params"]["impala_password"] == "•••"
    assert ice["params"]["impala_host"] == "h"


def test_put_masked_secret_keeps_stored_value(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.put("/api/config/embedded/iceberg-mcp", json={"enabled": True, "params": {
        "impala_host": "h", "impala_user": "u",
        "impala_password": "secret", "impala_database": "db"}})
    # resubmit with the mask — password must survive
    c.put("/api/config/embedded/iceberg-mcp", json={"enabled": True, "params": {
        "impala_host": "h2", "impala_user": "u",
        "impala_password": "•••", "impala_database": "db"}})
    from common.db import get_connection
    conn = get_connection()
    row = conn.execute("SELECT params FROM tool_config WHERE name='iceberg-mcp'").fetchone()
    conn.close()
    stored = json.loads(row["params"])
    assert stored["impala_password"] == "secret"
    assert stored["impala_host"] == "h2"


def test_put_unknown_server_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.put("/api/config/embedded/nope", json={"params": {}}).status_code == 404


def test_test_endpoint_uses_probe(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    from common import mcp_client
    monkeypatch.setattr(mcp_client, "probe_embedded",
                        lambda name, params: (True, [{"name": "execute_query"}]))
    r = c.post("/api/config/embedded/iceberg-mcp/test", json={"params": {
        "impala_host": "h", "impala_user": "u",
        "impala_password": "p", "impala_database": "db"}})
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 02_backend && python -m pytest tests/test_embedded_api.py -v`
Expected: FAIL — 404 on `/api/config/embedded`.

- [ ] **Step 3: Implement the endpoints in `main.py`**

Add a Pydantic body near the existing `ToolConfigBody`:

```python
class EmbeddedConfigBody(BaseModel):
    params: dict = {}
    enabled: bool = True
```

Add after the `/api/config/tools/{tool_id}/test` endpoint:

```python
# ── embedded MCP servers (fixed registry, parameter-driven) ──────────────────

_SECRET_KEYS = {"impala_password", "api_key"}
_MASK = "•••"


def _embedded_row(conn, name: str):
    return conn.execute(
        "SELECT * FROM tool_config WHERE name=? AND kind='embedded'", (name,)
    ).fetchone()


@app.get("/api/config/embedded")
def list_embedded(conn=Depends(get_db)):
    from common import mcp_client
    servers = []
    for name, spec in mcp_client.EMBEDDED_SERVERS.items():
        row = _embedded_row(conn, name)
        stored = json.loads(row["params"]) if row and row["params"] else {}
        masked = {k: (_MASK if k in _SECRET_KEYS and v else v) for k, v in stored.items()}
        servers.append({
            "name": name,
            "enabled": bool(row["enabled"]) if row else False,
            "configured": mcp_client.embedded_params(name) is not None,
            "params": masked,
            "required": spec["required"],
            "fields": list(spec["env_map"].keys()),
        })
    return {"servers": servers}


@app.put("/api/config/embedded/{name}")
def update_embedded(name: str, body: EmbeddedConfigBody, conn=Depends(get_db)):
    from common import mcp_client
    if name not in mcp_client.EMBEDDED_SERVERS:
        raise HTTPException(404, f"unknown embedded server '{name}'")
    row = _embedded_row(conn, name)
    stored = json.loads(row["params"]) if row and row["params"] else {}
    merged = dict(stored)
    for k, v in (body.params or {}).items():
        v = str(v or "").strip()
        if k in _SECRET_KEYS and (not v or v == _MASK):
            continue                      # blank/masked secret = keep existing
        merged[k] = v
    if row:
        conn.execute("UPDATE tool_config SET params=?, enabled=? WHERE id=?",
                     (json.dumps(merged), 1 if body.enabled else 0, row["id"]))
    else:
        conn.execute(
            "INSERT INTO tool_config (kind, name, transport, params, enabled) "
            "VALUES ('embedded', ?, 'stdio', ?, ?)",
            (name, json.dumps(merged), 1 if body.enabled else 0))
    conn.commit()
    mcp_client.reset_embedded(name)
    from common import source
    reset = getattr(source, "reset_backend", None)   # arrives in Task 4
    if reset:
        reset()
    return {"ok": True, "name": name}


@app.post("/api/config/embedded/{name}/test")
def test_embedded(name: str, body: EmbeddedConfigBody, conn=Depends(get_db)):
    from common import mcp_client
    if name not in mcp_client.EMBEDDED_SERVERS:
        raise HTTPException(404, f"unknown embedded server '{name}'")
    row = _embedded_row(conn, name)
    stored = json.loads(row["params"]) if row and row["params"] else {}
    params = dict(stored)
    for k, v in (body.params or {}).items():
        v = str(v or "").strip()
        if v and v != _MASK:
            params[k] = v
    ok, res = mcp_client.probe_embedded(name, params)
    if ok:
        return {"ok": True, "tools": [t["name"] for t in res], "count": len(res)}
    return {"ok": False, "message": str(res)}
```

(`json` and `HTTPException` are already imported in `main.py` — verify, add if missing.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 02_backend && python -m pytest tests/test_embedded_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 02_backend/api/main.py 02_backend/tests/test_embedded_api.py
git commit -m "feat: embedded MCP server config API (params, mask, probe)"
```

---

### Task 4: `source.py` gains the `mcp` backend (investigation data via iceberg MCP)

**Files:**
- Modify: `02_backend/common/source.py` (backend resolution ~line 93, `_impala_df` ~line 126)
- Test: `02_backend/tests/test_source_mcp.py` (new)

**Interfaces:**
- Consumes: `mcp_client.embedded_params("iceberg-mcp")`, `mcp_client.call_embedded("iceberg-mcp", "execute_query", {"query": sql})` → JSON string of row dicts (the server's documented output)
- Produces:
  - `backend()` may now return `"mcp"` (resolution order: iceberg-mcp params configured → `mcp`; else existing auto/impala/csv logic unchanged)
  - `reset_backend()` — clears the cached resolution (Task 3's PUT calls it)
  - `_mcp_df(sql: str) -> pd.DataFrame` — internal; on MCP error raises `RuntimeError` so the caller path stays fail-fast per query while `backend()` itself only picks `mcp` after a successful probe
- Every public source function keeps its signature; each `if backend() == "impala":` branch becomes `if backend() in ("impala", "mcp"):` routed through a shared `_sql_df(sql, params)` helper that formats params inline for MCP (the MCP tool takes one query string).

- [ ] **Step 1: Write the failing tests (mock `call_embedded`)**

```python
# 02_backend/tests/test_source_mcp.py
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fake_params(monkeypatch, present=True):
    from common import mcp_client
    monkeypatch.setattr(mcp_client, "embedded_params",
                        lambda name: {"impala_host": "h"} if present else None)


def test_backend_resolves_mcp_when_configured(monkeypatch):
    from common import source, mcp_client
    source.reset_backend()
    _fake_params(monkeypatch, True)
    monkeypatch.setattr(mcp_client, "list_embedded_tools",
                        lambda name: [{"name": "execute_query"}])
    assert source.backend() == "mcp"
    source.reset_backend()


def test_backend_falls_back_when_unconfigured(monkeypatch):
    from common import source
    source.reset_backend()
    _fake_params(monkeypatch, False)
    assert source.backend() in ("csv", "impala")   # existing auto logic
    source.reset_backend()


def test_backend_falls_back_when_probe_fails(monkeypatch):
    from common import source, mcp_client
    source.reset_backend()
    _fake_params(monkeypatch, True)
    monkeypatch.setattr(mcp_client, "list_embedded_tools", lambda name: None)
    assert source.backend() in ("csv", "impala")
    source.reset_backend()


def test_mcp_df_parses_json_rows(monkeypatch):
    from common import source, mcp_client
    rows = [{"account_id": "A1", "amount": 5.0}]
    monkeypatch.setattr(mcp_client, "call_embedded",
                        lambda name, tool, args: json.dumps(rows))
    df = source._mcp_df("SELECT 1")
    assert list(df["account_id"]) == ["A1"]


def test_mcp_df_error_raises(monkeypatch):
    from common import source, mcp_client
    monkeypatch.setattr(mcp_client, "call_embedded",
                        lambda name, tool, args: {"error": "boom"})
    import pytest
    with pytest.raises(RuntimeError):
        source._mcp_df("SELECT 1")


def test_get_account_via_mcp(monkeypatch):
    from common import source, mcp_client
    source.reset_backend()
    _fake_params(monkeypatch, True)
    monkeypatch.setattr(mcp_client, "list_embedded_tools",
                        lambda name: [{"name": "execute_query"}])
    monkeypatch.setattr(mcp_client, "call_embedded",
                        lambda name, tool, args: json.dumps(
                            [{"account_id": "ACC-1", "customer_id": "CUST-1"}]))
    acc = source.get_account("ACC-1")
    assert acc["customer_id"] == "CUST-1"
    source.reset_backend()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 02_backend && python -m pytest tests/test_source_mcp.py -v`
Expected: FAIL — `reset_backend` / `_mcp_df` not defined.

- [ ] **Step 3: Implement in `source.py`**

Add after `backend()`:

```python
def reset_backend() -> None:
    """Forget the resolved backend (call after Tools-tab params change)."""
    global _backend, _impala_conn
    _backend = None
    _impala_conn = None
```

Modify `backend()` — insert the MCP check before the existing auto/impala logic:

```python
def backend() -> str:
    """Resolve the source backend once ('mcp', 'impala' or 'csv')."""
    global _backend, _impala_conn
    if _backend is not None:
        return _backend
    from common import mcp_client
    if mcp_client.embedded_params("iceberg-mcp") is not None:
        if mcp_client.list_embedded_tools("iceberg-mcp"):
            _backend = "mcp"
            print("[source] backend=mcp (iceberg-mcp-server via Tools tab)")
            return _backend
        print("[source] iceberg-mcp configured but unreachable; trying impala/csv")
    # ... existing want/auto/impala/csv logic unchanged below ...
```

Add `_mcp_df` next to `_impala_df`:

```python
def _mcp_df(sql: str) -> pd.DataFrame:
    """Run SQL through the embedded iceberg MCP server (execute_query → JSON)."""
    from common import mcp_client
    res = mcp_client.call_embedded("iceberg-mcp", "execute_query", {"query": sql})
    if isinstance(res, dict):                      # {"error": ...}
        raise RuntimeError(f"iceberg-mcp query failed: {res.get('error')}")
    import json as _json
    try:
        rows = _json.loads(res)
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"iceberg-mcp returned non-JSON: {e}")
    return pd.DataFrame(rows if isinstance(rows, list) else [rows])
```

Add a shared SQL dispatcher and route every `if backend() == "impala":` branch through it. The MCP tool takes a single query string, so interpolate params with basic SQL-string escaping (values here are internal IDs, not user free-text, but escape quotes anyway):

```python
def _sql_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Dispatch SQL to impala (parameterized) or MCP (inlined literals)."""
    if backend() == "impala":
        return _impala_df(sql, params)
    def _lit(v):
        if isinstance(v, (int, float)):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"
    inlined = sql
    for v in params:
        inlined = inlined.replace("%s", _lit(v), 1)
    return _mcp_df(inlined)
```

Then mechanically update each public function, e.g. `get_account`:

```python
def get_account(account_id: str) -> dict | None:
    if backend() in ("impala", "mcp"):
        df = _sql_df("SELECT * FROM accounts WHERE account_id = %s", (account_id,))
    else:
        df = _csv("accounts")
        df = df[df["account_id"] == account_id]
    rows = _records(df)
    return rows[0] if rows else None
```

Apply the same `in ("impala", "mcp")` + `_sql_df` change to: `get_customer`, `get_accounts`, `customer_transactions`, `account_transactions`, `device_fingerprints`, `devices_by_fingerprints`, `accounts_by_fingerprints`, `count_suspicious`, `count_transactions`, `transactions_features_df`, `devices_df` — every function with an `if backend() == "impala":` branch. `fund_flow_edges` is pure (no change).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 02_backend && python -m pytest tests/test_source_mcp.py tests/test_network_graph.py -v`
Expected: PASS (including the existing network-graph tests, which exercise the CSV path).

- [ ] **Step 5: Commit**

```bash
git add 02_backend/common/source.py 02_backend/tests/test_source_mcp.py
git commit -m "feat: source layer 'mcp' backend via embedded iceberg-mcp-server"
```

---

### Task 5: `workbench.py` MCP mode (retraining via Workbench MCP server)

**Files:**
- Modify: `02_backend/common/workbench.py`
- Modify: `02_backend/agents/retraining.py` (mode string only, line 62)
- Test: `02_backend/tests/test_workbench_mcp.py` (new)

**Interfaces:**
- Consumes: `mcp_client.embedded_params("workbench-mcp")`, `mcp_client.call_embedded("workbench-mcp", <tool>, args)`, `mcp_client.list_embedded_tools("workbench-mcp")`
- Produces (in `common.workbench`):
  - `mode() -> str` — `"mcp"` (Tools-tab params present) | `"rest"` (env/config present) | `"local"`
  - `configured() -> bool` — now `mode() != "local"` (keeps every existing caller working)
  - Existing functions (`create_training_job`, `run_job`, `get_job_run`, `canary_deploy`) route through MCP tools when `mode()=="mcp"`, else the current REST path — same signatures, same `WorkbenchError` on failure
  - `_mcp_tool(candidates: list[str]) -> str` — resolves the actual tool name from the server's tool list (the 105-tool server wraps cmlapi; names are verified at runtime, not hardcoded blindly)
- `retraining.py` line 62 becomes `mode = workbench.mode() if workbench.configured() else "local"` — the SSE `detail` strings then honestly show `mode=mcp` in the ModelOps stream.

**⚠ Implementation note:** the exact MCP tool names must be confirmed against a live `list_tools` (Tools tab → Test connection) during implementation. The candidates below follow the cmlapi v2 naming the server wraps (`create_job`, `create_job_run`, `list_job_runs`, `get_job_run`, `create_model`, `create_model_build`, `create_model_deployment`). `_mcp_tool` picks the first candidate present; raises `WorkbenchError` when none match, which falls back cleanly.

- [ ] **Step 1: Write the failing tests (mock `call_embedded` / `list_embedded_tools`)**

```python
# 02_backend/tests/test_workbench_mcp.py
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import workbench, mcp_client


def _mcp_configured(monkeypatch, tools=("create_job", "create_job_run",
                                        "get_job_run", "create_model",
                                        "create_model_build", "create_model_deployment")):
    monkeypatch.setattr(mcp_client, "embedded_params",
                        lambda name: {"host": "https://ml-x", "api_key": "k",
                                      "project_id": "pid"} if name == "workbench-mcp" else None)
    monkeypatch.setattr(mcp_client, "list_embedded_tools",
                        lambda name: [{"name": t} for t in tools])


def test_mode_local_when_nothing(monkeypatch):
    monkeypatch.setattr(mcp_client, "embedded_params", lambda name: None)
    for k in ("CAI_WORKBENCH_HOST", "CAI_WORKBENCH_PROJECT_ID", "CAI_WORKBENCH_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert workbench.mode() == "local"
    assert workbench.configured() is False


def test_mode_mcp_when_tools_params(monkeypatch):
    _mcp_configured(monkeypatch)
    assert workbench.mode() == "mcp"
    assert workbench.configured() is True


def test_create_job_routes_through_mcp(monkeypatch):
    _mcp_configured(monkeypatch)
    calls = []
    def fake_call(name, tool, args):
        calls.append((tool, args))
        return json.dumps({"id": "job-42"})
    monkeypatch.setattr(mcp_client, "call_embedded", fake_call)
    job_id = workbench.create_training_job("aml-retrain", "02_backend/ml/train.py")
    assert job_id == "job-42"
    assert calls[0][0] == "create_job"


def test_mcp_error_raises_workbench_error(monkeypatch):
    _mcp_configured(monkeypatch)
    monkeypatch.setattr(mcp_client, "call_embedded",
                        lambda name, tool, args: {"error": "boom"})
    import pytest
    with pytest.raises(workbench.WorkbenchError):
        workbench.create_training_job("aml-retrain", "x.py")


def test_missing_tool_name_raises(monkeypatch):
    _mcp_configured(monkeypatch, tools=("something_else",))
    import pytest
    with pytest.raises(workbench.WorkbenchError):
        workbench.create_training_job("aml-retrain", "x.py")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd 02_backend && python -m pytest tests/test_workbench_mcp.py -v`
Expected: FAIL — `workbench.mode` not defined.

- [ ] **Step 3: Implement in `workbench.py`**

Add after `configured()` (and change `configured()`):

```python
def mode() -> str:
    """'mcp' (Tools-tab params) | 'rest' (env/config) | 'local'."""
    from common import mcp_client
    if mcp_client.embedded_params("workbench-mcp") is not None:
        return "mcp"
    if _host() and _project() and _token():
        return "rest"
    return "local"


def configured() -> bool:
    """True when the retraining workflow can reach a real Workbench (MCP or REST)."""
    return mode() != "local"
```

Add the MCP call helpers:

```python
# ── MCP routing (embedded CAI_Workbench_MCP_Server) ──────────────────────────

def _mcp_tool(candidates: list[str]) -> str:
    """Resolve the actual tool name exposed by the server; the 105-tool server
    wraps cmlapi so names follow its conventions, but we verify at runtime."""
    from common import mcp_client
    listed = mcp_client.list_embedded_tools("workbench-mcp") or []
    names = {t["name"] for t in listed}
    for c in candidates:
        if c in names:
            return c
    raise WorkbenchError(f"workbench-mcp exposes none of {candidates}")


def _mcp_call(candidates: list[str], args: dict) -> dict:
    from common import mcp_client
    res = mcp_client.call_embedded("workbench-mcp", _mcp_tool(candidates), args)
    if isinstance(res, dict) and "error" in res:
        raise WorkbenchError(str(res["error"]))
    try:
        out = json.loads(res) if isinstance(res, str) else res
    except ValueError:
        raise WorkbenchError(f"workbench-mcp returned non-JSON: {res[:200]}")
    return out if isinstance(out, dict) else {}
```

Route the four public functions — each gains a leading MCP branch, REST path untouched. Example (`create_training_job`; apply the same shape to the others):

```python
def create_training_job(name: str, script: str, runtime_id: str | None = None,
                        cpu: float = 1.0, memory: float = 4.0) -> str:
    if mode() == "mcp":
        body: dict = {"name": name, "script": script, "kernel": "python3",
                      "cpu": cpu, "memory": memory}
        if runtime_id:
            body["runtime_identifier"] = runtime_id
        out = _mcp_call(["create_job"], body)
        job_id = out.get("id") or out.get("job", {}).get("id")
        if not job_id:
            raise WorkbenchError(f"mcp create_job returned no id: {out}")
        return str(job_id)
    # ── existing REST path unchanged ──
    body: dict = {"name": name, "script": script, "kernel": "python3",
                  "cpu": cpu, "memory": memory}
    ...
```

- `run_job` → `_mcp_call(["create_job_run"], {"job_id": job_id})`
- `get_job_run` → `_mcp_call(["get_job_run"], {"job_id": job_id, "run_id": run_id})`
- `canary_deploy` → three `_mcp_call`s: `["create_model"]` (after a `["list_models"]` lookup mirroring `_find_model`), `["create_model_build"]`, `["create_model_deployment"]` — same id-extraction and `WorkbenchError` checks as the REST path.

Update `retraining.py` line 62:

```python
    mode = workbench.mode() if workbench.configured() else "local"
```

(Downstream `if mode == "workbench":` checks become `if mode != "local":` — grep the file, there are two.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd 02_backend && python -m pytest tests/test_workbench_mcp.py -v && python -m agents.retraining`
Expected: tests PASS; the retraining self-check still completes in local mode (`[retraining] OK`).

- [ ] **Step 5: Commit**

```bash
git add 02_backend/common/workbench.py 02_backend/agents/retraining.py 02_backend/tests/test_workbench_mcp.py
git commit -m "feat: workbench MCP mode — retraining drives CML via CAI_Workbench_MCP_Server"
```

---

### Task 6: ToolsView redesign — embedded server cards + custom registry

**Files:**
- Modify: `03_frontend/src/api.ts`
- Modify: `03_frontend/src/components/ToolsView.tsx`

**Interfaces:**
- Consumes: `GET /api/config/embedded`, `PUT /api/config/embedded/{name}`, `POST /api/config/embedded/{name}/test` (Task 3)
- Produces (in `api.ts`):

```typescript
export interface EmbeddedServer {
  name: string
  enabled: boolean
  configured: boolean
  params: Record<string, string>
  required: string[]
  fields: string[]
}
export const getEmbedded = () =>
  api.get<{ servers: EmbeddedServer[] }>('/config/embedded').then(r => r.data.servers)
export const updateEmbedded = (name: string, body: { params: Record<string, string>; enabled: boolean }) =>
  api.put(`/config/embedded/${name}`, body).then(r => r.data)
export const testEmbedded = (name: string, params: Record<string, string>) =>
  api.post<ToolTestResult>(`/config/embedded/${name}/test`, { params }).then(r => r.data)
```

- [ ] **Step 1: Add the api.ts types + functions above** (next to the existing `getTools`/`testTool`).

- [ ] **Step 2: Rebuild ToolsView with two sections**

Section 1 — "Embedded Cloudera MCP Servers": one card per server from `getEmbedded()`. Card metadata is a frontend constant (mirror pattern like `WORKER_TOOLS` in AgentPanel):

```typescript
const EMBEDDED_META: Record<string, {
  title: string; blurb: string; fallback: string
  labels: Record<string, string>; secrets: string[]
}> = {
  'iceberg-mcp': {
    title: 'Iceberg MCP Server',
    blurb: 'Read-only Iceberg/Impala access for the investigation agents (execute_query, get_schema).',
    fallback: 'Unconfigured — investigation reads the local CSV dataset.',
    labels: {
      impala_host: 'Impala host', impala_port: 'Port', impala_user: 'Workload user',
      impala_password: 'Workload password', impala_database: 'Database',
    },
    secrets: ['impala_password'],
  },
  'workbench-mcp': {
    title: 'CAI Workbench MCP Server',
    blurb: 'Drives training jobs + canary model deployments on Cloudera AI Workbench for the retraining workflow.',
    fallback: 'Unconfigured — retraining trains locally, no Workbench job is created.',
    labels: { host: 'Workbench host', api_key: 'API key', project_id: 'Project ID' },
    secrets: ['api_key'],
  },
}
```

Each card renders: title + blurb, a status pill (`configured ? 'Active' : 'Local fallback'` with the `fallback` text), one `Input` per `fields` entry (secrets as `type="password"`, placeholder "leave blank to keep current" when a mask is stored), an Enabled checkbox, **Save** (calls `updateEmbedded`, reloads) and **Test connection** (calls `testEmbedded` with the current form values; renders tool list or error exactly like the existing custom-server test chip).

Card component (full code):

```tsx
const EmbeddedCard: React.FC<{ server: EmbeddedServer; onSaved: () => void }> = ({ server, onSaved }) => {
  const meta = EMBEDDED_META[server.name]
  const [form, setForm] = useState<Record<string, string>>({ ...server.params })
  const [enabled, setEnabled] = useState(server.enabled)
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const save = async () => {
    setBusy(true); setMsg(null)
    try {
      await updateEmbedded(server.name, { params: form, enabled })
      setMsg({ ok: true, text: 'Saved.' }); onSaved()
    } catch { setMsg({ ok: false, text: 'Save failed — check the backend.' }) }
    setBusy(false)
  }

  const test = async () => {
    setTesting(true); setMsg(null)
    try {
      const r = await testEmbedded(server.name, form)
      setMsg(r.ok
        ? { ok: true, text: `${r.count} tool(s): ${(r.tools ?? []).join(', ')}` }
        : { ok: false, text: r.message ?? 'Connection failed' })
    } catch { setMsg({ ok: false, text: 'Test failed — check the backend.' }) }
    setTesting(false)
  }

  return (
    <div className="bg-surface-1 rounded-lg p-5 shadow-soft space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-ink">{meta.title}</h3>
          <p className="text-xs text-ink-muted mt-0.5 max-w-xl">{meta.blurb}</p>
        </div>
        <span className={`text-2xs font-semibold px-2 py-1 rounded-full shrink-0
          ${server.configured ? 'bg-aml-green/10 text-aml-green-dim' : 'bg-surface-2 text-ink-faint'}`}>
          {server.configured ? 'Active' : 'Local fallback'}
        </span>
      </div>
      {!server.configured && <p className="text-2xs text-ink-faint">{meta.fallback}</p>}
      <div className="grid grid-cols-2 gap-4">
        {server.fields.map(f => (
          <Field key={f} label={meta.labels[f] ?? f}>
            <Input
              value={form[f] ?? ''}
              type={meta.secrets.includes(f) ? 'password' : 'text'}
              placeholder={meta.secrets.includes(f) && server.params[f] ? 'leave blank to keep current' : ''}
              onChange={e => setForm(prev => ({ ...prev, [f]: e.target.value }))}
            />
          </Field>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button onClick={save} disabled={busy}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold transition-colors
            ${busy ? 'bg-surface-3 text-ink-faint cursor-not-allowed' : 'bg-accent text-white hover:bg-accent-dim'}`}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} Save
        </button>
        <button onClick={test} disabled={testing}
          className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm text-ink-muted bg-surface-2 hover:bg-surface-3 transition-colors">
          {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plug className="w-4 h-4" />} Test connection
        </button>
        <label className="flex items-center gap-2 text-sm text-ink-muted">
          <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}
            className="accent-accent w-4 h-4" /> Enabled
        </label>
        {msg && <span className={`text-xs ${msg.ok ? 'text-aml-green-dim' : 'text-aml-red-dim'}`}>{msg.text}</span>}
      </div>
    </div>
  )
}
```

Section 2 — "Custom verification servers": the ENTIRE existing generic form + table, unchanged, retitled with the blurb "Remote streamable-HTTP MCP servers used by the verification agent (sanctions, registry, adverse media…)."

Top-level component: load both `getEmbedded()` and `getTools()`; render `servers.map(s => <EmbeddedCard …/>)` then the custom section.

- [ ] **Step 3: Build**

Run: `cd 03_frontend && npm run build`
Expected: clean tsc + vite build.

- [ ] **Step 4: Commit**

```bash
git add 03_frontend/src/api.ts 03_frontend/src/components/ToolsView.tsx
git commit -m "feat: Tools tab — embedded Cloudera MCP server parameter cards"
```

---

### Task 7: Regression + README

**Files:**
- Modify: `README.md` (replace the "MCP tool servers + verification agent" Tools-tab paragraph)

- [ ] **Step 1: Full backend regression**

Run: `cd 02_backend && python -m pytest -q`
Expected: all green (existing 62 + ~20 new).

- [ ] **Step 2: Frontend build**

Run: `cd 03_frontend && npm run build`
Expected: clean.

- [ ] **Step 3: Manual smoke (via `python start_app.py`)**

- Tools tab shows both embedded cards in "Local fallback" state + the custom verification section.
- With no params: open an alert (CSV data), run a retrain from ModelOps (`mode=local` in the stream) — both work exactly as before.
- (If you have a live DataHub/Workbench): fill the Iceberg card → Test connection lists `execute_query, get_schema` → Save → reopen an alert (data now flows through MCP; backend log shows `[source] backend=mcp`). Fill the Workbench card → retrain from ModelOps → stream shows `mode=mcp`, `create_job` / `create_job_run` steps.

- [ ] **Step 4: README update**

Replace the "Configure servers in the **Tools** tab" paragraph with:

```markdown
Configure servers in the **Tools** tab (persisted in the ops `tool_config` table):

- **Embedded Cloudera MCP servers** — two parameter cards:
  [iceberg-mcp-server](https://github.com/cloudera/iceberg-mcp-server) (Impala
  host/port/user/password/database) feeds the investigation agents' Iceberg
  reads, and [CAI_Workbench_MCP_Server](https://github.com/cloudera/CAI_Workbench_MCP_Server)
  (Workbench host/API key/project ID) drives the retraining workflow's training
  job + canary deployment. Both are spawned on demand over stdio via `uvx`.
  **Leave a card blank and the app runs fully locally** — investigation reads
  the CSV dataset, retraining trains in-process with a simulated canary.
- **Custom verification servers** — remote streamable-HTTP MCP servers the
  verification worker calls to confirm/refute findings, as before.
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: Tools tab — embedded MCP servers with local fallback"
```

---

## Risks / open items (verify during implementation)

1. **Workbench MCP tool names** — the candidate names in Task 5 follow cmlapi conventions but must be confirmed via Test connection against a live server; `_mcp_tool` fails soft to local mode if none match. Adjust candidates on first contact.
2. **`uvx` availability** — required on PATH for embedded spawn (dev laptops: `brew install uv`; CML runtimes: add to `01_installer/install.py` as `pip install uv` if absent). Probe reports a clear error when missing; everything falls back local.
3. **iceberg-mcp `execute_query` output shape** — assumed JSON list of row dicts per the README; `_mcp_df` raises (→ visible error) on anything else. Confirm on first live test.
4. **CML sandboxes may block subprocess spawn** (noted in the current README's stretch section) — in that environment embedded servers won't launch and the app runs in local mode; the Tools card's Test button surfaces the spawn error honestly.
