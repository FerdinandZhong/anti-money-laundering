"""Impala/Iceberg connectivity smoke test (run OUTSIDE the sandbox, from a
network that is allow-listed on the CDP environment).

Usage:
    python 02_backend/scripts/impala_smoke.py [http_path]

Reads password from $IMPALA_PASSWORD or ~/tokens/workload_password.
Prints the first http_path that authenticates and runs SELECT 1.

check_connectivity() is the callable form (tries each candidate http_path,
returns structured results) — reusable by other health checks without
shelling out to this script.
"""
import os
import socket
import sys

HOST = os.environ.get("IMPALA_HOST", "qzhong-datahub-gateway.qzhong-a.a465-9q4k.cloudera.site")
PORT = int(os.environ.get("IMPALA_PORT", "443"))
USER = os.environ.get("IMPALA_USER", "qzhong")
DB = os.environ.get("IMPALA_DATABASE", "default")

# CDP DataHub Impala sits behind Knox; http_path is <datahub>/cdp-proxy-api/impala.
CANDIDATE_PATHS = [
    "qzhong-datahub/cdp-proxy-api/impala",
    "qzhong/cdp-proxy-api/impala",
    "cdp-proxy-api/impala",
]


def _password() -> str:
    pw = os.environ.get("IMPALA_PASSWORD")
    if pw:
        return pw.strip()
    with open(os.path.expanduser("~/tokens/workload_password")) as f:
        return f.read().strip()


def _preflight(host: str, port: int, timeout: float = 6) -> tuple[bool, str]:
    """Hard-bounded TCP check so we fail fast instead of hanging on a blocked port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True, ""
    except OSError as e:
        return False, str(e)
    finally:
        s.close()


def check_connectivity(
    host: str = HOST, port: int = PORT, user: str = USER, database: str = DB,
    candidate_paths: list[str] | None = None,
) -> dict:
    """Run the same preflight + multi-path auth probe as the CLI, returning a
    structured result instead of printing. Never raises — every failure mode
    (unreachable, bad creds, wrong http_path) becomes {"ok": False, ...}.
    """
    ok, err = _preflight(host, port)
    if not ok:
        return {"ok": False, "stage": "tcp_preflight", "message": err, "http_path": None}

    from impala.dbapi import connect  # imported after preflight to keep failure fast

    try:
        pw = _password()
    except FileNotFoundError as e:
        return {"ok": False, "stage": "password", "message": str(e), "http_path": None}

    attempts = []
    for hp in candidate_paths or CANDIDATE_PATHS:
        try:
            conn = connect(
                host=host, port=port, http_path=hp, use_http_transport=True,
                use_ssl=True, auth_mechanism="LDAP", user=user, password=pw,
                database=database, timeout=15,
            )
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            conn.close()
            return {"ok": True, "stage": "connected", "message": "", "http_path": hp}
        except Exception as e:  # noqa: BLE001 - report and try next path
            attempts.append(f"{hp}: {type(e).__name__}: {str(e).splitlines()[0][:140]}")
    return {"ok": False, "stage": "auth", "message": "; ".join(attempts), "http_path": None}


def main() -> int:
    paths = [sys.argv[1]] if len(sys.argv) > 1 else None
    result = check_connectivity(candidate_paths=paths)
    if result["ok"]:
        print(f"OK  http_path={result['http_path']!r}")
        return 0
    if result["stage"] == "tcp_preflight":
        print(f"[preflight] TCP {HOST}:{PORT} unreachable: {result['message']}")
        print("  -> gateway is likely IP-allow-listed; run from an allow-listed network.")
        return 2
    print(f"FAIL {result['stage']}: {result['message']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
