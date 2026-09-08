"""Source (reference) data access — the read-only bank data.

Backend is Impala/Iceberg in prod, local CSV as fallback when Impala is
unreachable. NO SQLite for source data. Operational state (alerts/cases/
evidence/annotations/model registry) lives in the ops store (see common/db.py),
not here.

Config (config.yaml):
    source:
      backend: auto        # auto | impala | csv
      csv_dir: data/raw
      impala:
        host: ...
        port: 443
        http_path: <datahub>/cdp-proxy-api/impala
        user: qzhong
        database: default
        # password from $IMPALA_PASSWORD or ~/tokens/workload_password

`auto` tries Impala (with a short TCP preflight) and falls back to CSV. The
resolved backend is decided once per process and logged.
"""
import json
import os
import socket

import pandas as pd

from common.config import get_config, PROJECT_ROOT

SOURCE_TABLES = ["customers", "accounts", "transactions", "devices"]

_backend: str | None = None
_impala_conn = None
_csv_cache: dict[str, pd.DataFrame] = {}


# ── backend resolution ────────────────────────────────────────────────────

def _source_cfg() -> dict:
    return get_config().get("source", {}) or {}


def _impala_password() -> str:
    pw = os.environ.get("IMPALA_PASSWORD")
    if pw:
        return pw.strip()
    token = os.path.expanduser("~/tokens/workload_password")
    if os.path.exists(token):
        with open(token) as f:
            return f.read().strip()
    return ""


def _try_impala():
    """Return a live impyla connection, or None if unavailable/unreachable."""
    imp = _source_cfg().get("impala") or {}
    host = imp.get("host")
    if not host:
        return None
    port = int(imp.get("port", 443))
    # Hard-bounded TCP preflight so we fail fast to CSV instead of hanging.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(float(imp.get("connect_timeout", 6)))
    try:
        s.connect((host, port))
    except OSError as e:
        print(f"[source] Impala {host}:{port} unreachable ({e}); using CSV fallback")
        return None
    finally:
        s.close()
    try:
        from impala.dbapi import connect
        conn = connect(
            host=host, port=port,
            http_path=imp.get("http_path", "cdp-proxy-api/impala"),
            use_http_transport=True, use_ssl=True,
            auth_mechanism=imp.get("auth_mechanism", "LDAP"),
            user=imp.get("user"), password=_impala_password(),
            database=imp.get("database", "default"),
            timeout=int(imp.get("query_timeout", 60)),
        )
        conn.cursor().execute("SELECT 1")
        # Verify tables actually exist in this DB — SELECT 1 alone passes even when they don't
        conn.cursor().execute("SELECT 1 FROM customers LIMIT 1")
        print(f"[source] Impala connected: {host} db={imp.get('database', 'default')}")
        return conn
    except Exception as e:  # noqa: BLE001
        print(f"[source] Impala connect failed ({type(e).__name__}: {e}); using CSV fallback")
        return None


def backend() -> str:
    """Resolve the source backend once ('impala' or 'csv')."""
    global _backend, _impala_conn
    if _backend is not None:
        return _backend
    want = _source_cfg().get("backend", "auto")
    if want == "csv":
        _backend = "csv"
    else:
        _impala_conn = _try_impala()
        if _impala_conn is not None:
            _backend = "impala"
        elif want == "impala":
            raise RuntimeError("source.backend=impala but Impala is unreachable")
        else:
            _backend = "csv"
    return _backend


# ── query helpers ─────────────────────────────────────────────────────────

def _csv(table: str) -> pd.DataFrame:
    if table not in _csv_cache:
        csv_dir = os.path.join(PROJECT_ROOT, _source_cfg().get("csv_dir", "data/raw"))
        path = os.path.join(csv_dir, f"{table}.csv")
        if not os.path.exists(path):
            raise RuntimeError(
                f"CSV source missing: {path}. Run 02_backend/scripts/export_source_csv.py"
            )
        _csv_cache[table] = pd.read_csv(path, low_memory=False)
    return _csv_cache[table]


def _impala_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    # impyla paramstyle is pyformat -> use %s placeholders in the SQL passed here.
    return pd.read_sql(sql, _impala_conn, params=params or None)


def _records(df: pd.DataFrame) -> list[dict]:
    """Rows as JSON-native dicts (no numpy scalar types, NaN -> None)."""
    return json.loads(df.to_json(orient="records"))


# ── source accessors (return DataFrame or list[dict]) ─────────────────────

