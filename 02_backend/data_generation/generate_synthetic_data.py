import sys
import os
import random
import uuid
import datetime
import json

try:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except NameError:
    # __file__ is not defined in interactive environments (e.g. CML notebook sessions)
    PROJECT_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

from common.db import init_db, get_connection
from common.config import get_config
from data_generation.schema import init_schema

random.seed(42)

# H3 demo lift (docs/superpowers/specs/2026-09-06-preflight-hardening-design.md):
# this many of the seeded structuring transactions start is_suspicious=0 despite
# being genuinely part of the pattern, so the first-trained model under-learns
# them. An analyst correcting the labels via the tx-label UI then retraining
# produces a real, visible PR-AUC delta instead of a flat metric across runs.
STRUCTURING_UNDERLABELED_N = 30

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:12].upper()


def _ts(days_ago: float = 0, hours_ago: float = 0) -> str:
    dt = datetime.datetime.now() - datetime.timedelta(days=days_ago, hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _date(days_ago: int = 0) -> str:
    return (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()


def _ip() -> str:
    return f"{random.randint(1,254)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"


# ---------------------------------------------------------------------------
# Generation functions
# ---------------------------------------------------------------------------

INDUSTRIES = ["RETAIL", "SME_TRADING", "SME_SERVICES", "SME_MANUFACTURING", "CORPORATE"]
REGIONS = ["SG", "MY", "HK", "CN", "ID"]
OCCUPATIONS = ["SALARIED", "SELF_EMPLOYED", "BUSINESS_OWNER", "DIRECTOR", "TREASURER"]
RISK_RATINGS = ["LOW", "MEDIUM", "HIGH"]


def gen_customers(n: int) -> list[dict]:
    rows = []
    n_suspicious = max(1, int(n * 0.01))
    n_normal = n - n_suspicious - 1  # -1 for Nightfall

    # Nightfall anchor customer
    rows.append({
        "customer_id": "CUST-NIGHTFALL-001",
        "name": "Nova Trading Pte. Ltd.",
        "industry": "ELECTRONICS_WHOLESALE",
        "occupation": "DIRECTOR",
        "risk_rating": "MEDIUM",
        "expected_monthly_turnover": 280000.0,
        "region": "SG",
        "country": "SG",
        "account_age_days": 45,
        "beneficial_owner": "Zhang Wei",
        "kyc_last_updated": _date(45),
    })

    # Normal customers
    for i in range(n_normal):
        industry = random.choice(INDUSTRIES)
        if industry == "RETAIL":
            turnover = random.uniform(3000, 15000)
        elif industry.startswith("SME"):
            turnover = random.uniform(50000, 500000)
        else:
            turnover = random.uniform(500000, 5000000)
        rows.append({
            "customer_id": f"CUST-{i:06d}",
            "name": f"Customer_{i:04d}" if industry == "RETAIL" else f"Corp_{i:04d} Pte. Ltd.",
            "industry": industry,
            "occupation": random.choice(OCCUPATIONS),
            "risk_rating": random.choices(["LOW", "MEDIUM", "HIGH"], weights=[70, 25, 5])[0],
            "expected_monthly_turnover": round(turnover, 2),
            "region": random.choice(REGIONS),
            "country": "SG",
            "account_age_days": random.randint(90, 3650),
            "beneficial_owner": f"Owner_{i:04d}",
            "kyc_last_updated": _date(random.randint(30, 365)),
        })

    # Suspicious/mule customers
    for i in range(n_suspicious):
        rows.append({
            "customer_id": f"CUST-MULE-{i:04d}",
            "name": f"Mule_Corp_{i:04d} Pte. Ltd.",
            "industry": random.choice(["SME_TRADING", "SME_SERVICES"]),
            "occupation": "DIRECTOR",
            "risk_rating": "HIGH",
            "expected_monthly_turnover": round(random.uniform(100000, 500000), 2),
            "region": random.choice(REGIONS),
            "country": "SG",
            "account_age_days": random.randint(30, 60),
            "beneficial_owner": f"Mule_Owner_{i:04d}",
            "kyc_last_updated": _date(random.randint(30, 60)),
        })

    return rows


def gen_accounts(customers: list[dict], n_accounts: int) -> list[dict]:
    rows = []

    # Nightfall main account
    rows.append({
        "account_id": "ACC-NIGHTFALL-001",
        "customer_id": "CUST-NIGHTFALL-001",
        "account_type": "CURRENT",
        "status": "ACTIVE",
        "opening_date": _date(45),
        "balance": 0.0,
        "currency": "SGD",
    })

    # 8 network accounts (linked by shared device or beneficiary)
    for i in range(1, 9):
        rows.append({
            "account_id": f"ACC-NETWORK-{i:03d}",
            "customer_id": f"CUST-MULE-{i-1:04d}",
            "account_type": "CURRENT",
            "status": "ACTIVE",
            "opening_date": _date(random.randint(30, 60)),
            "balance": 0.0,
            "currency": "SGD",
        })

    # Fill remaining accounts from normal customers
    normal_customers = [c for c in customers if not c["customer_id"].startswith("CUST-NIGHTFALL") and not c["customer_id"].startswith("CUST-MULE")]
    remaining = n_accounts - 9
    acc_idx = 0
    for cust in normal_customers[:remaining]:
        rows.append({
            "account_id": f"ACC-{acc_idx:07d}",
            "customer_id": cust["customer_id"],
            "account_type": random.choice(["CURRENT", "SAVINGS", "CORPORATE"]),
            "status": random.choices(["ACTIVE", "DORMANT", "CLOSED"], weights=[90, 7, 3])[0],
            "opening_date": _date(cust["account_age_days"]),
            "balance": round(random.uniform(0, 200000), 2),
            "currency": random.choices(["SGD", "USD", "HKD"], weights=[85, 10, 5])[0],
        })
        acc_idx += 1
        if acc_idx >= remaining:
            break

    return rows


def gen_devices(accounts: list[dict]) -> list[dict]:
    rows = []
    ring1 = "FP-NIGHTFALL-SHARED-001"
    ring2 = "FP-NIGHTFALL-SHARED-002"

    for acc in accounts:
        aid = acc["account_id"]
        if aid in ("ACC-NIGHTFALL-001", "ACC-NETWORK-001", "ACC-NETWORK-002",
                   "ACC-NETWORK-003", "ACC-NETWORK-004"):
            fp = ring1
        elif aid in ("ACC-NETWORK-005", "ACC-NETWORK-006", "ACC-NETWORK-007", "ACC-NETWORK-008"):
            fp = ring2
        else:
            fp = f"FP-{_uid()}"

        rows.append({
            "device_id": f"DEV-{_uid()}",
            "account_id": aid,
            "device_fingerprint": fp,
            "ip_address": _ip(),
            "login_time": _ts(random.uniform(0, 30)),
        })
        # Some accounts have a second device
        if random.random() < 0.3 and not aid.startswith("ACC-NIGHTFALL") and not aid.startswith("ACC-NETWORK"):
            rows.append({
                "device_id": f"DEV-{_uid()}",
                "account_id": aid,
                "device_fingerprint": f"FP-{_uid()}",
                "ip_address": _ip(),
                "login_time": _ts(random.uniform(0, 30)),
            })

    return rows


MERCHANTS = ["FairPrice", "Grab", "McDonald's", "Starbucks", "ComfortDelGro", "SP Group", "Singtel", "Amazon SG"]
BILL_REFS = ["UTILITIES", "TELCO", "INSURANCE", "SUBSCRIPTION"]
B2B_REFS = ["INV-{}", "PO-{}", "CONTRACT-{}"]


def gen_normal_transactions(accounts: list[dict], n: int) -> list[dict]:
    rows = []
    active_accs = [a["account_id"] for a in accounts if a["status"] == "ACTIVE"
                   and not a["account_id"].startswith("ACC-NIGHTFALL")
                   and not a["account_id"].startswith("ACC-NETWORK")]

    if not active_accs:
        return rows

    for _ in range(n):
        acc = random.choice(active_accs)
        tx_type = random.choices(
            ["salary", "bill", "merchant", "b2b", "remittance"],
            weights=[10, 20, 45, 15, 10]
        )[0]

        days_ago = random.uniform(0, 90)

        if tx_type == "salary":
            rows.append({
                "transaction_id": f"TX-{_uid()}",
                "from_account_id": None,
                "to_account_id": acc,
                "amount": round(random.uniform(3000, 15000), 2),
                "currency": "SGD",
                "channel": "FAST",
                "direction": "INBOUND",
                "counterparty_name": f"Employer_{random.randint(1,200)} Pte. Ltd.",
                "counterparty_country": "SG",
                "event_time": _ts(days_ago),
                "mcc": None,
                "reference": "SALARY",
                "is_suspicious": 0,
                "typology": None,
            })
        elif tx_type == "bill":
            rows.append({
                "transaction_id": f"TX-{_uid()}",
                "from_account_id": acc,
                "to_account_id": None,
                "amount": round(random.uniform(50, 500), 2),
                "currency": "SGD",
                "channel": "GIRO",
                "direction": "OUTBOUND",
                "counterparty_name": random.choice(["SP Group", "Singtel", "StarHub", "M1"]),
                "counterparty_country": "SG",
                "event_time": _ts(days_ago),
                "mcc": "4900",
                "reference": random.choice(BILL_REFS),
                "is_suspicious": 0,
                "typology": None,
            })
        elif tx_type == "merchant":
            rows.append({
                "transaction_id": f"TX-{_uid()}",
                "from_account_id": acc,
                "to_account_id": None,
                "amount": round(random.uniform(5, 500), 2),
                "currency": "SGD",
                "channel": random.choice(["PAYNOW", "NETS", "VISA"]),
                "direction": "OUTBOUND",
                "counterparty_name": random.choice(MERCHANTS),
                "counterparty_country": "SG",
                "event_time": _ts(days_ago),
                "mcc": random.choice(["5411", "5812", "4121", "5999"]),
                "reference": "PURCHASE",
                "is_suspicious": 0,
                "typology": None,
            })
        elif tx_type == "b2b":
            ref_tmpl = random.choice(B2B_REFS)
            rows.append({
                "transaction_id": f"TX-{_uid()}",
                "from_account_id": acc,
                "to_account_id": None,
                "amount": round(random.uniform(5000, 200000), 2),
                "currency": "SGD",
                "channel": "FAST",
                "direction": "OUTBOUND",
                "counterparty_name": f"Supplier_{random.randint(1,500)} Pte. Ltd.",
                "counterparty_country": random.choice(["SG", "MY", "CN"]),
                "event_time": _ts(days_ago),
                "mcc": None,
                "reference": ref_tmpl.format(random.randint(1000, 9999)),
                "is_suspicious": 0,
                "typology": None,
            })
        else:  # remittance
            rows.append({
                "transaction_id": f"TX-{_uid()}",
                "from_account_id": acc,
                "to_account_id": None,
                "amount": round(random.uniform(500, 10000), 2),
                "currency": "SGD",
                "channel": "SWIFT",
                "direction": "OUTBOUND",
                "counterparty_name": f"Family_{random.randint(1,200)}",
                "counterparty_country": random.choice(["MY", "CN", "ID", "PH", "IN"]),
                "event_time": _ts(days_ago),
                "mcc": None,
                "reference": "FAMILY REMITTANCE",
                "is_suspicious": 0,
                "typology": None,
            })

    return rows


def gen_nightfall_transactions(accounts: list[dict]) -> list[dict]:
    rows = []
    # Yesterday's date as base (T+00:00)
    base = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=1)

    all_acc_ids = [a["account_id"] for a in accounts
                   if a["account_id"] != "ACC-NIGHTFALL-001"]
    # Use network accounts + some normal accounts as senders
    sender_pool = [f"ACC-NETWORK-{i:03d}" for i in range(1, 9)]
    normal_pool = [a for a in all_acc_ids if not a.startswith("ACC-NETWORK")]
    sender_pool += random.sample(normal_pool, min(29, len(normal_pool)))
    random.shuffle(sender_pool)

    # 46 inbound over ~24 hours, totaling ~1,260,000
    n_inbound = 46
    target_total = 1_260_000
    amounts = []
    for i in range(n_inbound):
        if i < n_inbound - 1:
            amt = round(random.uniform(15000, 40000), 2)
            amounts.append(amt)
        else:
            # Last one makes up the rest (capped to range)
            remainder = target_total - sum(amounts)
            amt = max(15000, min(40000, round(remainder, 2)))
            amounts.append(amt)

    for i in range(n_inbound):
        minutes_offset = (24 * 60 / n_inbound) * i  # spread across 24h
        event_time = (base + datetime.timedelta(minutes=minutes_offset)).strftime("%Y-%m-%dT%H:%M:%S")
        sender = sender_pool[i % len(sender_pool)]
        rows.append({
            "transaction_id": f"TX-NF-IN-{i:03d}",
            "from_account_id": sender,
            "to_account_id": "ACC-NIGHTFALL-001",
            "amount": amounts[i],
            "currency": "SGD",
            "channel": random.choice(["FAST", "PAYNOW"]),
            "direction": "INBOUND",
            "counterparty_name": f"Sender_{i:03d}",
            "counterparty_country": "SG",
            "event_time": event_time,
            "mcc": None,
            "reference": f"TRANSFER {_uid()}",
            "is_suspicious": 1,
            "typology": "MULE_FUNNEL",
        })

    # 3 outbound SWIFT at T+00:30
    outbound_time = (base + datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
    out_amt = round(sum(amounts) * 0.92 / 3, 2)
    beneficiaries = [
        ("Oversea Beneficiary 1 Ltd", "CN"),
        ("Oversea Beneficiary 2 Ltd", "MY"),
        ("Oversea Beneficiary 3 Ltd", "AE"),
    ]
    for i, (bene_name, bene_country) in enumerate(beneficiaries):
        rows.append({
            "transaction_id": f"TX-NF-OUT-{i:03d}",
            "from_account_id": "ACC-NIGHTFALL-001",
            "to_account_id": None,
            "amount": out_amt,
            "currency": "SGD",
            "channel": "SWIFT",
            "direction": "OUTBOUND",
            "counterparty_name": bene_name,
            "counterparty_country": bene_country,
            "event_time": outbound_time,
            "mcc": None,
            "reference": f"SWIFT-{_uid()}",
            "is_suspicious": 1,
            "typology": "MULE_FUNNEL",
        })

    return rows


def gen_structuring_transactions(accounts: list[dict]) -> list[dict]:
    """Structuring typology: many just-under-threshold transfers from one
    account. A subset (STRUCTURING_UNDERLABELED_N) is seeded with
    is_suspicious=0 despite being genuinely part of the pattern — simulating
    a synthetic ground-truth gap the model under-learns from on first train.
    An analyst tagging those transactions suspicious (existing tx-label UI)
    and retraining is the demo's before/after PR-AUC lift; see H3 design spec.
    """
    rows = []
    active = [a["account_id"] for a in accounts
              if a["status"] == "ACTIVE"
              and not a["account_id"].startswith("ACC-NIGHTFALL")
              and not a["account_id"].startswith("ACC-NETWORK")]
    if not active:
        return rows

    struct_acc = random.choice(active)
    n = random.randint(50, 100)
    n_underlabeled = min(STRUCTURING_UNDERLABELED_N, n)
    for i in range(n):
        days_ago = random.uniform(0, 3)
        rows.append({
            "transaction_id": f"TX-STR-{i:04d}",
            "from_account_id": struct_acc,
            "to_account_id": None,
            "amount": round(random.uniform(45000, 49500), 2),
            "currency": "SGD",
            "channel": "FAST",
            "direction": "OUTBOUND",
            "counterparty_name": f"Recipient_{_uid()}",
            "counterparty_country": random.choice(["SG", "MY"]),
            "event_time": _ts(days_ago),
            "mcc": None,
            "reference": f"TRANSFER {_uid()}",
            "is_suspicious": 0 if i < n_underlabeled else 1,
            "typology": "STRUCTURING",
        })
    return rows


def gen_hard_negatives(accounts: list[dict]) -> list[dict]:
    rows = []
    active = [a["account_id"] for a in accounts
              if a["status"] == "ACTIVE"
              and not a["account_id"].startswith("ACC-NIGHTFALL")
              and not a["account_id"].startswith("ACC-NETWORK")]
    if not active:
        return rows

    # Large property purchase
    acc = random.choice(active)
    rows.append({
        "transaction_id": f"TX-HN-PROP-001",
        "from_account_id": acc,
        "to_account_id": None,
        "amount": round(random.uniform(800000, 1200000), 2),
        "currency": "SGD",
        "channel": "SWIFT",
        "direction": "OUTBOUND",
        "counterparty_name": "SLA Property Registry",
        "counterparty_country": "SG",
        "event_time": _ts(random.uniform(5, 30)),
        "mcc": "6552",
        "reference": "PROPERTY PURCHASE",
        "is_suspicious": 0,
        "typology": None,
    })

    # Corporate treasury sweeps (100-200 rows of large round amounts)
    corp_accs = [a["account_id"] for a in accounts if a["account_type"] == "CORPORATE" and a["status"] == "ACTIVE"]
    if len(corp_accs) < 2:
        corp_accs = random.sample(active, min(2, len(active)))

    n_sweeps = random.randint(100, 200)
    for i in range(n_sweeps):
        src, dst = random.sample(corp_accs, 2) if len(corp_accs) >= 2 else (corp_accs[0], None)
        rows.append({
            "transaction_id": f"TX-HN-SWEEP-{i:04d}",
            "from_account_id": src,
            "to_account_id": dst,
            "amount": round(random.choice([100000, 200000, 500000, 1000000]) * random.uniform(0.9, 1.1), 2),
            "currency": "SGD",
            "channel": "FAST",
            "direction": "OUTBOUND",
            "counterparty_name": f"Group Entity_{i:03d} Pte. Ltd.",
            "counterparty_country": "SG",
            "event_time": _ts(random.uniform(0, 30)),
            "mcc": None,
            "reference": f"INTERCO SWEEP {_uid()}",
            "is_suspicious": 0,
            "typology": None,
        })

    return rows


def gen_alerts() -> list[dict]:
    # No hand-seeded alerts — the scorer flags accounts (incl. Nightfall)
    # from real transaction risk on first score_transactions() run.
    return []


def gen_cases() -> list[dict]:
    # No hand-seeded cases — cases are created when alerts are first opened.
    return []


def gen_annotations() -> list[dict]:
    rows = []
    # 499 historical labels, ~70% SUSPICIOUS / 30% FALSE_POSITIVE
    dispositions = ["SUSPICIOUS"] * 349 + ["FALSE_POSITIVE"] * 150
    random.shuffle(dispositions)
    # Dummy case pool for historical annotations
    dummy_cases = [f"CASE-HIST-{i:04d}" for i in range(50)]
    for i, disp in enumerate(dispositions):
        rows.append({
            "annotation_id": f"ANN-HIST-{i:04d}",
            "case_id": dummy_cases[i % len(dummy_cases)],
            "disposition": disp,
            "reason_codes": '["HISTORICAL"]',
            "notes": "Historical adjudication",
            "adjudicator": "system",
            "evidence_version": "v0",
        })
    return rows


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

def insert_customers(conn, rows):
    conn.executemany(
        "INSERT OR IGNORE INTO customers (customer_id,name,industry,occupation,risk_rating,"
        "expected_monthly_turnover,region,country,account_age_days,beneficial_owner,kyc_last_updated) "
        "VALUES (:customer_id,:name,:industry,:occupation,:risk_rating,:expected_monthly_turnover,"
        ":region,:country,:account_age_days,:beneficial_owner,:kyc_last_updated)",
        rows,
    )


def insert_accounts(conn, rows):
    conn.executemany(
        "INSERT OR IGNORE INTO accounts (account_id,customer_id,account_type,status,opening_date,balance,currency) "
        "VALUES (:account_id,:customer_id,:account_type,:status,:opening_date,:balance,:currency)",
        rows,
    )


def insert_devices(conn, rows):
    conn.executemany(
        "INSERT OR IGNORE INTO devices (device_id,account_id,device_fingerprint,ip_address,login_time) "
        "VALUES (:device_id,:account_id,:device_fingerprint,:ip_address,:login_time)",
        rows,
    )


def insert_transactions(conn, rows):
    conn.executemany(
        "INSERT OR IGNORE INTO transactions (transaction_id,from_account_id,to_account_id,amount,currency,"
        "channel,direction,counterparty_name,counterparty_country,event_time,mcc,reference,is_suspicious,typology) "
        "VALUES (:transaction_id,:from_account_id,:to_account_id,:amount,:currency,:channel,:direction,"
        ":counterparty_name,:counterparty_country,:event_time,:mcc,:reference,:is_suspicious,:typology)",
        rows,
    )


def insert_alerts(conn, rows):
    conn.executemany(
        "INSERT OR IGNORE INTO alerts (alert_id,customer_id,account_id,triggered_rules,risk_score,risk_band,"
        "reason_codes,top_features,model_version,status,sla_deadline) "
        "VALUES (:alert_id,:customer_id,:account_id,:triggered_rules,:risk_score,:risk_band,"
        ":reason_codes,:top_features,:model_version,:status,:sla_deadline)",
        rows,
    )


def insert_cases(conn, rows):
    conn.executemany(
        "INSERT OR IGNORE INTO cases (case_id,alert_id,customer_id,state,assignee,priority) "
        "VALUES (:case_id,:alert_id,:customer_id,:state,:assignee,:priority)",
        rows,
    )


def insert_annotations(conn, rows):
    conn.executemany(
        "INSERT OR IGNORE INTO annotations (annotation_id,case_id,disposition,reason_codes,notes,adjudicator,evidence_version) "
        "VALUES (:annotation_id,:case_id,:disposition,:reason_codes,:notes,:adjudicator,:evidence_version)",
        rows,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cfg = get_config()
    data_cfg = cfg.get("data", {})
    n_customers = data_cfg.get("n_customers", 2000)
    n_accounts = data_cfg.get("n_accounts", 3000)
    n_transactions = data_cfg.get("n_transactions", 100000)

    # Ensure DB and schema exist
    init_db()
    conn = get_connection()
    conn.execute("PRAGMA foreign_keys=OFF")  # bulk inserts happen out of FK order

    print("Generating customers...")
    customers = gen_customers(n_customers)
    insert_customers(conn, customers)
    conn.commit()

    print("Generating accounts...")
    accounts = gen_accounts(customers, n_accounts)
    insert_accounts(conn, accounts)
    conn.commit()

    print("Generating devices...")
    devices = gen_devices(accounts)
    insert_devices(conn, devices)
    conn.commit()

    print(f"Generating {n_transactions} normal transactions...")
    normal_txs = gen_normal_transactions(accounts, n_transactions)
    batch = 1000
    for i in range(0, len(normal_txs), batch):
        insert_transactions(conn, normal_txs[i:i+batch])
    conn.commit()

    print("Injecting Nightfall typology...")
    nf_txs = gen_nightfall_transactions(accounts)
    insert_transactions(conn, nf_txs)
    conn.commit()

    print("Injecting structuring typology...")
    str_txs = gen_structuring_transactions(accounts)
    insert_transactions(conn, str_txs)
    conn.commit()

    print("Generating hard negatives...")
    hn_txs = gen_hard_negatives(accounts)
    insert_transactions(conn, hn_txs)
    conn.commit()

    print("Creating alerts...")
    alert_rows = gen_alerts()
    insert_alerts(conn, alert_rows)
    conn.commit()

    print("Creating cases...")
    case_rows = gen_cases()
    insert_cases(conn, case_rows)
    conn.commit()

    # No hand-seeded model_runs/deployments row here: a fake "v1.0.0" run with
    # no on-disk artifact (pr_auc=0.847, never trained) was exactly the bug
    # H3 fixes — scorer.py/get_model_explanation silently fell back to the
    # newest artifact because the champion pointer never matched a real train
    # run. Run `python 02_backend/scripts/export_source_csv.py` then
    # `python -m ml.train` (from 02_backend/) next; train.py's __main__ now
    # promotes the freshly trained version to CHAMPION itself.
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()

    n_tx = len(normal_txs) + len(nf_txs) + len(str_txs) + len(hn_txs)
    print(f"\nGenerated: {len(customers)} customers, {len(accounts)} accounts, {n_tx} transactions")
    print(f"Alerts: {len(alert_rows)}, Cases: {len(case_rows)}")

    # Export the source tables to CSV so the source abstraction (common/source.py)
    # can read them when Impala is unavailable (e.g. CML). The CML job chain has no
    # separate export step, so fold it in here — otherwise Feature Engineering / Train
    # fail with "CSV source missing". Idempotent; a live Impala warehouse ignores it.
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend", "scripts"))
    import export_source_csv
    export_source_csv.main()


if __name__ == "__main__":
    main()
