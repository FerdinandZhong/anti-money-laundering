# Case Lifecycle Queues + Network Graph + Transaction Detail — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close dispositioned cases out of the Alert Queue into disposition-routed buckets, draw the mule-funnel network as an SVG graph on case open, and let analysts expand a transaction row for raw fields + derived typology flags.

**Architecture:** Three independent slices on branch `feat/tx-labels-and-caii-endpoints`. Backend: disposition drives `alerts.status`; a pure `fund_flow_edges` + richer `get_network_graph` and a pure `derive_tx_flags` are folded into `GET /api/alerts/{id}/detail`; an idempotent backfill runs in the self-heal seam. Frontend: a four-bucket segmented queue, a no-dependency layered-SVG `NetworkGraph`, and an inline expandable transaction row. Everything fails soft (unlinked account → single node; legacy DB → backfilled; clean row → no flags).

**Tech Stack:** Python 3.11 / FastAPI / SQLite / pytest (backend); React 19 / TypeScript / Tailwind / Vite (frontend, no test runner — `npm run build` = `tsc -b && vite build` is the typecheck gate).

## Global Constraints

- Branch: `feat/tx-labels-and-caii-endpoints`. Do not create new branches.
- **No new dependencies** (frontend or backend). SVG is hand-rolled like `WorkflowGraph.tsx`; no graph/physics/test-runner libs.
- **Fail-soft everywhere:** a missing/empty result returns the pre-change behavior, never an error.
- Backend tests use the `tmp_db_path` / `db_conn` fixtures in `02_backend/tests/conftest.py`. Run pytest from `02_backend/`.
- Money threshold for structuring in this dataset: **$50,000 SGD**; structuring rows are $45,000–49,500.
- Disposition values are exactly `SUSPICIOUS`, `FALSE_POSITIVE`, `NEEDS_MORE_INFO` (validated in `dispose_case`).
- Alert status values after this work: `OPEN` (default), `PROPOSED`, `PENDING`, `CLOSED`.
- Commit after every task with the shown message.

---

## File Structure

**Backend**
- `02_backend/api/main.py` — add `_DISPOSITION_TO_STATUS`, status update in `dispose_case`, `GET /api/alerts/counts`, and fold `network` + per-tx `flags` into `/detail`.
- `02_backend/common/db.py` — idempotent status backfill in `get_connection()`.
- `02_backend/common/source.py` — new pure `fund_flow_edges(transactions, root_account_id)`.
- `02_backend/common/tx_flags.py` — **new**, pure `derive_tx_flags(tx, all_txs)`.
- `02_backend/agents/tools.py` — richer `get_network_graph` (typed nodes + fund-flow edges).
- `02_backend/data_generation/generate_synthetic_data.py` — second shared-device ring.

**Frontend**
- `03_frontend/src/api.ts` — `NetworkNode`/`NetworkEdge`/`TxFlag` types, `network?` on `CaseDetail`, `flags?` on `Transaction`, `getAlertCounts`, widen queue status.
- `03_frontend/src/components/NetworkGraph.tsx` — **new**, layered SVG funnel.
- `03_frontend/src/components/AlertQueue.tsx` — bucket segmented control + counts.
- `03_frontend/src/components/CaseWorkbench.tsx` — render `NetworkGraph`, expandable tx row + flag chips, `onDisposed`, read-only-when-closed.
- `03_frontend/src/App.tsx` — wire `onDisposed` → queue reload.

---

## Task 1: Route disposition → alert status

**Files:**
- Modify: `02_backend/api/main.py` (`dispose_case`, ~line 229)
- Test: `02_backend/tests/test_dispose_status.py` (new)

**Interfaces:**
- Produces: `dispose_case` now also runs `UPDATE alerts SET status=? WHERE alert_id=(SELECT alert_id FROM cases WHERE case_id=?)` using `_DISPOSITION_TO_STATUS = {"SUSPICIOUS":"PROPOSED","FALSE_POSITIVE":"CLOSED","NEEDS_MORE_INFO":"PENDING"}`.

- [ ] **Step 1: Write the failing test**

```python
# 02_backend/tests/test_dispose_status.py
from datetime import datetime, timezone
from fastapi.testclient import TestClient


def _seed(conn):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO alerts (alert_id, customer_id, account_id, risk_score, risk_band, status, created_at) "
        "VALUES ('ALERT-1','CUST-1','ACC-1',0.9,'CRITICAL','OPEN',?)", (now,))
    conn.execute(
        "INSERT INTO cases (case_id, alert_id, customer_id, state, priority, created_at, updated_at) "
        "VALUES ('CASE-1','ALERT-1','CUST-1','ALERT_CREATED','CRITICAL',?,?)", (now, now))
    conn.commit()


def test_suspicious_moves_alert_to_proposed(tmp_db_path):
    from common.db import get_connection
    conn = get_connection(); _seed(conn)
    import api.main as main
    client = TestClient(main.app)
    r = client.post("/api/cases/CASE-1/dispose", json={"disposition": "SUSPICIOUS", "adjudicator": "jsmith"})
    assert r.status_code == 200
    status = get_connection().execute("SELECT status FROM alerts WHERE alert_id='ALERT-1'").fetchone()["status"]
    assert status == "PROPOSED"


def test_false_positive_closes_alert(tmp_db_path):
    from common.db import get_connection
    conn = get_connection(); _seed(conn)
    import api.main as main
    client = TestClient(main.app)
    client.post("/api/cases/CASE-1/dispose", json={"disposition": "FALSE_POSITIVE"})
    status = get_connection().execute("SELECT status FROM alerts WHERE alert_id='ALERT-1'").fetchone()["status"]
    assert status == "CLOSED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 02_backend && python -m pytest tests/test_dispose_status.py -v`
Expected: FAIL — `assert 'OPEN' == 'PROPOSED'` (status never updated today).

- [ ] **Step 3: Add the mapping + status update**

In `02_backend/api/main.py`, add the constant near the other module-level dicts (e.g. beside `_ALERT_SORTS`):

```python
_DISPOSITION_TO_STATUS = {
    "SUSPICIOUS": "PROPOSED",       # awaiting SAR/STR filing
    "FALSE_POSITIVE": "CLOSED",     # archived
    "NEEDS_MORE_INFO": "PENDING",   # stays visible, needs info
}
```

Inside `dispose_case`, right after the existing `UPDATE cases SET state='CLOSED' ...` statement and before `conn.commit()`:

```python
    conn.execute(
        "UPDATE alerts SET status = ? "
        "WHERE alert_id = (SELECT alert_id FROM cases WHERE case_id = ?)",
        (_DISPOSITION_TO_STATUS[body.disposition], case_id),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd 02_backend && python -m pytest tests/test_dispose_status.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add 02_backend/api/main.py 02_backend/tests/test_dispose_status.py
git commit -m "feat: disposition routes alert status (OPEN -> PROPOSED/PENDING/CLOSED)"
```

---

## Task 2: Idempotent alert-status backfill for legacy DBs

**Files:**
- Modify: `02_backend/common/db.py` (`get_connection`, after the `conn.execute(_*_SQL)` self-heal calls, ~line 67)
- Test: `02_backend/tests/test_status_backfill.py` (new)

**Interfaces:**
- Consumes: `_DISPOSITION_TO_STATUS` semantics from Task 1 (re-expressed as SQL here; keep the mapping identical).
- Produces: every `get_connection()` runs an idempotent `UPDATE alerts ...` that only rewrites `OPEN` alerts whose case is `CLOSED`.

- [ ] **Step 1: Write the failing test**

```python
# 02_backend/tests/test_status_backfill.py
def test_backfill_remaps_legacy_closed_alerts(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    # a closed case whose alert is still OPEN (legacy state before Task 1 existed)
    conn.execute("INSERT INTO alerts (alert_id, customer_id, status) VALUES ('A1','C1','OPEN')")
    conn.execute("INSERT INTO cases (case_id, alert_id, customer_id, state, disposition, created_at, updated_at) "
                 "VALUES ('K1','A1','C1','CLOSED','SUSPICIOUS','t','t')")
    # an untouched open alert with no case
    conn.execute("INSERT INTO alerts (alert_id, customer_id, status) VALUES ('A2','C2','OPEN')")
    conn.commit(); conn.close()

    conn2 = get_connection()  # backfill runs on connect
    assert conn2.execute("SELECT status FROM alerts WHERE alert_id='A1'").fetchone()["status"] == "PROPOSED"
    assert conn2.execute("SELECT status FROM alerts WHERE alert_id='A2'").fetchone()["status"] == "OPEN"


def test_backfill_is_idempotent(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    conn.execute("INSERT INTO alerts (alert_id, customer_id, status) VALUES ('A1','C1','OPEN')")
    conn.execute("INSERT INTO cases (case_id, alert_id, customer_id, state, disposition, created_at, updated_at) "
                 "VALUES ('K1','A1','C1','CLOSED','FALSE_POSITIVE','t','t')")
    conn.commit(); conn.close()
    s1 = get_connection().execute("SELECT status FROM alerts WHERE alert_id='A1'").fetchone()["status"]
    s2 = get_connection().execute("SELECT status FROM alerts WHERE alert_id='A1'").fetchone()["status"]
    assert s1 == s2 == "CLOSED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 02_backend && python -m pytest tests/test_status_backfill.py -v`
Expected: FAIL — `A1` is still `OPEN` (no backfill yet).

- [ ] **Step 3: Add the backfill SQL constant + call**

In `02_backend/common/db.py`, add near the other `_*_SQL` constants:

```python
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
```

In `get_connection()`, after the existing `conn.execute(_TOOL_CONFIG_SQL)` line, add:

```python
    conn.execute(_STATUS_BACKFILL_SQL)
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd 02_backend && python -m pytest tests/test_status_backfill.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add 02_backend/common/db.py 02_backend/tests/test_status_backfill.py
git commit -m "feat: idempotent alert-status backfill for legacy closed cases"
```

---

## Task 3: `GET /api/alerts/counts`

**Files:**
- Modify: `02_backend/api/main.py` (add endpoint after `list_alerts`, ~line 66)
- Test: `02_backend/tests/test_alert_counts.py` (new)

**Interfaces:**
- Produces: `GET /api/alerts/counts` → `{"counts": {"OPEN": int, "PROPOSED": int, "PENDING": int, "CLOSED": int}}` (all four keys always present, zero-filled).

- [ ] **Step 1: Write the failing test**

```python
# 02_backend/tests/test_alert_counts.py
from fastapi.testclient import TestClient


def test_counts_zero_filled_and_grouped(tmp_db_path):
    from common.db import get_connection
    conn = get_connection()
    for aid, st in [("A1","OPEN"), ("A2","OPEN"), ("A3","PROPOSED")]:
        conn.execute("INSERT INTO alerts (alert_id, customer_id, status) VALUES (?,?,?)", (aid, "C", st))
    conn.commit()
    import api.main as main
    r = TestClient(main.app).get("/api/alerts/counts")
    assert r.status_code == 200
    counts = r.json()["counts"]
    assert counts["OPEN"] == 2
    assert counts["PROPOSED"] == 1
    assert counts["PENDING"] == 0 and counts["CLOSED"] == 0  # zero-filled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 02_backend && python -m pytest tests/test_alert_counts.py -v`
Expected: FAIL — 404 (endpoint missing).

- [ ] **Step 3: Add the endpoint**

In `02_backend/api/main.py`, immediately after `list_alerts`:

```python
@app.get("/api/alerts/counts")
def alert_counts(conn=Depends(get_db)):
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM alerts GROUP BY status").fetchall()
    counts = {"OPEN": 0, "PROPOSED": 0, "PENDING": 0, "CLOSED": 0}
    for r in rows:
        counts[r["status"]] = r["n"]
    return {"counts": counts}
```