def transactions_features_df(with_customer_id: bool = False) -> pd.DataFrame:
    """tx ⋈ accounts ⋈ customers, base columns for feature engineering."""
    cols = [
        "transaction_id", "from_account_id", "amount", "channel",
        "counterparty_country", "event_time", "is_suspicious",
        "risk_rating", "account_age_days", "expected_monthly_turnover",
    ]
    if with_customer_id:
        cols.append("customer_id")

    if backend() == "impala":
        sel = ("t.transaction_id, t.from_account_id, t.amount, t.channel, "
               "t.counterparty_country, t.event_time, t.is_suspicious, "
               "c.risk_rating, c.account_age_days, c.expected_monthly_turnover"
               + (", a.customer_id" if with_customer_id else ""))
        return _impala_df(
            f"SELECT {sel} FROM transactions t "
            "LEFT JOIN accounts a ON t.from_account_id = a.account_id "
            "LEFT JOIN customers c ON a.customer_id = c.customer_id"
        )

    tx = _csv("transactions")[
        ["transaction_id", "from_account_id", "amount", "channel",
         "counterparty_country", "event_time", "is_suspicious"]
    ]
    acc = _csv("accounts")[["account_id", "customer_id"]]
    cust = _csv("customers")[
        ["customer_id", "risk_rating", "account_age_days", "expected_monthly_turnover"]
    ]
    m = tx.merge(acc, left_on="from_account_id", right_on="account_id", how="left")
    m = m.merge(cust, on="customer_id", how="left")
    return m[cols]


def devices_df() -> pd.DataFrame:
    if backend() == "impala":
        return _impala_df("SELECT account_id, device_fingerprint FROM devices")
    return _csv("devices")[["account_id", "device_fingerprint"]].copy()


def get_customer(customer_id: str) -> dict | None:
    if backend() == "impala":
        df = _impala_df("SELECT * FROM customers WHERE customer_id = %s", (customer_id,))
    else:
        df = _csv("customers")
        df = df[df["customer_id"] == customer_id]
    rows = _records(df)
    return rows[0] if rows else None


def get_accounts(customer_id: str) -> list[dict]:
    if backend() == "impala":
        df = _impala_df("SELECT * FROM accounts WHERE customer_id = %s", (customer_id,))
    else:
        df = _csv("accounts")
        df = df[df["customer_id"] == customer_id]
    return _records(df)


def get_account(account_id: str) -> dict | None:
    if backend() == "impala":
        df = _impala_df("SELECT * FROM accounts WHERE account_id = %s", (account_id,))
    else:
        df = _csv("accounts")
        df = df[df["account_id"] == account_id]
    rows = _records(df)
    return rows[0] if rows else None


def customer_transactions(customer_id: str, limit: int = 20) -> list[dict]:
    """Recent transactions across the customer's accounts (by from_account_id)."""
    if backend() == "impala":
        df = _impala_df(
            "SELECT t.* FROM transactions t "
            "JOIN accounts a ON t.from_account_id = a.account_id "
            "WHERE a.customer_id = %s ORDER BY t.event_time DESC LIMIT %s",
            (customer_id, limit),
        )
        return _records(df)
    acc_ids = set(_csv("accounts").query("customer_id == @customer_id")["account_id"])
    tx = _csv("transactions")
    tx = tx[tx["from_account_id"].isin(acc_ids)].sort_values("event_time", ascending=False).head(limit)
    return _records(tx)


def account_transactions(account_id: str, limit: int = 50) -> list[dict]:
    if backend() == "impala":
        df = _impala_df(
            "SELECT * FROM transactions WHERE from_account_id = %s OR to_account_id = %s "
            "ORDER BY event_time DESC LIMIT %s",
            (account_id, account_id, limit),
        )
        return _records(df)
    tx = _csv("transactions")
    tx = tx[(tx["from_account_id"] == account_id) | (tx["to_account_id"] == account_id)]
    tx = tx.sort_values("event_time", ascending=False).head(limit)
    return _records(tx)


def device_fingerprints(account_id: str) -> list[str]:
    if backend() == "impala":
        df = _impala_df(
            "SELECT DISTINCT device_fingerprint FROM devices "
            "WHERE account_id = %s AND device_fingerprint IS NOT NULL",
            (account_id,),
        )
        return [x for x in df["device_fingerprint"].tolist() if x]
    dev = _csv("devices")
    fps = dev[dev["account_id"] == account_id]["device_fingerprint"].dropna().unique()
    return [str(x) for x in fps]


