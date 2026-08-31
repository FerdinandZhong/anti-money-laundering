"""Start both the FastAPI backend and the React frontend for the AML Platform."""

import os
import sys
import subprocess
import signal
import time

try:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
except NameError:
    PROJECT_ROOT = os.getcwd()

BACKEND_PORT = int(os.environ.get("BACKEND_PORT", 7078))
FRONTEND_PORT = int(os.environ.get("CDSW_APP_PORT", os.environ.get("FRONTEND_PORT", 8100)))

processes = []


def cleanup(signum=None, frame=None):
    print("\nShutting down...")
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
    for proc in processes:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def main():
    # Check prerequisites — warn but don't block
    db_path = os.path.join(PROJECT_ROOT, "data", "aml.db")
    models_dir = os.path.join(PROJECT_ROOT, "models")
    model_present = any(
        f.endswith(".json") or f.endswith(".ubj")
        for f in os.listdir(models_dir)
        if os.path.isfile(os.path.join(models_dir, f))
    ) if os.path.isdir(models_dir) else False

    if not os.path.exists(db_path) or not model_present:
        print("WARNING: Database or trained model not found.")
        print("  Build them first by running, in order:")
        print("    python3 02_backend/data_generation/generate_synthetic_data.py")
        print("    python3 02_backend/data_pipeline/feature_engineering.py")
        print("    python3 02_backend/model_serving/train.py")
        print()

    env = os.environ.copy()
    env["BACKEND_PORT"] = str(BACKEND_PORT)
    env["FRONTEND_PORT"] = str(FRONTEND_PORT)

    # Start backend
    print(f"Starting backend on port {BACKEND_PORT}...")
    backend = subprocess.Popen(
        [sys.executable, os.path.join(PROJECT_ROOT, "02_backend", "start_backend.py")],
        env=env,
        cwd=PROJECT_ROOT,
    )
    processes.append(backend)

    # Give backend a moment to bind
    time.sleep(2)

    # Start frontend (prod if dist/ exists, else dev)
    dist_dir = os.path.join(PROJECT_ROOT, "03_frontend", "dist")
    if os.path.isdir(dist_dir):
        print(f"Starting frontend (production) on port {FRONTEND_PORT}...")
        mode = "prod"
    else:
        print(f"Starting frontend (dev) on port {FRONTEND_PORT}...")
        mode = "dev"

    frontend = subprocess.Popen(
        [sys.executable, os.path.join(PROJECT_ROOT, "03_frontend", "start_frontend.py"), mode],
        env=env,
        cwd=PROJECT_ROOT,
    )
    processes.append(frontend)

    print()
    print("=" * 55)
    print(f"  Backend API:        http://localhost:{BACKEND_PORT}/api")
    print(f"  Investigator UI:    http://localhost:{FRONTEND_PORT}/investigation")
    print(f"  Model Ops UI:       http://localhost:{FRONTEND_PORT}/modelops")
    print("=" * 55)
    print("Press Ctrl+C to stop both services.")
    print()

    # Wait for either process to exit
    while True:
        for proc in processes:
            ret = proc.poll()
            if ret is not None:
                print(f"Process exited with code {ret}")
                cleanup()
        time.sleep(1)


if __name__ == "__main__":
    main()