Note: `/api/alerts/counts` must be declared before any `@app.get("/api/alerts/{alert_id}")`-style path so it is not captured as an `alert_id`. `list_alerts` is at line 52 and `get_alert` at 69, so inserting right after `list_alerts` (line 66) is correct.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd 02_backend && python -m pytest tests/test_alert_counts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add 02_backend/api/main.py 02_backend/tests/test_alert_counts.py
git commit -m "feat: GET /api/alerts/counts (zero-filled per-status counts)"
```

---

## Task 4: `fund_flow_edges` + richer `get_network_graph`

**Files:**
- Modify: `02_backend/common/source.py` (add pure `fund_flow_edges`)
- Modify: `02_backend/agents/tools.py` (`get_network_graph`, line 46)
- Test: `02_backend/tests/test_network_graph.py` (new)

**Interfaces:**
- Produces:
  - `source.fund_flow_edges(transactions: list[dict], root_account_id: str) -> list[dict]` — pure. Groups a transaction list into directional fund-flow edges. Each edge: `{"source": str, "target": str, "relation": "fund_flow", "amount": float, "count": int}`. INBOUND rows → edge `from_account_id → root`; OUTBOUND rows → edge `root → (to_account_id or counterparty_name)`.
  - `tools.get_network_graph(conn, account_id)` now returns `{"nodes": [{"id","type","is_root"?,"country"?}], "edges": [{"source","target","relation"} (+amount,count on fund_flow)]}` where `type ∈ {collector, source, beneficiary, account}`.

- [ ] **Step 1: Write the failing test**

```python
# 02_backend/tests/test_network_graph.py
def test_fund_flow_edges_aggregates_by_pair():
    from common.source import fund_flow_edges
    txns = [
        {"direction": "INBOUND", "from_account_id": "ACC-N-001", "to_account_id": "ACC-ROOT",
         "amount": 40000.0, "counterparty_name": "Sender_001", "counterparty_country": "SG"},
        {"direction": "INBOUND", "from_account_id": "ACC-N-001", "to_account_id": "ACC-ROOT",
         "amount": 8200.0, "counterparty_name": "Sender_001", "counterparty_country": "SG"},
        {"direction": "OUTBOUND", "from_account_id": "ACC-ROOT", "to_account_id": None,
         "amount": 190000.0, "counterparty_name": "Oversea Beneficiary 1 Ltd", "counterparty_country": "CN"},
    ]
    edges = fund_flow_edges(txns, "ACC-ROOT")
    inbound = [e for e in edges if e["target"] == "ACC-ROOT"]
    assert len(inbound) == 1
    assert inbound[0]["source"] == "ACC-N-001"
    assert inbound[0]["amount"] == 48200.0 and inbound[0]["count"] == 2
    outbound = [e for e in edges if e["source"] == "ACC-ROOT"]
    assert outbound[0]["target"] == "Oversea Beneficiary 1 Ltd"
    assert all(e["relation"] == "fund_flow" for e in edges)


def test_fund_flow_edges_empty():
    from common.source import fund_flow_edges
    assert fund_flow_edges([], "ACC-ROOT") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 02_backend && python -m pytest tests/test_network_graph.py -v`
Expected: FAIL — `ImportError: cannot import name 'fund_flow_edges'`.

- [ ] **Step 3: Implement `fund_flow_edges` (pure)**

Add to `02_backend/common/source.py` (bottom, near the other graph helpers):

```python
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
```

- [ ] **Step 4: Run the pure-function tests**

Run: `cd 02_backend && python -m pytest tests/test_network_graph.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Enrich `get_network_graph` to use it**

Replace `get_network_graph` in `02_backend/agents/tools.py` (lines 46-59) with:

```python
def get_network_graph(conn, account_id: str) -> dict:
    fp_list = source.device_fingerprints(account_id)
    linked = source.accounts_by_fingerprints(fp_list) if fp_list else []

    txns = source.account_transactions(account_id, limit=200)
    flow = source.fund_flow_edges(txns, account_id)

    # node set: root + device-linked accounts + every endpoint named by a flow edge
    node_ids = {account_id}
    node_ids.update(a for a in linked if a != account_id)
    for e in flow:
        node_ids.add(e["source"]); node_ids.add(e["target"])

    # classify: root is the collector; flow targets that aren't accounts are beneficiaries
    flow_targets = {e["target"] for e in flow if e["source"] == account_id}
    flow_sources = {e["source"] for e in flow if e["target"] == account_id}
    nodes = []
    for nid in node_ids:
        if nid == account_id:
            nodes.append({"id": nid, "type": "collector", "is_root": True})
        elif nid in flow_targets and nid not in linked:
            nodes.append({"id": nid, "type": "beneficiary"})
        elif nid in flow_sources or nid in linked:
            nodes.append({"id": nid, "type": "source"})
        else:
            nodes.append({"id": nid, "type": "account"})

    edges = [{"source": account_id, "target": aid, "relation": "shared_device"}
             for aid in linked if aid != account_id]
    edges.extend(flow)
    return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 6: Add a graph-shape assertion test**

Append to `02_backend/tests/test_network_graph.py`:

```python
def test_get_network_graph_lone_account_is_failsoft(monkeypatch):
    from agents import tools
    monkeypatch.setattr(tools.source, "device_fingerprints", lambda a: [])
    monkeypatch.setattr(tools.source, "accounts_by_fingerprints", lambda f: [])
    monkeypatch.setattr(tools.source, "account_transactions", lambda a, limit=200: [])
    g = tools.get_network_graph(None, "ACC-LONE")
    assert g == {"nodes": [{"id": "ACC-LONE", "type": "collector", "is_root": True}], "edges": []}


def test_get_network_graph_funnel(monkeypatch):
    from agents import tools
    monkeypatch.setattr(tools.source, "device_fingerprints", lambda a: ["FP-1"])
    monkeypatch.setattr(tools.source, "accounts_by_fingerprints", lambda f: ["ACC-ROOT", "ACC-N-001"])
    monkeypatch.setattr(tools.source, "account_transactions", lambda a, limit=200: [
        {"direction": "INBOUND", "from_account_id": "ACC-N-001", "to_account_id": "ACC-ROOT", "amount": 48200.0},
        {"direction": "OUTBOUND", "from_account_id": "ACC-ROOT", "to_account_id": None,
         "amount": 190000.0, "counterparty_name": "Oversea Beneficiary 1 Ltd"},
    ])
    g = tools.get_network_graph(None, "ACC-ROOT")
    types = {n["id"]: n["type"] for n in g["nodes"]}
    assert types["ACC-ROOT"] == "collector"
    assert types["ACC-N-001"] == "source"
    assert types["Oversea Beneficiary 1 Ltd"] == "beneficiary"
    relations = {e["relation"] for e in g["edges"]}
    assert relations == {"shared_device", "fund_flow"}
```

- [ ] **Step 7: Run all network tests**

Run: `cd 02_backend && python -m pytest tests/test_network_graph.py -v`
Expected: PASS (4 passed).

- [ ] **Step 8: Commit**

```bash
git add 02_backend/common/source.py 02_backend/agents/tools.py 02_backend/tests/test_network_graph.py
git commit -m "feat: fund_flow_edges + typed network graph (sources/collector/beneficiary)"
```

---

## Task 5: `derive_tx_flags` + fold `network` and per-tx `flags` into `/detail`

**Files:**
- Create: `02_backend/common/tx_flags.py`
- Modify: `02_backend/api/main.py` (`get_alert_detail`, build per-tx `flags`, add `network`)
- Test: `02_backend/tests/test_tx_flags.py` (new)

**Interfaces:**
- Consumes: `tools.get_network_graph` (Task 4); `source.get_accounts` (existing, used to resolve the root account id like `investigate_case` at line 196-197).
- Produces:
  - `tx_flags.derive_tx_flags(tx: dict, all_txs: list[dict]) -> list[dict]` — pure. Each flag: `{"key": str, "label": str, "why": str}`. Keys: `near_threshold`, `off_hours`, `cross_border`, `repeat_counterparty`.
  - `/detail` response gains `"network": {...}` (the graph) and each transaction dict gains `"flags": [...]`.

- [ ] **Step 1: Write the failing test**

```python
# 02_backend/tests/test_tx_flags.py
from common.tx_flags import derive_tx_flags