def accounts_by_fingerprints(fps: list[str]) -> list[str]:
    if not fps:
        return []
    if backend() == "impala":
        ph = ",".join(["%s"] * len(fps))
        df = _impala_df(
            f"SELECT DISTINCT account_id FROM devices "
            f"WHERE device_fingerprint IN ({ph}) AND account_id IS NOT NULL",
            tuple(fps),
        )
        return [x for x in df["account_id"].tolist() if x]
    dev = _csv("devices")
    ids = dev[dev["device_fingerprint"].isin(fps)]["account_id"].dropna().unique()
    return [str(x) for x in ids]


def devices_by_fingerprints(fps: list[str], exclude_account: str) -> list[dict]:
    if not fps:
        return []
    if backend() == "impala":
        ph = ",".join(["%s"] * len(fps))
        df = _impala_df(
            f"SELECT account_id, device_fingerprint, ip_address FROM devices "
            f"WHERE device_fingerprint IN ({ph}) AND account_id != %s",
            tuple(fps) + (exclude_account,),
        )
        return _records(df)
    dev = _csv("devices")
    m = dev[dev["device_fingerprint"].isin(fps) & (dev["account_id"] != exclude_account)]
    return _records(m[["account_id", "device_fingerprint", "ip_address"]])


_suspicious_count: int | None = None


def count_suspicious() -> int:
    """COUNT of source transactions flagged is_suspicious=1. Cached per-process
    so /api/stats doesn't rescan the full transactions table on every call."""
    global _suspicious_count
    if _suspicious_count is not None:
        return _suspicious_count
    try:
        if backend() == "impala":
            df = _impala_df("SELECT COUNT(*) AS n FROM transactions WHERE is_suspicious = 1")
            _suspicious_count = int(df["n"].iloc[0])
        else:
            tx = _csv("transactions")
            _suspicious_count = int((tx["is_suspicious"] == 1).sum())
    except Exception as e:  # noqa: BLE001
        print(f"[source] count_suspicious failed ({type(e).__name__}: {e}); returning 0")
        _suspicious_count = 0
    return _suspicious_count


_total_count: int | None = None


def count_transactions() -> int:
    """COUNT(*) of all source transactions. Cached per-process, same pattern as
    count_suspicious()."""
    global _total_count
    if _total_count is not None:
        return _total_count
    try:
        if backend() == "impala":
            df = _impala_df("SELECT COUNT(*) AS n FROM transactions")
            _total_count = int(df["n"].iloc[0])
        else:
            _total_count = len(_csv("transactions"))
    except Exception as e:  # noqa: BLE001
        print(f"[source] count_transactions failed ({type(e).__name__}: {e}); returning 0")
        _total_count = 0
    return _total_count


if __name__ == "__main__":
    # Self-check: exercises the CSV fallback path end-to-end.
    print("backend:", backend())
    feat = transactions_features_df(with_customer_id=True)
    assert len(feat) > 0 and "customer_id" in feat.columns, "features frame empty/missing col"
    assert set(["transaction_id", "risk_rating"]).issubset(feat.columns)
    dev = devices_df()
    assert {"account_id", "device_fingerprint"}.issubset(dev.columns)
    print(f"features rows={len(feat)} devices rows={len(dev)}  OK")


def fund_flow_edges(transactions: list[dict], root_account_id: str) -> list[dict]:
    """Aggregate a transaction list into directional fund-flow edges centered on
    root_account_id. INBOUND -> (from_account_id -> root); OUTBOUND -> (root ->
    to_account_id or counterparty_name). Pure: no I/O. Fail-soft on [] -> []."""
    agg: dict[tuple[str, str], dict] = {}
    for t in transactions:
        direction = (t.get("direction") or "").upper()
        amount = float(t.get("amount") or 0.0)
        if direction == "INBOUND":
            src = t.get("from_account_id") or t.get("counterparty_name") or "unknown"
            dst = root_account_id
        else:  # OUTBOUND (default)
            src = root_account_id
            dst = t.get("to_account_id") or t.get("counterparty_name") or "unknown"
        if not src or not dst or src == dst:
            continue
        key = (src, dst)
        e = agg.setdefault(key, {"source": src, "target": dst, "relation": "fund_flow",
                                 "amount": 0.0, "count": 0})
        e["amount"] = round(e["amount"] + amount, 2)
        e["count"] += 1
    return list(agg.values())
