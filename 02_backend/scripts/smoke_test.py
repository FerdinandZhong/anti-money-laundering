"""Smoke test for the CAI pipeline changes — run locally before deploying.

Exercises the demo-critical paths against a TEMP COPY of data/aml.db (never
mutates the real DB or models):
  1. config falls back to config.yaml.example when config.yaml is absent
  2. LLM client is built with a finite timeout (no hang on a dead endpoint)
  3. run_scoring populates an empty alert queue (top-N), and is idempotent by account
  4. scorer still fills the queue with a weak model (composite floor fallback)
  5. the CML job chain wiring: train -> score -> launch, launch is keep-alive

Usage:  python 02_backend/scripts/smoke_test.py
Exit 0 = all green.
"""
import os
import sys
import shutil
import sqlite3
import tempfile

try:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except NameError:
    PROJECT_ROOT = os.getcwd()
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

PASS, FAIL = "PASS", "FAIL"
_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond), detail))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    import common.config as cfg
    import common.db as db

    # 1. config fallback to example
    import tempfile as _tf
    d = _tf.mkdtemp()
    os.makedirs(os.path.join(d, "config"))
    shutil.copy(os.path.join(PROJECT_ROOT, "config", "config.yaml.example"),
                os.path.join(d, "config", "config.yaml.example"))
    _orig_root, cfg.PROJECT_ROOT, cfg._config = cfg.PROJECT_ROOT, d, None
    conf = cfg.get_config()
    check("config falls back to config.yaml.example", isinstance(conf, dict) and "model" in conf)
    cfg.PROJECT_ROOT, cfg._config = _orig_root, None

    # 2. LLM client finite timeout
    import agents.llm_client as lc
    lc.set_endpoint("https://10.255.255.1:9/v1", "dummy")
    client, _ = lc._make_client()
    check("LLM client has finite timeout (no hang)", getattr(client, "timeout", None) == 20 and client.max_retries == 0,
          f"timeout={getattr(client,'timeout',None)} retries={client.max_retries}")

    # temp DB copy with an empty alert queue (mimics a fresh CML deploy)
    real_db = cfg.get_db_path.__wrapped__() if hasattr(cfg.get_db_path, "__wrapped__") else os.path.join(PROJECT_ROOT, "data", "aml.db")
    if not os.path.exists(real_db):
        check("data/aml.db present (run generate first)", False, real_db)
        return _summary()
    dbp = os.path.join(d, "aml.db")
    shutil.copy(real_db, dbp)
    c = sqlite3.connect(dbp); c.execute("DELETE FROM alerts"); c.commit(); c.close()
    cfg._config = None
    cfg.get_db_path = lambda: dbp
    db.get_db_path = cfg.get_db_path
    import ml.scorer as sc
    sc.PROJECT_ROOT = PROJECT_ROOT  # models/ live here

    # 3. run_scoring populates queue + idempotent by account
    conn = db.get_connection()
    created = sc.score_transactions(conn)
    n_open = conn.execute("SELECT COUNT(*) FROM alerts WHERE status='OPEN'").fetchone()[0]
    n_scores = conn.execute("SELECT COUNT(*) FROM transaction_scores").fetchone()[0]
    check("scoring fills the queue (1..20 OPEN)", 0 < n_open <= 20, f"created={created} open={n_open}")
    check("transaction_scores populated", n_scores > 0, f"rows={n_scores}")
    same = sc.score_transactions(conn)  # rerun: must not re-flag already-OPEN accounts
    open2 = conn.execute("SELECT COUNT(*) FROM alerts WHERE status='OPEN' AND account_id IN "
                         "(SELECT account_id FROM alerts WHERE status='OPEN')").fetchone()[0]
    check("scoring dedupes by account on rerun (no duplicate open account)",
          open2 == conn.execute("SELECT COUNT(DISTINCT account_id) FROM alerts WHERE status='OPEN'").fetchone()[0])
    conn.close()

    # 4. weak-model floor fallback
    c = sqlite3.connect(dbp); c.execute("DELETE FROM alerts"); c.commit(); c.close()
    import numpy as np, xgboost as xgb
    _orig = xgb.XGBClassifier
    class _Weak:
        def load_model(self, *a, **k): pass
        def predict_proba(self, X):
            p = np.full(len(X), 0.10)
            return np.column_stack([1 - p, p])
    xgb.XGBClassifier = _Weak
    conn = db.get_connection()
    sc.score_transactions(conn)
    weak_open = conn.execute("SELECT COUNT(*) FROM alerts WHERE status='OPEN'").fetchone()[0]
    conn.close()
    xgb.XGBClassifier = _orig
    check("weak model still fills queue via composite fallback", weak_open == 20, f"open={weak_open}")

    # 5. job-chain wiring
    import yaml
    jobs = yaml.safe_load(open(os.path.join(PROJECT_ROOT, "cai_integration", "jobs_config.yaml")))["jobs"]
    check("chain order train->score->launch",
          jobs["score"]["parent_job_key"] == "train" and jobs["launch"]["parent_job_key"] == "score",
          f"score<-{jobs['score']['parent_job_key']} launch<-{jobs['launch']['parent_job_key']}")
    check("score job runs run_scoring.py", jobs["score"]["script"].endswith("run_scoring.py"))
    check("launch job timeout raised for keep-alive", jobs["launch"]["timeout"] >= 3600, f"timeout={jobs['launch']['timeout']}")

    shutil.rmtree(d, ignore_errors=True)
    return _summary()


def _summary() -> int:
    ok = all(r[1] for r in _results)
    print("\n" + ("ALL GREEN" if ok else "FAILURES: " + ", ".join(n for n, p, _ in _results if not p)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