def _tx(**kw):
    base = {"amount": 100.0, "event_time": "2026-07-09T14:00:00", "counterparty_country": "SG",
            "counterparty_name": "Shop", "direction": "OUTBOUND"}
    base.update(kw); return base


def test_near_threshold_fires_just_under_50k():
    flags = derive_tx_flags(_tx(amount=48201.0), [])
    assert any(f["key"] == "near_threshold" for f in flags)


def test_near_threshold_silent_for_small_amount():
    flags = derive_tx_flags(_tx(amount=60.0), [])
    assert not any(f["key"] == "near_threshold" for f in flags)


def test_off_hours_fires_at_3am():
    flags = derive_tx_flags(_tx(event_time="2026-07-09T03:21:00"), [])
    assert any(f["key"] == "off_hours" for f in flags)


def test_cross_border_fires_for_non_sg():
    flags = derive_tx_flags(_tx(counterparty_country="MY"), [])
    assert any(f["key"] == "cross_border" for f in flags)


def test_repeat_counterparty_needs_more_than_one():
    others = [_tx(counterparty_name="Recip_A"), _tx(counterparty_name="Recip_A")]
    flags = derive_tx_flags(_tx(counterparty_name="Recip_A"), others)
    assert any(f["key"] == "repeat_counterparty" for f in flags)


def test_clean_small_domestic_daytime_row_has_no_flags():
    assert derive_tx_flags(_tx(amount=60.0, event_time="2026-07-09T12:13:00",
                               counterparty_country="SG", counterparty_name="Grab"), []) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 02_backend && python -m pytest tests/test_tx_flags.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'common.tx_flags'`.

- [ ] **Step 3: Implement `derive_tx_flags` (pure)**

```python
# 02_backend/common/tx_flags.py
"""Pure, presentation-layer transaction typology flags. No I/O. Derived from a
row's own fields (+ the case's tx set for repeat detection). These are honest
heuristics for the demo — NOT model output."""

_STRUCTURING_THRESHOLD = 50_000.0
_NEAR_BAND = 5_000.0  # within $5k below the threshold


def derive_tx_flags(tx: dict, all_txs: list[dict]) -> list[dict]:
    flags: list[dict] = []
    amount = float(tx.get("amount") or 0.0)
    if _STRUCTURING_THRESHOLD - _NEAR_BAND <= amount < _STRUCTURING_THRESHOLD:
        flags.append({"key": "near_threshold", "label": "Near-threshold",
                      "why": f"${amount:,.0f} sits just under the ${_STRUCTURING_THRESHOLD:,.0f} reporting line."})

    hour = _hour(tx.get("event_time"))
    if hour is not None and 0 <= hour <= 6:
        flags.append({"key": "off_hours", "label": "Off-hours",
                      "why": f"Executed at {hour:02d}:00 — outside normal business hours."})

    country = (tx.get("counterparty_country") or "").upper()
    if country and country != "SG":
        flags.append({"key": "cross_border", "label": "Cross-border",
                      "why": f"Counterparty in {country}, not SG."})

    name = tx.get("counterparty_name")
    if name:
        same = sum(1 for t in all_txs if t.get("counterparty_name") == name)
        if same > 1:
            flags.append({"key": "repeat_counterparty", "label": "Repeat counterparty",
                          "why": f"Same counterparty appears {same}× in this case."})
    return flags


def _hour(event_time) -> int | None:
    if not event_time or "T" not in str(event_time):
        return None
    try:
        return int(str(event_time).split("T")[1][:2])
    except (ValueError, IndexError):
        return None
```

- [ ] **Step 4: Run the flag tests**

Run: `cd 02_backend && python -m pytest tests/test_tx_flags.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Fold `flags` + `network` into `/detail`**

In `02_backend/api/main.py`, at the top add the imports (near the other `from agents...`/`from common...` imports):

```python
from common.tx_flags import derive_tx_flags
from agents.tools import get_network_graph
```

In `get_alert_detail`, change the `transactions = [ ... ]` list-comp (line 143) so each row carries `flags`. Replace the comprehension with an explicit loop so `all_txs` is available:

```python
    transactions = []
    for t in customer_txns:
        row = {
            "transaction_id": t.get("transaction_id"),
            "event_time": t.get("event_time"),
            "direction": t.get("direction"),
            "amount": t.get("amount"),
            "channel": t.get("channel"),
            "counterparty_name": t.get("counterparty_name"),
            "counterparty_country": t.get("counterparty_country"),
            "typology": t.get("typology"),
            "is_suspicious": t.get("is_suspicious"),
            "score": tx_scores.get(t.get("transaction_id")),
            "label": tx_labels.get(t.get("transaction_id")),
            "from_account_id": t.get("from_account_id"),
            "to_account_id": t.get("to_account_id"),
            "currency": t.get("currency"),
            "mcc": t.get("mcc"),
            "reference": t.get("reference"),
        }
        row["flags"] = derive_tx_flags(t, customer_txns)
        transactions.append(row)
```

Then compute the network graph before the `return` (reuse the account-resolution pattern from `investigate_case`):

```python
    accounts = source.get_accounts(alert["customer_id"])
    root_account_id = accounts[0]["account_id"] if accounts else alert["customer_id"]
    try:
        network = get_network_graph(None, root_account_id)
    except Exception:
        network = {"nodes": [{"id": root_account_id, "type": "collector", "is_root": True}], "edges": []}
```

Add `"network": network,` to the returned dict (after `"transactions": transactions,`).

- [ ] **Step 6: Add a `/detail` wiring smoke test**

Append to `02_backend/tests/test_tx_flags.py`:

```python
def test_detail_includes_network_and_flags(tmp_db_path, monkeypatch):
    from fastapi.testclient import TestClient
    from common.db import get_connection
    import api.main as main

    conn = get_connection()
    conn.execute("INSERT INTO alerts (alert_id, customer_id, account_id, risk_score, risk_band, status, created_at) "
                 "VALUES ('ALERT-1','CUST-1','ACC-1',0.9,'CRITICAL','OPEN','t')")
    conn.commit()

    monkeypatch.setattr(main.source, "get_customer", lambda c: {"name": "X", "risk_rating": "LOW"})
    monkeypatch.setattr(main.source, "customer_transactions", lambda c, limit=20: [
        {"transaction_id": "T1", "event_time": "2026-07-09T03:21:00", "direction": "OUTBOUND",
         "amount": 48201.0, "channel": "FAST", "counterparty_name": "R", "counterparty_country": "MY"}])
    monkeypatch.setattr(main.source, "get_accounts", lambda c: [{"account_id": "ACC-1"}])
    monkeypatch.setattr(main.source, "device_fingerprints", lambda a: [])
    monkeypatch.setattr(main.source, "accounts_by_fingerprints", lambda f: [])
    monkeypatch.setattr(main.source, "account_transactions", lambda a, limit=200: [])

    r = TestClient(main.app).get("/api/alerts/ALERT-1/detail")
    body = r.json()
    assert "network" in body and body["network"]["nodes"][0]["is_root"] is True
    flags = {f["key"] for f in body["transactions"][0]["flags"]}
    assert "near_threshold" in flags and "off_hours" in flags and "cross_border" in flags
```

