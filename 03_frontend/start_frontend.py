"""Launch the React frontend (dev or prod) with a co-located FastAPI backend.

Both services run in this single CML application: the FastAPI backend is started
as a co-located child process bound to localhost:BACKEND_PORT (7078 by default),
and the frontend reverse-proxies /api requests to it.  Keeping both in one app
avoids cross-app JWT/networking issues on CAI Workbench.
"""
import os
import sys
import time
import atexit
import subprocess

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(_HERE)
    FRONTEND_DIR = _HERE
except NameError:
    PROJECT_ROOT = os.getcwd()
    FRONTEND_DIR = os.path.join(PROJECT_ROOT, "03_frontend")

DIST_DIR = os.path.join(FRONTEND_DIR, "dist")


def _env_int(*names: str, default: int) -> int:
    for name in names:
        raw = os.environ.get(name)
        if raw is not None and raw.strip():
            try:
                return int(raw.strip())
            except ValueError:
                pass
    return default


def _bind_host() -> str:
    """CML Applications must listen on 127.0.0.1:$CDSW_APP_PORT — the Workbench proxy
    connects over loopback, so binding 0.0.0.0 leaves the app unreachable. Treat "on CML"
    as HOME==/home/cdsw OR CDSW_APP_PORT set (CML injects it for Applications); bind
    0.0.0.0 only for local runs so the dev box is reachable on the LAN."""
    on_cml = os.path.expanduser("~") == "/home/cdsw" or bool(os.environ.get("CDSW_APP_PORT"))
    return "127.0.0.1" if on_cml else "0.0.0.0"


_backend_proc: subprocess.Popen | None = None


def _stop_backend():
    global _backend_proc
    if _backend_proc and _backend_proc.poll() is None:
        _backend_proc.terminate()
        try:
            _backend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _backend_proc.kill()


def _wait_for_backend(port: int, timeout: float = 30.0):
    import urllib.request
    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    print("[backend] ready")
                    return
        except Exception:
            pass
        time.sleep(0.5)
    print("[backend] WARNING: readiness check timed out — continuing anyway")


def _start_backend(port: int):
    global _backend_proc
    env = os.environ.copy()
    env["BACKEND_PORT"] = str(port)
    env.pop("CDSW_APP_PORT", None)  # backend must not claim the public port
    backend_script = os.path.join(PROJECT_ROOT, "02_backend", "start_backend.py")
    print(f"Starting co-located backend on 127.0.0.1:{port} ...")
    _backend_proc = subprocess.Popen(
        [sys.executable, backend_script], env=env, cwd=PROJECT_ROOT,
    )
    atexit.register(_stop_backend)
    _wait_for_backend(port)


def serve_production():
    port = _env_int("FRONTEND_PORT", "CDSW_APP_PORT", default=8100)

    import asyncio
    import uvicorn
    import httpx
    from fastapi import FastAPI, Request
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, Response, JSONResponse, StreamingResponse

    app = FastAPI(title="AML Investigation Platform")

    backend_port = _env_int("BACKEND_PORT", default=7078)
    backend_url = f"http://127.0.0.1:{backend_port}"
    _start_backend(backend_port)

    # read=None: the /investigate and /model/retrain/stream endpoints are long-lived
    # SSE streams; a fixed read timeout would cut them off mid-run.
    client = httpx.AsyncClient(
        base_url=backend_url, follow_redirects=True,
        timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=10.0),
    )

    _HOP_BY_HOP = {"content-length", "transfer-encoding", "connection",
                   "keep-alive", "content-encoding", "upgrade"}

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def proxy_api(path: str, request: Request):
        url = f"/api/{path}"
        if request.url.query:
            url = f"{url}?{request.url.query}"
        body = await request.body()
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ("host", "content-length")}
        # Stream the upstream response through so SSE (chunked, long-lived) works
        # and never gets buffered — buffering broke with RemoteProtocolError.
        req = client.build_request(request.method, url, content=body, headers=headers)
        resp = await client.send(req, stream=True)
        response_headers = {k: v for k, v in resp.headers.items()
                            if k.lower() not in _HOP_BY_HOP}

        async def _stream():
            try:
                async for chunk in resp.aiter_raw():
                    yield chunk
            finally:
                await resp.aclose()

        return StreamingResponse(
            _stream(), status_code=resp.status_code, headers=response_headers,
            media_type=resp.headers.get("content-type"),
        )

    @app.get("/api/health-proxy")
    async def health_proxy():
        return {"frontend": "ok", "backend_url": backend_url}

    # Static assets
    assets_dir = os.path.join(DIST_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    dist_root = os.path.realpath(DIST_DIR)

    # index.html has no content hash in its URL, so browsers must always
    # revalidate it — otherwise a stale cached copy (with old asset hashes)
    # can be served indefinitely across normal reloads. /assets/* is safe to
    # cache aggressively since its filenames are content-hashed by Vite.
    _no_cache_headers = {"Cache-Control": "no-cache, must-revalidate"}

    @app.get("/{full_path:path}")
    async def serve_react(full_path: str):
        file_path = os.path.realpath(os.path.join(dist_root, full_path))
        if file_path.startswith(dist_root + os.sep) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(dist_root, "index.html"), headers=_no_cache_headers)

    host = _bind_host()
    print(f"Serving production build on {host}:{port}")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        loop.create_task(uvicorn.Server(uvicorn.Config(app, host=host, port=port)).serve())
    else:
        uvicorn.run(app, host=host, port=port)


def serve_dev():
    port = _env_int("FRONTEND_PORT", "CDSW_APP_PORT", default=8100)
    host = _bind_host()
    backend_port = _env_int("BACKEND_PORT", default=7078)
    _start_backend(backend_port)
    print(f"Starting Vite dev server on {host}:{port} (proxy → :{backend_port})")
    subprocess.run(
        ["npx", "vite", "--port", str(port), "--host", host],
        cwd=FRONTEND_DIR,
    )


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode == "dev":
        serve_dev()
    elif mode == "prod":
        serve_production()
    else:
        if os.path.isdir(DIST_DIR) and os.path.isfile(os.path.join(DIST_DIR, "index.html")):
            serve_production()
        else:
            serve_dev()


if __name__ == "__main__":
    main()
else:
    # CML Jupyter kernel mode
    main()
