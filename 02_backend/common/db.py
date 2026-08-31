import sqlite3
import os
from common.config import get_db_path


def get_connection() -> sqlite3.Connection:
    path = get_db_path()
    if not os.path.exists(path):
        raise RuntimeError(f"Database file not found: {path}. Run init_db() first.")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    from data_generation.schema import init_schema
    path = get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_schema(conn)
    conn.close()