- [ ] **Step 7: Run the full test + regression**

Run: `cd 02_backend && python -m pytest tests/test_tx_flags.py tests/test_network_graph.py -v`
Expected: PASS. Then `cd 02_backend && python -m pytest -q` — all green (no regressions).

- [ ] **Step 8: Commit**

```bash
git add 02_backend/common/tx_flags.py 02_backend/api/main.py 02_backend/tests/test_tx_flags.py
git commit -m "feat: per-transaction typology flags + network graph in /detail"
```

---

## Task 6: Second shared-device ring in synthetic data

**Files:**
- Modify: `02_backend/data_generation/generate_synthetic_data.py` (`gen_devices`, lines 164-193)
- Test: `02_backend/tests/test_devices_rings.py` (new)

**Interfaces:**
- Produces: `ACC-NETWORK-005..008` share a second fingerprint `FP-NIGHTFALL-SHARED-002` (a weaker second ring). `ACC-NIGHTFALL-001` + `ACC-NETWORK-001..004` keep `FP-NIGHTFALL-SHARED-001`.

- [ ] **Step 1: Write the failing test**

```python
# 02_backend/tests/test_devices_rings.py
def test_two_device_rings():
    from data_generation.generate_synthetic_data import gen_devices
    accounts = [{"account_id": "ACC-NIGHTFALL-001"}] + [
        {"account_id": f"ACC-NETWORK-{i:03d}"} for i in range(1, 9)]
    devs = gen_devices(accounts)
    fp = {d["account_id"]: d["device_fingerprint"] for d in devs if d["account_id"].startswith("ACC-N")}
    ring1 = {a for a, f in fp.items() if f == "FP-NIGHTFALL-SHARED-001"}
    ring2 = {a for a, f in fp.items() if f == "FP-NIGHTFALL-SHARED-002"}
    assert "ACC-NIGHTFALL-001" in ring1 and "ACC-NETWORK-001" in ring1
    assert "ACC-NETWORK-005" in ring2 and "ACC-NETWORK-008" in ring2
    assert ring1.isdisjoint(ring2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd 02_backend && python -m pytest tests/test_devices_rings.py -v`
Expected: FAIL — `ACC-NETWORK-005` currently gets a unique `FP-...`, not `FP-NIGHTFALL-SHARED-002`.

- [ ] **Step 3: Add the second ring**

In `gen_devices` (line 164), replace the fingerprint-selection block:

```python
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
        if random.random() < 0.3 and not aid.startswith("ACC-NIGHTFALL") and not aid.startswith("ACC-NETWORK"):
            rows.append({
                "device_id": f"DEV-{_uid()}",
                "account_id": aid,
                "device_fingerprint": f"FP-{_uid()}",
                "ip_address": _ip(),
                "login_time": _ts(random.uniform(0, 30)),
            })

    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd 02_backend && python -m pytest tests/test_devices_rings.py -v`
Expected: PASS.

- [ ] **Step 5: Regenerate the demo DB + CSVs so the running app shows the funnel**

Run:
```bash
cd 02_backend && python data_generation/generate_synthetic_data.py && python scripts/export_source_csv.py && cd ..
```
Expected: completes without error (rebuilds `data/aml.db` + `data/raw/*.csv`).

- [ ] **Step 6: Commit**

```bash
git add 02_backend/data_generation/generate_synthetic_data.py 02_backend/tests/test_devices_rings.py
git commit -m "feat: second shared-device ring (ACC-NETWORK-005..008) for network demo"
```

---

## Task 7: Frontend API types + calls

**Files:**
- Modify: `03_frontend/src/api.ts`

**Interfaces:**
- Produces: `NetworkNode`, `NetworkEdge`, `NetworkGraph`, `TxFlag` types; `network?` on `CaseDetail`; `flags?` + raw fields on `Transaction`; `AlertStatus` type; `getAlertCounts()`; `getAlerts` accepts any status string.

- [ ] **Step 1: Add types + call (no test — `tsc` is the gate)**

In `03_frontend/src/api.ts`, extend `Transaction` (line 41) with the new optional fields:

```typescript
export interface TxFlag { key: string; label: string; why: string }

export interface Transaction {
  transaction_id?: string
  event_time: string
  direction: string
  amount: number
  channel: string
  counterparty_name: string
  counterparty_country: string
  typology?: string
  is_suspicious: number
  score: number | null
  label?: number | null
  from_account_id?: string | null
  to_account_id?: string | null
  currency?: string | null
  mcc?: string | null
  reference?: string | null
  flags?: TxFlag[]
}
```

Add graph types + put `network?` on `CaseDetail` (line 21, add the field before the closing brace):

```typescript
export interface NetworkNode { id: string; type: string; is_root?: boolean; country?: string }
export interface NetworkEdge {
  source: string; target: string; relation: 'shared_device' | 'fund_flow'
  amount?: number; count?: number
}
export interface NetworkGraph { nodes: NetworkNode[]; edges: NetworkEdge[] }
```

Add to the `CaseDetail` interface body: `network?: NetworkGraph`.

Add the status type + counts call (near `getAlerts`, line 96-102):

```typescript
export type AlertStatus = 'OPEN' | 'PROPOSED' | 'PENDING' | 'CLOSED'

export const getAlertCounts = () =>
  api.get<{ counts: Record<AlertStatus, number> }>('/alerts/counts').then(r => r.data.counts)
```

Change `getAlerts` signature to accept a status string (keep default `'OPEN'`):

```typescript
export const getAlerts = (status: string = 'OPEN', limit = 50, sort: AlertSort = 'risk_score') =>
  api.get<AlertsResponse>('/alerts', { params: { status, limit, sort } }).then(r => r.data)
```

- [ ] **Step 2: Typecheck**

Run: `cd 03_frontend && npm run build`
Expected: builds clean (types only; no consumers broken yet).

- [ ] **Step 3: Commit**

