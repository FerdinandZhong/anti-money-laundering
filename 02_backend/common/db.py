import sqlite3
import os
from common.config import get_db_path

_TRANSACTION_SCORES_SQL = """
CREATE TABLE IF NOT EXISTS transaction_scores (
    transaction_id TEXT PRIMARY KEY,
    account_id TEXT,
    score REAL NOT NULL,
    model_version TEXT,
    scored_at TEXT DEFAULT (datetime('now'))
);
"""

_TRANSACTION_LABELS_SQL = """
CREATE TABLE IF NOT EXISTS transaction_labels (
    transaction_id TEXT PRIMARY KEY,
    label INTEGER NOT NULL,
    case_id TEXT REFERENCES cases(case_id),
    labeled_by TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_LLM_MODELS_SQL = """
CREATE TABLE IF NOT EXISTS llm_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT UNIQUE NOT NULL,
    provider TEXT NOT NULL,
    model_identifier TEXT NOT NULL,
    api_base TEXT,
    api_key TEXT,
    is_active INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_STATUS_BACKFILL_SQL = """
UPDATE alerts SET status =
  CASE (SELECT disposition FROM cases WHERE cases.alert_id = alerts.alert_id)
    WHEN 'SUSPICIOUS'      THEN 'PROPOSED'
    WHEN 'FALSE_POSITIVE'  THEN 'CLOSED'
    WHEN 'NEEDS_MORE_INFO' THEN 'PENDING'
  END
WHERE status = 'OPEN'
  AND alert_id IN (SELECT alert_id FROM cases WHERE state = 'CLOSED');
"""

_TOOL_CONFIG_SQL = """
CREATE TABLE IF NOT EXISTS tool_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'mcp_server',
    name TEXT UNIQUE NOT NULL,
    transport TEXT NOT NULL DEFAULT 'http',
    url TEXT,
    api_key TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def get_connection() -> sqlite3.Connection:
    path = get_db_path()
    if not os.path.exists(path):
        raise RuntimeError(f"Database file not found: {path}. Run init_db() first.")
    # check_same_thread=False: FastAPI runs sync endpoints in a threadpool, so a
    # per-request connection may be used on a different worker thread than it was
    # created on. Each request still gets its own conn via get_db, so this is safe.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # ponytail: heals pre-existing local DBs created before these tables existed;
    # drop once every dev DB has been regenerated via init_db().
    conn.execute(_TRANSACTION_SCORES_SQL)
    conn.execute(_TRANSACTION_LABELS_SQL)
    conn.execute(_LLM_MODELS_SQL)
    conn.execute(_TOOL_CONFIG_SQL)
    for col in ("analysis TEXT", "analyzed_at TEXT", "disposition TEXT"):
        try:
            conn.execute(f"ALTER TABLE cases ADD COLUMN {col}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    for col in ("params TEXT",):
        try:
            conn.execute(f"ALTER TABLE tool_config ADD COLUMN {col}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    # account_id lets the alert detail fetch an account's top-scoring transactions
    # directly (per-account tx counts can be huge, so an IN(all-tx-ids) query is
    # not viable). Heals DBs scored before this column existed.
    for col in ("account_id TEXT",):
        try:
            conn.execute(f"ALTER TABLE transaction_scores ADD COLUMN {col}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    # Part 1A: make the alert chronology explicit for existing databases. These
    # values are populated by the next scoring run; older alerts remain nullable
    # and the API derives sensible fallbacks from their transaction evidence.
    for col in (
        "scoring_run_at TEXT",
        "data_cutoff_at TEXT",
        "window_start_at TEXT",
        "pattern_start_at TEXT",
        "latest_contributing_at TEXT",
    ):
        try:
            conn.execute(f"ALTER TABLE alerts ADD COLUMN {col}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    # ponytail: runs on every connect; idempotent (WHERE status='OPEN' is a no-op once remapped)
    conn.execute(_STATUS_BACKFILL_SQL)
    conn.commit()
    return conn


def init_db() -> None:
    from data_generation.schema import init_schema
    path = get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_schema(conn)
    conn.close()
