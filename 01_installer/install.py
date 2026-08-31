"""Install all dependencies: Python packages, Node.js/npm, and frontend build."""

import subprocess
import sys
import os
import shutil
import json
import urllib.request

try:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    # __file__ is not defined in interactive environments (e.g. CML notebook sessions)
    PROJECT_ROOT = os.getcwd()


def install_python_deps():
    """Install Python dependencies from requirements.txt."""
    req_file = os.path.join(PROJECT_ROOT, "requirements.txt")

    print("=" * 50)
    print("Installing Python dependencies...")
    print("=" * 50)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", req_file],
    )
    print("Python dependencies installed.\n")


def get_latest_node_lts_major():
    """Fetch the latest Node.js LTS major version number from the official release API."""
    try:
        url = "https://nodejs.org/dist/index.json"
        with urllib.request.urlopen(url, timeout=15) as resp:
            releases = json.loads(resp.read().decode())
        for release in releases:
            if release.get("lts"):
                major = release["version"].lstrip("v").split(".")[0]
                print(f"Latest Node.js LTS: {release['version']} ({release['lts']})")
                return major
    except Exception as e:
        print(f"Warning: could not fetch latest Node.js version ({e}), defaulting to 22.")
    return "22"


def install_nodejs():
    """Install Node.js and npm via nvm if not already available."""
    print("=" * 50)
    print("Checking Node.js / npm...")
    print("=" * 50)

    nvm_dir = os.environ.get("NVM_DIR", os.path.expanduser("~/.nvm"))
    nvm_sh = os.path.join(nvm_dir, "nvm.sh")

    def run_with_nvm(cmd):
        """Run a command with nvm sourced."""
        return subprocess.check_output(
            ["bash", "-c", f'. "{nvm_sh}" && {cmd}'],
            text=True,
        ).strip()

    node_ok = shutil.which("node") is not None
    npm_ok = shutil.which("npm") is not None

    if not node_ok and os.path.isfile(nvm_sh):
        try:
            run_with_nvm("node --version")
            node_ok = npm_ok = True
        except Exception:
            pass

    if node_ok and npm_ok:
        try:
            node_ver = subprocess.check_output(["node", "--version"], text=True).strip()
            npm_ver = subprocess.check_output(["npm", "--version"], text=True).strip()
        except FileNotFoundError:
            node_ver = run_with_nvm("node --version")
            npm_ver = run_with_nvm("npm --version")
        print(f"Node.js {node_ver} and npm {npm_ver} already installed.")
        return

    node_major = get_latest_node_lts_major()
    print(f"Node.js/npm not found. Installing Node.js {node_major}.x via nvm...")

    if not os.path.isfile(nvm_sh):
        print("Installing nvm...")
        subprocess.check_call(
            ["bash", "-c", "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.4/install.sh | bash"],
        )
        if not os.path.isfile(nvm_sh):
            print("ERROR: nvm installation failed.")
            print("Please install Node.js manually: https://nodejs.org/")
            sys.exit(1)

    try:
        run_with_nvm(f"nvm install {node_major}")
        node_ver = run_with_nvm("node --version")
        npm_ver = run_with_nvm("npm --version")
        print(f"Node.js {node_ver} and npm {npm_ver} installed via nvm.")
    except Exception as e:
        print(f"Could not install Node.js via nvm: {e}")
        print("Please install Node.js manually: https://nodejs.org/")
        sys.exit(1)


def run_npm(args, cwd=None):
    """Run an npm command, sourcing nvm first if npm isn't on the system PATH."""
    if shutil.which("npm"):
        subprocess.check_call(["npm"] + args, cwd=cwd)
    else:
        nvm_dir = os.environ.get("NVM_DIR", os.path.expanduser("~/.nvm"))
        nvm_sh = os.path.join(nvm_dir, "nvm.sh")
        cmd = "npm " + " ".join(args)
        subprocess.check_call(["bash", "-c", f'. "{nvm_sh}" && {cmd}'], cwd=cwd)


def install_frontend():
    """Install npm dependencies and build the React frontend."""
    frontend_dir = os.path.join(PROJECT_ROOT, "03_application", "frontend")
    pkg_json = os.path.join(frontend_dir, "package.json")

    if not os.path.isfile(pkg_json):
        print("WARNING: Frontend package.json not found, skipping frontend build.")
        return

    print("=" * 50)
    print("Installing frontend dependencies...")
    print("=" * 50)
    run_npm(["ci"], cwd=frontend_dir)

    print("\nBuilding frontend...")
    run_npm(["run", "build"], cwd=frontend_dir)
    print("Frontend built successfully.\n")


def create_directories():
    """Ensure data and model directories exist."""
    for d in ["data/raw", "data/processed", "models", "models/registry"]:
        path = os.path.join(PROJECT_ROOT, d)
        os.makedirs(path, exist_ok=True)
        print(f"  Directory ready: {d}")


def validate_resources():
    """Quick resource check."""
    print("=" * 50)
    print("Resource Validation")
    print("=" * 50)
    print(f"CPUs available: {os.cpu_count()}")
    disk = shutil.disk_usage(PROJECT_ROOT)
    print(f"Disk: {disk.free / (1024**3):.1f} GB free of {disk.total / (1024**3):.1f} GB")
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            print(f"GPU: {result.stdout.strip()}")
        else:
            print("GPU: None detected (CPU-only mode)")
    except FileNotFoundError:
        print("GPU: nvidia-smi not found (CPU-only mode)")
    print()


def main():
    validate_resources()

    print("=" * 50)
    print("Creating directories...")
    print("=" * 50)
    create_directories()
    print()

    install_python_deps()
    install_nodejs()
    install_frontend()

    print("=" * 50)
    print("Installation complete!")
    print("=" * 50)
    print()
    print("Next steps:")
    print("  1. Copy config: cp config/config.yaml.example config/config.yaml")
    print("     Then set your CAII endpoint in config/config.yaml")
    print("  2. Build data and model (first run only):")
    print("       python3 02_backend/data_generation/generate_synthetic_data.py")
    print("       python3 02_backend/data_pipeline/feature_engineering.py")
    print("       python3 02_backend/model_serving/train.py")
    print("  3. Start the app:   python3 start_app.py")


if __name__ == "__main__":
    main()