```bash
git add 03_frontend/src/api.ts
git commit -m "feat: frontend types for network graph, tx flags, alert counts"
```

---

## Task 8: `NetworkGraph.tsx` — layered SVG funnel

**Files:**
- Create: `03_frontend/src/components/NetworkGraph.tsx`

**Interfaces:**
- Consumes: `NetworkGraph`, `NetworkNode`, `NetworkEdge` from `api.ts` (Task 7).
- Produces: `export const NetworkGraph: React.FC<{ graph: NetworkGraph }>`.

- [ ] **Step 1: Create the component**

```tsx
// 03_frontend/src/components/NetworkGraph.tsx
import { Share2 } from 'lucide-react'
import type { NetworkGraph as Graph, NetworkNode } from '../api'

const COL_X: Record<string, number> = { source: 90, collector: 300, beneficiary: 510, account: 300 }
const NODE_W = 132
const NODE_H = 40
const SVG_W = 640

const NODE_STYLE: Record<string, { fill: string; stroke: string; text: string }> = {
  source:      { fill: '#f7f8fa', stroke: '#9aa1ac', text: '#4b5563' },
  collector:   { fill: '#fff4ee', stroke: '#e35b1f', text: '#e35b1f' },
  beneficiary: { fill: '#fef2f2', stroke: '#dc2626', text: '#dc2626' },
  account:     { fill: '#f7f8fa', stroke: '#d5d9e0', text: '#9aa1ac' },
}

const short = (id: string) => (id.length > 18 ? id.slice(0, 17) + '…' : id)
const money = (n?: number) => (n == null ? '' : n >= 1000 ? `$${(n / 1000).toFixed(0)}k` : `$${n}`)

export const NetworkGraph: React.FC<{ graph: Graph }> = ({ graph }) => {
  if (!graph || graph.nodes.length === 0) return null

  // group nodes into columns, assign y by index within the column
  const cols: Record<string, NetworkNode[]> = { source: [], collector: [], beneficiary: [], account: [] }
  graph.nodes.forEach(n => { (cols[n.type] ?? cols.account).push(n) })

  const pos: Record<string, { x: number; y: number }> = {}
  const rowGap = NODE_H + 16
  Object.entries(cols).forEach(([type, ns]) => {
    const x = COL_X[type] ?? COL_X.account
    const top = 20 + Math.max(0, (Math.max(...Object.values(cols).map(c => c.length)) - ns.length)) * rowGap / 2
    ns.forEach((n, i) => { pos[n.id] = { x, y: top + i * rowGap } })
  })

  const maxCount = Math.max(1, ...Object.values(cols).map(c => c.length))
  const svgH = 40 + maxCount * rowGap

  const cx = (id: string) => (pos[id]?.x ?? 300) + NODE_W / 2
  const cy = (id: string) => (pos[id]?.y ?? 20) + NODE_H / 2

  return (
    <div className="bg-surface-1 rounded-lg shadow-soft overflow-hidden">
      <div className="flex items-center gap-2 border-b border-surface-3 px-4 py-2">
        <Share2 className="w-3 h-3 text-accent" />
        <span className="text-2xs font-semibold tracking-wider uppercase text-ink-muted">Network Graph</span>
        <span className="ml-auto text-2xs text-ink-faint">
          {graph.nodes.length} nodes · {graph.edges.length} links
        </span>
      </div>
      <div className="overflow-x-auto px-2 py-2">
        <svg viewBox={`0 0 ${SVG_W} ${svgH}`} width="100%" style={{ minWidth: SVG_W }}>
          <defs>
            <marker id="ng-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <polygon points="0,0 8,4 0,8" fill="#e35b1f" />
            </marker>
          </defs>

          {graph.edges.map((e, i) => {
            const x1 = cx(e.source), y1 = cy(e.source), x2 = cx(e.target), y2 = cy(e.target)
            const isFlow = e.relation === 'fund_flow'
            return (
              <g key={i}>
                <line
                  x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke={isFlow ? '#e35b1f' : '#c4b5fd'}
                  strokeWidth={isFlow ? 1.6 : 1.2}
                  strokeDasharray={isFlow ? undefined : '4 3'}
                  markerEnd={isFlow ? 'url(#ng-arrow)' : undefined}
                  opacity={0.8}
                />
                {isFlow && e.amount != null && (
                  <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 3} textAnchor="middle"
                        fontSize={8} fill="#e35b1f" fontFamily="Inter,system-ui,sans-serif">
                    {money(e.amount)}
                  </text>
                )}
              </g>
            )
          })}

          {graph.nodes.map(n => {
            const p = pos[n.id]; if (!p) return null
            const s = NODE_STYLE[n.type] ?? NODE_STYLE.account
            return (
              <g key={n.id}>
                <rect x={p.x} y={p.y} width={NODE_W} height={NODE_H} rx={7}
                      fill={s.fill} stroke={s.stroke} strokeWidth={n.is_root ? 2 : 1} />
                <text x={p.x + NODE_W / 2} y={p.y + 17} textAnchor="middle" fontSize={9}
                      fill={s.text} fontWeight="600" fontFamily="Inter,system-ui,sans-serif">
                  {short(n.id)}
                </text>
                <text x={p.x + NODE_W / 2} y={p.y + 30} textAnchor="middle" fontSize={7.5}
                      fill={s.text} opacity={0.7} fontFamily="Inter,system-ui,sans-serif">
                  {n.type}{n.country ? ` · ${n.country}` : ''}
                </text>
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Typecheck**

Run: `cd 03_frontend && npm run build`
Expected: clean (component compiles; not yet rendered).

- [ ] **Step 3: Commit**

```bash
git add 03_frontend/src/components/NetworkGraph.tsx
git commit -m "feat: NetworkGraph layered-SVG funnel component"
```

---

## Task 9: Alert Queue buckets + counts

**Files:**
- Modify: `03_frontend/src/components/AlertQueue.tsx`

**Interfaces:**
- Consumes: `getAlerts(status, ...)`, `getAlertCounts()`, `AlertStatus` from `api.ts`.
- Produces: a `status` state (default `'OPEN'`) + a segmented control (Open · Proposed · Pending · Archived) driving the query; counts per bucket.

- [ ] **Step 1: Add the bucket bar + status-driven load**

Replace the top of `AlertQueue.tsx` (the imports through the `load`/`useEffect` block, lines 1-39) with:

```tsx
import React, { useEffect, useState } from 'react'
import { Bell, RefreshCw } from 'lucide-react'
import type { Alert, AlertSort, AlertStatus } from '../api'
import { getAlerts, getAlertCounts } from '../api'
import { RiskBadge } from './Badge'

