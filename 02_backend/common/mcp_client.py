"""Remote streamable-HTTP MCP client with a sync bridge for the threaded workers.

Reads enabled servers from the `tool_config` table. Everything fails soft: any
connect / list / call error returns None (or an {"error": ...} dict) so callers
degrade to non-MCP behaviour. HTTP URL only — stdio spawn is deferred (see the
design doc's "prod hardening / stretch" section).

Sync bridge: the MCP SDK is async and the investigation workers are threads, so
we run one persistent asyncio loop on a background daemon thread and marshal
each blocking call onto it with run_coroutine_threadsafe.

# ponytail: one persistent background loop (created lazily), but a FRESH HTTP
# session per call. The event-loop churn is the expensive part `asyncio.run`
# per call would cause; a fresh session per call is cheap enough for a
# verification worker's handful of calls. Long-lived pooled sessions per server
# only matter under sustained throughput — deferred.
"""
import asyncio
import threading

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="mcp-loop", daemon=True).start()
        return _loop


def _run(coro, timeout: float = 30.0):
    """Run an async coroutine on the background loop and block for the result."""
    fut = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    return fut.result(timeout)


# ── async primitives (open a fresh session per call) ────────────────────────

async def _alist_tools(url: str, api_key: str | None) -> list[dict]:
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            resp = await session.list_tools()
            return [
                {"name": t.name,
                 "description": t.description or "",
                 "input_schema": t.inputSchema or {"type": "object", "properties": {}}}
                for t in resp.tools
            ]


async def _acall_tool(url: str, api_key: str | None, name: str, args: dict | None) -> str:
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments=args or {})
            return _content_to_text(result)


def _content_to_text(result) -> str:
    """Flatten a CallToolResult's content blocks to plain text."""
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        parts.append(text if text is not None else str(block))
    return "\n".join(parts).strip() or "(empty result)"


# ── config lookup (tool_config table) ───────────────────────────────────────

def _server(name: str) -> dict | None:
    try:
        from common.db import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT url, api_key FROM tool_config "
                "WHERE name=? AND enabled=1 AND kind='mcp_server' LIMIT 1",
                (name,)).fetchone()
        finally:
            conn.close()
        if not row or not row["url"]:
            return None
        return {"url": row["url"], "api_key": row["api_key"] or None}
    except Exception:
        return None


def enabled_servers() -> list[dict]:
    """All enabled MCP servers: [{name, url, api_key}]. Empty on any error."""
    try:
        from common.db import get_connection
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT name, url, api_key FROM tool_config "
                "WHERE enabled=1 AND kind='mcp_server' AND url IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
        return [{"name": r["name"], "url": r["url"], "api_key": r["api_key"] or None}
                for r in rows]
    except Exception:
        return []


# ── public sync API ─────────────────────────────────────────────────────────

def list_tools_sync(server_name: str) -> list[dict] | None:
    """Tool schemas for a configured server, or None (unconfigured / failed)."""
    srv = _server(server_name)
    if not srv:
        return None
    try:
        return _run(_alist_tools(srv["url"], srv["api_key"]))
    except Exception:
        return None


def call_tool_sync(server_name: str, tool_name: str, args: dict | None = None):
    """Call a tool on a configured server. None if unconfigured;
    {"error": ...} on call failure; text string on success."""
    srv = _server(server_name)
    if not srv:
        return None
    try:
        return _run(_acall_tool(srv["url"], srv["api_key"], tool_name, args))
    except Exception as e:
        return {"error": f"mcp call failed: {e}"}


def probe(url: str, api_key: str | None) -> tuple[bool, "list[dict] | str"]:
    """Explicit-URL connectivity test for the Tools view (no saved row needed).
    Returns (True, tool_list) or (False, "<ErrorType>: <msg>")."""
    try:
        return True, _run(_alist_tools(url, api_key or None), timeout=20)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


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
    try:
        read, write = await stack.enter_async_context(stdio_client(
            StdioServerParameters(command="uvx", args=args, env={**_os.environ, **env})))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
    except Exception:
        await stack.aclose()
        raise
    return session, stack


async def _aembedded_session(name: str, params: dict):
    # ponytail: check-then-set is not atomic; two concurrent first-callers for
    # the same name both spawn, the loser's session leaks. Acceptable given
    # single-worker-per-server usage; add a per-name asyncio.Lock if contention
    # becomes real.
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


if __name__ == "__main__":
    servers = enabled_servers()
    if not servers:
        print("mcp_client: not configured (no enabled MCP servers in tool_config)")
    else:
        for s in servers:
            ok, res = probe(s["url"], s["api_key"])
            if ok:
                print(f"mcp_client: {s['name']} OK — tools: {[t['name'] for t in res]}")
            else:
                print(f"mcp_client: {s['name']} FAILED — {res}")
    for name in EMBEDDED_SERVERS:
        p = embedded_params(name)
        if not p:
            print(f"mcp_client: {name} not configured (local fallback)")
        else:
            tools = list_embedded_tools(name)
            print(f"mcp_client: {name} — "
                  + (f"OK, tools: {[t['name'] for t in tools]}" if tools else "FAILED to connect"))
