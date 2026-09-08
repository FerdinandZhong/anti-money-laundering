"""Export source (reference) tables to data/raw/*.csv — the local fallback the
app reads when Impala is unreachable. Bootstrap step for the demo: run once
after generating synthetic data.

Source tables only (customers, accounts, transactions, devices). Operational
tables (alerts/cases/evidence/annotations/model registry) stay in the ops store.

Usage:  python 02_backend/scripts/export_source_csv.py
"""
import sys
import os

try:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except NameError:
    # __file__ is not defined in interactive environments (e.g. CML notebook sessions)
    PROJECT_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import sqlite3
import pandas as pd
from common.config import get_config, get_db_path

SOURCE_TABLES = ["customers", "accounts", "transactions", "devices"]


def main() -> int:
    csv_dir = os.path.join(PROJECT_ROOT, get_config().get("source", {}).get("csv_dir", "data/raw"))
    os.makedirs(csv_dir, exist_ok=True)
    conn = sqlite3.connect(get_db_path())
    try:
        for t in SOURCE_TABLES:
            df = pd.read_sql_query(f"SELECT * FROM {t}", conn)
            out = os.path.join(csv_dir, f"{t}.csv")
            df.to_csv(out, index=False)
            print(f"[export] {t}: {len(df)} rows -> {out}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