const RISK_COLOR: Record<string, string> = {
  CRITICAL: '#dc2626', HIGH: '#ea580c', MEDIUM: '#d97706', LOW: '#16a34a',
}

const BUCKETS: { status: AlertStatus; label: string }[] = [
  { status: 'OPEN', label: 'Open' },
  { status: 'PROPOSED', label: 'Proposed' },
  { status: 'PENDING', label: 'Pending' },
  { status: 'CLOSED', label: 'Archived' },
]

interface Props {
  selectedAlertId: string | null
  onSelect: (alert: Alert) => void
  reloadKey?: number   // bump to force a reload after a disposition
}

export const AlertQueue: React.FC<Props> = ({ selectedAlertId, onSelect, reloadKey }) => {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [counts, setCounts] = useState<Record<AlertStatus, number>>({ OPEN: 0, PROPOSED: 0, PENDING: 0, CLOSED: 0 })
  const [status, setStatus] = useState<AlertStatus>('OPEN')
  const [loading, setLoading] = useState(true)
  const [sort, setSort] = useState<AlertSort>('risk_score')
  const [error, setError] = useState(false)

  const load = (nextStatus: AlertStatus = status, nextSort: AlertSort = sort) => {
    setLoading(true); setError(false)
    getAlerts(nextStatus, 50, nextSort)
      .then(r => setAlerts(r.alerts))
      .catch(() => { setAlerts([]); setError(true) })
      .finally(() => setLoading(false))
    getAlertCounts().then(setCounts).catch(() => {})
  }

  useEffect(() => { load() }, [reloadKey])   // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 2: Add the bucket bar to the header and use `counts[status]`**

In the header block, replace the count badge (`{openCount}`) with `{counts[status]}`, and insert the bucket bar directly under the header row (after the closing `</div>` of the header flex, before `{/* List */}`):

```tsx
      {/* Bucket bar */}
      <div className="flex gap-1 px-3 py-2 border-b border-surface-3 bg-surface-1">
        {BUCKETS.map(b => (
          <button
            key={b.status}
            onClick={() => { setStatus(b.status); load(b.status) }}
            className={`text-2xs font-semibold px-2 py-1 rounded-lg transition-colors
              ${status === b.status ? 'bg-accent text-white' : 'text-ink-muted bg-surface-2 hover:bg-surface-3'}`}
          >
            {b.label} <span className="opacity-70">{counts[b.status]}</span>
          </button>
        ))}
      </div>
```

Update the empty-state text to reflect the bucket:

```tsx
            {error ? "Couldn't load alerts" : `No ${status.toLowerCase()} alerts`}
```

- [ ] **Step 3: Typecheck**

Run: `cd 03_frontend && npm run build`
Expected: clean. (`App.tsx` still compiles — `reloadKey` is optional.)

- [ ] **Step 4: Commit**

```bash
git add 03_frontend/src/components/AlertQueue.tsx
git commit -m "feat: alert queue disposition buckets (Open/Proposed/Pending/Archived) + counts"
```

---

## Task 10: Dispose reload wiring + read-only-when-closed

**Files:**
- Modify: `03_frontend/src/App.tsx`
- Modify: `03_frontend/src/components/CaseWorkbench.tsx`

**Interfaces:**
- Consumes: `AlertQueue`'s `reloadKey` prop (Task 9).
- Produces: `CaseWorkbench` accepts `onDisposed?: () => void`, calls it after a successful dispose; `App` increments a `reloadKey` and clears selection on that callback.

- [ ] **Step 1: Wire `onDisposed` in `App.tsx`**

In `03_frontend/src/App.tsx`, add a reload counter and pass it down. Add near the other `useState` hooks:

```tsx
  const [queueReload, setQueueReload] = useState(0)
```

Pass `reloadKey={queueReload}` to `<AlertQueue ... />` and `onDisposed={() => { setQueueReload(k => k + 1) }}` to `<CaseWorkbench ... />`. (Keep the existing `selectedAlert`/`onSelect` props.)

- [ ] **Step 2: Consume `onDisposed` in `CaseWorkbench.tsx`**

Add `onDisposed?: () => void` to the workbench `Props` interface. Find the dispose handler (the function that calls the dispose API on Submit Decision) and, on success, call `onDisposed?.()`. If the workbench currently derives a `closed`/`disposition` state, also disable the decision controls when `detail.disposition` is set:

```tsx
  const isClosed = !!detail.disposition
```

Guard the Submit control with `disabled={isClosed || ...}` and show the existing "Decision recorded" note when `isClosed`. (Do not remove existing behavior — only add the guard.)

- [ ] **Step 3: Typecheck + manual check**

Run: `cd 03_frontend && npm run build`
Expected: clean.

Manual: with the app running (`python start_app.py`), open an OPEN alert → dispose SUSPICIOUS → the row leaves **Open** and the **Proposed** count increments; selecting **Proposed** shows it.

- [ ] **Step 4: Commit**

```bash
git add 03_frontend/src/App.tsx 03_frontend/src/components/CaseWorkbench.tsx
git commit -m "feat: reload queue + lock workbench after disposition"
```

---

## Task 11: Render NetworkGraph + expandable transaction row

**Files:**
- Modify: `03_frontend/src/components/CaseWorkbench.tsx`

**Interfaces:**
- Consumes: `NetworkGraph` component (Task 8); `detail.network` and `tx.flags` (Tasks 5, 7).
- Produces: a Network card above `AgentPanel`; each tx row expands on click to show raw fields + flag chips.

- [ ] **Step 1: Render the Network card**

In `CaseWorkbench.tsx`, import the component: `import { NetworkGraph } from './NetworkGraph'`. Just before `<AgentPanel ... />` (line 195), add:

```tsx
        {detail.network && detail.network.nodes.length > 1 && (
          <div className="mb-6">
            <div className="w-8 h-0.5 bg-accent mb-2" />
            <h3 className="text-sm font-bold text-ink mb-2">Network</h3>
            <NetworkGraph graph={detail.network} />
          </div>
        )}
```

- [ ] **Step 2: Make tx rows expandable**

Add expansion state near the top of the component (with the other hooks):

```tsx
  const [openRow, setOpenRow] = useState<number | null>(null)
```

Import a chevron: add `ChevronDown, ChevronRight` to the existing `lucide-react` import. Change the sorted map (line 151) to render a fragment per row (row + optional detail row). Replace the `<tr ...>...</tr>` block with:

```tsx
              {[...(detail.transactions ?? [])]
                .sort((a, b) => (b.is_suspicious ? 1 : 0) - (a.is_suspicious ? 1 : 0))
                .map((tx, i) => (
                <React.Fragment key={i}>
                  <tr
                    onClick={() => setOpenRow(openRow === i ? null : i)}
                    className={`border-b border-surface-3 last:border-0 transition-colors cursor-pointer
                      ${tx.is_suspicious ? 'bg-red-50 hover:bg-red-100/50' : 'hover:bg-surface-2'}`}
                  >
                    <td className="px-3 py-2.5 text-ink-muted font-mono">
                      <span className="inline-flex items-center gap-1">
                        {openRow === i ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                        {fmtDate(tx.event_time)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      {tx.direction === 'OUT'
                        ? <ArrowUpRight className="w-4 h-4 text-red-500" />
                        : <ArrowDownLeft className="w-4 h-4 text-green-500" />}
                    </td>
                    <td className="px-3 py-2.5 text-ink font-semibold tabular-nums">{fmt(tx.amount)}</td>
                    <td className="px-3 py-2.5 text-ink-muted">{tx.channel}</td>
                    <td className="px-3 py-2.5 text-ink-muted">{tx.counterparty_name}</td>
                    <td className="px-3 py-2.5">
                      <span className="px-1.5 py-0.5 rounded-lg bg-surface-3 text-ink-muted font-mono text-2xs">
                        {tx.counterparty_country}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      {tx.typology
                        ? <Badge label={tx.typology} color="#fff7ed" small />
                        : <span className="text-ink-faint">—</span>}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums font-semibold">
                      {tx.score != null
                        ? <span className={RISK_SCORE_COLOR(tx.score)}>{(tx.score * 100).toFixed(0)}%</span>
                        : <span className="text-ink-faint">—</span>}
                    </td>
                    <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                      {tx.transaction_id
                        ? <LabelControl
                            value={labels[tx.transaction_id] ?? null}
                            onChange={next => saveLabel(tx.transaction_id!, next)}
                          />
                        : <span className="text-ink-faint">—</span>}
                    </td>
                  </tr>
                  {openRow === i && (
                    <tr className="bg-surface-2/60">
                      <td colSpan={9} className="px-6 py-3">
                        <div className="flex flex-wrap gap-1.5 mb-3">
                          {(tx.flags ?? []).length === 0
                            ? <span className="text-2xs text-ink-faint">No typology flags for this transaction.</span>
                            : (tx.flags ?? []).map(f => (
                                <span key={f.key} title={f.why}
                                  className="text-2xs font-semibold px-2 py-0.5 rounded-lg bg-amber-50 text-amber-700 border border-amber-200">
                                  {f.label}
                                </span>
                              ))}
                        </div>
                        <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-2xs text-ink-muted">
                          <Detail label="Transaction ID" value={tx.transaction_id} />
                          <Detail label="From → To" value={`${tx.from_account_id ?? '—'} → ${tx.to_account_id ?? '—'}`} />
                          <Detail label="Currency" value={tx.currency} />
                          <Detail label="MCC" value={tx.mcc} />
                          <Detail label="Reference" value={tx.reference} />
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
```

- [ ] **Step 3: Add the `Detail` helper**

Near the other small helpers at the bottom of the file (e.g. beside `LabelControl`), add:

```tsx
const Detail: React.FC<{ label: string; value?: string | null }> = ({ label, value }) => (
  <div className="flex gap-2">
    <span className="text-ink-faint uppercase tracking-wider">{label}</span>
    <span className="font-mono text-ink-muted break-all">{value || '—'}</span>
  </div>
)
```

- [ ] **Step 4: Typecheck**

Run: `cd 03_frontend && npm run build`
Expected: clean.

- [ ] **Step 5: Manual verification**

With the app running, open the Nightfall case: the Network card draws the funnel (source mules → collector → offshore beneficiaries, orange fund-flow arrows + dashed device links). Click a $48k STRUCTURING row → it expands showing **Near-threshold** (+ **Cross-border**/**Off-hours** where applicable) plus raw fields; the $60 Grab row expands to "No typology flags."

- [ ] **Step 6: Commit**

```bash
git add 03_frontend/src/components/CaseWorkbench.tsx
git commit -m "feat: network card + expandable transaction detail with typology flags"
```

---

## Task 12: Full regression + README note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Backend regression**

Run: `cd 02_backend && python -m pytest -q`
Expected: all green (existing net + new tests).

- [ ] **Step 2: Frontend build**

Run: `cd 03_frontend && npm run build`
Expected: clean.

- [ ] **Step 3: Add a short README subsection**

In `README.md`, after the "MCP tool servers + verification agent" section, add:

```markdown
### Case lifecycle & network graph

Dispositioning a case now routes its alert out of the **Open** queue: `SUSPICIOUS`
→ **Proposed** (awaiting SAR/STR filing), `NEEDS_MORE_INFO` → **Pending**,
`FALSE_POSITIVE` → **Archived**. The Alert Queue has a bucket bar with live counts;
a legacy DB is backfilled idempotently on startup.

Opening a case draws the account's **network graph** (source mules → collector →
offshore beneficiaries) from `/api/alerts/{id}/detail` — orange arrows are
aggregated fund-flow, dashed links are shared devices. Clicking a transaction row
expands raw fields plus derived typology flags (near-threshold, off-hours,
cross-border, repeat-counterparty). Flags are honest heuristics, not model output.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: case lifecycle queues + network graph + tx detail"
```

---

## Self-Review

**Spec coverage:**
- §1 status model → Task 1. Backfill → Task 2. Counts endpoint → Task 3. Queue buckets → Task 9. onDisposed reload + read-only → Task 10. ✓
- §2 funnel data → Task 6 (fund-flow already existed; second ring added). `fund_flow_edges` + typed `get_network_graph` → Task 4. `/detail` network → Task 5. `NetworkGraph.tsx` → Task 8, rendered in Task 11. ✓
- §3 expandable row + raw fields + derived flags → Task 5 (server-side `derive_tx_flags`, the spec's stated alternative — chosen because there is no frontend test runner) + Task 11 (render). No fake model explanation. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every test shows assertions. ✓

**Type consistency:** `fund_flow_edges(transactions, root_account_id)` and its `{source,target,relation,amount,count}` edge shape are identical in Tasks 4, 5, 8. `derive_tx_flags(tx, all_txs)` → `[{key,label,why}]` identical in Tasks 5, 11. `AlertStatus`/`getAlertCounts`/`reloadKey` names identical in Tasks 7, 9, 10. `NetworkGraph` component prop `{ graph }` matches its use in Task 11. ✓

**Deviation from spec (conscious):** transaction flags computed server-side (Task 5) rather than a frontend `deriveTxFlags` helper — the spec listed this as the alternative; chosen because the frontend has no test runner and the backend does, so the logic gets real pytest coverage. No new dependency added.
