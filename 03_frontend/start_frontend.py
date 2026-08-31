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
    from fastapi.responses import FileResponse, Response, JSONResponse

    app = FastAPI(title="AML Investigation Platform")

    backend_port = _env_int("BACKEND_PORT", default=7078)
    backend_url = f"http://127.0.0.1:{backend_port}"
    _start_backend(backend_port)

    client = httpx.AsyncClient(base_url=backend_url, timeout=120.0, follow_redirects=True)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def proxy_api(path: str, request: Request):
        url = f"/api/{path}"
        if request.url.query:
            url = f"{url}?{request.url.query}"
        body = await request.body()
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ("host", "content-length")}
        resp = await client.request(request.method, url, content=body, headers=headers)
        _hop_by_hop = {"content-length", "transfer-encoding", "connection",
                       "keep-alive", "content-encoding", "upgrade"}
        response_headers = {k: v for k, v in resp.headers.items()
                            if k.lower() not in _hop_by_hop}
        return Response(content=resp.content, status_code=resp.status_code,
                        headers=response_headers)

    @app.get("/api/health-proxy")
    async def health_proxy():
        return {"frontend": "ok", "backend_url": backend_url}

    # Static assets
    assets_dir = os.path.join(DIST_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    dist_root = os.path.realpath(DIST_DIR)

    @app.get("/{full_path:path}")
    async def serve_react(full_path: str):
        file_path = os.path.realpath(os.path.join(dist_root, full_path))
        if file_path.startswith(dist_root + os.sep) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(dist_root, "index.html"))

    host = "127.0.0.1" if os.path.expanduser("~") == "/home/cdsw" else "0.0.0.0"
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
    host = "127.0.0.1" if os.path.expanduser("~") == "/home/cdsw" else "0.0.0.0"
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
