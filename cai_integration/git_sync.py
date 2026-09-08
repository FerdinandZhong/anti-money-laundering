#!/usr/bin/env python3
"""
Git sync job for the AML Investigation Platform CML deployment.

Root job in the CML job chain (see cai_integration/jobs_config.yaml):
    git_sync -> install -> generate -> features -> train

Pulls the latest code from the project's git remote into the CML project
working directory so every deploy runs against current code, then lets CML
auto-trigger the dependent install job.

The CML project is created from a git template, so the project working
directory (default /home/cdsw) is itself the git clone.

Env vars:
    GIT_SYNC_DIR     repo dir to sync (default: this script's directory's parent)
    GIT_SYNC_BRANCH  branch to reset to (default: main)
"""

import os
import subprocess


def _repo_dir() -> str:
    # CML runs job scripts in an IPython-style engine where __file__ is not
    # defined. CML clones the project's git repo directly into /home/cdsw and
    # runs jobs from there.
    if os.environ.get("GIT_SYNC_DIR"):
        return os.environ["GIT_SYNC_DIR"]
    try:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        for cand in ("/home/cdsw", os.getcwd()):
            if os.path.isdir(os.path.join(cand, ".git")):
                return cand
        return "/home/cdsw"


REPO_DIR = _repo_dir()
BRANCH = os.environ.get("GIT_SYNC_BRANCH", "main")


def run(cmd) -> bool:
    print(f"Running: {cmd}  (cwd={REPO_DIR})")
    result = subprocess.run(cmd, shell=True, cwd=REPO_DIR, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            print(f"Error output: {result.stderr}")
        return False
    return True


def main() -> None:
    print("=" * 70)
    print("AML Investigation Platform — Git Sync")
    print("=" * 70)
    print(f"Repo dir: {REPO_DIR}")
    print(f"Branch:   {BRANCH}")

    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        # Not fatal: a freshly cloned project is already up to date.
        print(f"{REPO_DIR} is not a git repository — nothing to sync.")
        return

    # fetch + hard reset so local matches the remote branch exactly,
    # discarding any drift in the project working copy.
    if not run("git fetch origin --prune"):
        raise RuntimeError("git fetch failed")
    if not run(f"git reset --hard origin/{BRANCH}"):
        raise RuntimeError(f"git reset to origin/{BRANCH} failed")

    run("git rev-parse --short HEAD")
    print("Git sync complete.")


# CML runs jobs in an IPython engine that treats ANY SystemExit (even
# sys.exit(0)) as a job failure. Never sys.exit() here: return normally on
# success, raise on failure to mark the job failed. No __main__ guard needed —
# CML never sets __name__ == "__main__" — but keep it for local runs.
main()
