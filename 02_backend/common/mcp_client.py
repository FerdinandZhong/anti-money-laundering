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
