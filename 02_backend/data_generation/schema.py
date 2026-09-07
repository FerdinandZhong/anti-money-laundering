import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT,
    occupation TEXT,
    risk_rating TEXT DEFAULT 'LOW',
    expected_monthly_turnover REAL,
    region TEXT,
    country TEXT DEFAULT 'SG',
    account_age_days INTEGER,
    beneficial_owner TEXT,
    kyc_last_updated TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    account_type TEXT DEFAULT 'CURRENT',
    status TEXT DEFAULT 'ACTIVE',
    opening_date TEXT,
    balance REAL DEFAULT 0.0,
    currency TEXT DEFAULT 'SGD',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    from_account_id TEXT REFERENCES accounts(account_id),
    to_account_id TEXT REFERENCES accounts(account_id),
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'SGD',
    channel TEXT DEFAULT 'FAST',
    direction TEXT DEFAULT 'OUTBOUND',
    counterparty_name TEXT,
    counterparty_country TEXT,
    event_time TEXT NOT NULL,
    mcc TEXT,
    reference TEXT,
    is_suspicious INTEGER DEFAULT 0,
    typology TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    account_id TEXT REFERENCES accounts(account_id),
    device_fingerprint TEXT,
    ip_address TEXT,
    login_time TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(customer_id),
    account_id TEXT REFERENCES accounts(account_id),
    triggered_rules TEXT,
    risk_score REAL,
    risk_band TEXT,
    reason_codes TEXT,
    top_features TEXT,
    model_version TEXT,
    status TEXT DEFAULT 'OPEN',
    sla_deadline TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    alert_id TEXT REFERENCES alerts(alert_id),
    customer_id TEXT REFERENCES customers(customer_id),
    state TEXT DEFAULT 'ALERT_CREATED',
    assignee TEXT,
    priority TEXT DEFAULT 'MEDIUM',
    analysis TEXT,
    analyzed_at TEXT,
    disposition TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    case_id TEXT REFERENCES cases(case_id),
    tool TEXT NOT NULL,
    query TEXT,
    payload_hash TEXT,
    data_version TEXT,
    agent_worker TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY,
    case_id TEXT REFERENCES cases(case_id),
    disposition TEXT NOT NULL,
    reason_codes TEXT,
    notes TEXT,
    adjudicator TEXT,
    evidence_version TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS model_runs (
    run_id TEXT PRIMARY KEY,
    dataset_version TEXT,
    feature_version TEXT,
    code_commit TEXT,
    model_version TEXT,
    status TEXT DEFAULT 'PENDING',
    metrics TEXT,
    approved_by TEXT,
    approval_time TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deployments (
    deployment_id TEXT PRIMARY KEY,
    model_version TEXT NOT NULL,
    environment TEXT DEFAULT 'production',
    traffic_pct REAL DEFAULT 0.0,
    status TEXT DEFAULT 'PENDING',
    approved_by TEXT,
    deployed_at TEXT,
    rolled_back_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transaction_scores (
    transaction_id TEXT PRIMARY KEY,
    score REAL NOT NULL,
    model_version TEXT,
    scored_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transaction_labels (
    transaction_id TEXT PRIMARY KEY,
    label INTEGER NOT NULL,          -- 1 = suspicious, 0 = clean (analyst verdict)
    case_id TEXT REFERENCES cases(case_id),
    labeled_by TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT UNIQUE NOT NULL,
    provider TEXT NOT NULL,          -- openai | openai_compatible | caii | vllm | ollama
    model_identifier TEXT NOT NULL,
    api_base TEXT,
    api_key TEXT,                    -- ponytail: plaintext for local demo; secret store in prod
    is_active INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

TABLE_NAMES: list[str] = [
    "customers",
    "accounts",
    "transactions",
    "devices",
    "alerts",
    "cases",
    "evidence",
    "annotations",
    "model_runs",
    "deployments",
    "transaction_scores",
    "transaction_labels",
    "llm_models",
]


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


if __name__ == "__main__":
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert len(tables) == 12, f"Expected 12 tables, got {len(tables)}"
    print(f"Schema OK — {len(tables)} tables created")
    conn.close()
