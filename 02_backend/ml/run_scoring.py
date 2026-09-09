"""CML Job: Score Transactions — populate the alert queue with the champion model.

Runs after Train in the chain (… -> train -> score -> launch) so the app comes up
with a ready, risk-ranked alert queue. Pure scoring: no training, no app launch.

Uses the promoted CHAMPION to score transactions and insert the top-N ALERT-ML
rows (see ml/scorer.py). Idempotent by account — re-running only surfaces new
accounts, never duplicates an already-open one.

CML runs job scripts in an IPython engine where __name__ != "__main__" and
sys.exit is treated as failure — so call main() unguarded and raise on error.
"""
import sys
import os

try:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except NameError:
    # __file__ is not defined in interactive environments (e.g. CML notebook sessions)
    PROJECT_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

from common.db import get_connection
from ml.scorer import score_transactions


def main() -> None:
    conn = get_connection()
    try:
        created = score_transactions(conn)
        total_open = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE status='OPEN'"
        ).fetchone()[0]
        print(f"[score] created {created} new alert(s); {total_open} OPEN in the queue")
    finally:
        conn.close()


# CML engine: unguarded call, no sys.exit.
main()
