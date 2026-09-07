# Case lifecycle queues + network graph visualization — design

**Date:** 2026-09-07
**Branch:** `feat/tx-labels-and-caii-endpoints`
**Status:** approved (both sections) — ready for implementation plan

## Context

Two demo-polish gaps in the AML investigation workbench:

1. **Closed cases never leave the Alert Queue.** `dispose_case` (`02_backend/api/main.py:229`)
   sets `cases.state='CLOSED'` + `cases.disposition` and inserts an annotation, but it
   never updates `alerts.status`. The queue is `GET /api/alerts?status=OPEN` and
   `AlertQueue.tsx` only ever queries `OPEN`, so a dispositioned case stays in the queue
   indefinitely. There is no "proposed case" / reviewed view.

2. **The network is analyzed but never drawn.** `get_network_graph(account_id)`
   (`02_backend/agents/tools.py:46`) already returns `{nodes, edges}` (a star of accounts
   sharing a device fingerprint), but the data is only serialized into the network worker's
   LLM prompt and returned as prose. The UI renders the pipeline DAG (`WorkflowGraph`) and
   text findings — no node-link diagram. The synthetic network is also thin: only
   `ACC-NIGHTFALL-001` + `ACC-NETWORK-001..004` share `FP-NIGHTFALL-SHARED-001`;
   `NETWORK-005..008` have unique fingerprints (unlinked). No fund-flow edges, no funnel.

Governing constraint (matches the rest of the blueprint): **fail-soft**. A lone account
with no links renders a single node; a closed DB with legacy `OPEN` alerts is backfilled
idempotently; nothing new throws.

---

## Section 1 — Case lifecycle & queue routing

### Status model

`alerts.status` (default `'OPEN'`) becomes disposition-driven. The transition happens in
the **same transaction** as the existing case close, inside `dispose_case`:

| Disposition       | `alerts.status` → | Bucket / UI                                  |
|-------------------|-------------------|----------------------------------------------|
| `SUSPICIOUS`      | `PROPOSED`        | **Proposed Cases** (awaiting SAR/STR filing) |
| `FALSE_POSITIVE`  | `CLOSED`          | **Archived** (hidden by default)             |
| `NEEDS_MORE_INFO` | `PENDING`         | **Pending** (stays visible, "needs info")    |

Added statement (one line, keyed via the case's alert):

```sql
UPDATE alerts SET status = ?
WHERE alert_id = (SELECT alert_id FROM cases WHERE case_id = ?)
```

A small `_DISPOSITION_TO_STATUS = {"SUSPICIOUS": "PROPOSED", "FALSE_POSITIVE": "CLOSED",
"NEEDS_MORE_INFO": "PENDING"}` map in `main.py` drives it. `list_alerts` already accepts
`?status=`, so no query-shape change; only new status *values* flow through.

### Migration / backfill

Legacy DBs have closed cases whose alerts are still `OPEN`. An idempotent backfill runs
once in the existing self-heal seam (`common/db.py` `get_connection()`, alongside the
`conn.execute(_*_SQL)` calls):

```sql
UPDATE alerts SET status =
  CASE (SELECT disposition FROM cases WHERE cases.alert_id = alerts.alert_id)
    WHEN 'SUSPICIOUS' THEN 'PROPOSED'
    WHEN 'FALSE_POSITIVE' THEN 'CLOSED'
    WHEN 'NEEDS_MORE_INFO' THEN 'PENDING'
  END
WHERE status = 'OPEN'
  AND alert_id IN (SELECT alert_id FROM cases WHERE state = 'CLOSED');
```

Idempotent: only rewrites `OPEN` rows whose case is `CLOSED`. Safe to run every connect.

### UI

`AlertQueue.tsx` gains a segmented control in the header: **Open · Proposed · Pending ·
Archived**, each showing its count. A `status` state var (default `'OPEN'`) drives
`getAlerts(status, …)`; selecting a bucket re-queries. The existing single-list row
rendering is reused unchanged. A `PROPOSED` row shows a "SAR/STR proposed" chip.

Counts: `list_alerts` return already includes `total` for the queried status. To show all
four counts at once without four round-trips, extend the alerts summary (there is already a
`/api/stats`-style count block at `main.py:358`) OR return a `counts` dict from a light
`GET /api/alerts/counts` (one `SELECT status, COUNT(*) ... GROUP BY status`). Chosen:
**`GET /api/alerts/counts`** — one query, keeps `list_alerts` unchanged.

### Data flow after disposition

`CaseWorkbench` already calls dispose; add an `onDisposed` callback prop wired from `App`/
the queue so that on a successful `Submit Decision` the queue reloads the active bucket and
clears the selection. The just-closed case visibly leaves **Open** and appears under
**Proposed**. The workbench renders read-only once the case has left `OPEN` (disposition
already recorded — no re-submit).

---

## Section 2 — Network graph + synthetic data enrichment

### Synthetic data — the funnel

Reshape the 8 `ACC-NETWORK` accounts (`generate_synthetic_data.py` `gen_accounts` /
`gen_devices` / transaction generators) into a classic mule funnel:

```
  SOURCE MULES            COLLECTOR            OFFSHORE
  (shared device)        (aggregator)        (beneficiary)

  NETWORK-001 ─┐
  NETWORK-002 ─┤ fund-flow                    ┌─ BENE-HK (offshore)
  NETWORK-003 ─┼──────────►  NIGHTFALL-001 ──►┤
  NETWORK-004 ─┘  (structured,               └─ BENE-AE (offshore)
  ⋮ shared FP     just-under-threshold)
  NETWORK-005..008 ── second device cluster ─┘ (2nd ring, weaker link)
```

Two edge types in the generated data:

- **shared-device** — all sources ↔ collector share `FP-NIGHTFALL-SHARED-001`; add a
  second fingerprint (`FP-NIGHTFALL-SHARED-002`) covering `NETWORK-005..008` so there are
  **two rings** (one tightly linked, one weaker).
- **fund-flow** — directional transfers `sources → collector → offshore`, from the
  `transactions` table. The source→collector legs are the existing structuring/mule-funnel
  transactions (tag them so they are queryable by account pair); **add** the
  collector→offshore leg (2 offshore beneficiary counterparties, cross-border).

Beneficiaries are represented as counterparty nodes (they need not be full accounts — the
graph derives them from transaction `counterparty_name`/`counterparty_country`).

### Backend — richer graph + fund-flow helper

Extend `get_network_graph(account_id)` (`agents/tools.py`) to return:

```json
{
  "nodes": [
    {"id": "ACC-NIGHTFALL-001", "type": "collector", "is_root": true},
    {"id": "ACC-NETWORK-001",   "type": "source"},
    {"id": "BENE-HK",           "type": "beneficiary", "country": "HK"}
  ],
  "edges": [
    {"source": "ACC-NETWORK-001", "target": "ACC-NIGHTFALL-001",
     "relation": "shared_device"},
    {"source": "ACC-NETWORK-001", "target": "ACC-NIGHTFALL-001",
     "relation": "fund_flow", "amount": 48200.0, "count": 6},
    {"source": "ACC-NIGHTFALL-001", "target": "BENE-HK",
     "relation": "fund_flow", "amount": 190000.0, "count": 3}
  ]
}
```

- Node `type ∈ {source, collector, beneficiary, account}`; `is_root` on the queried account.
- Edge `relation ∈ {shared_device, fund_flow}`; fund-flow carries `amount` + `count`.
- New source-layer helper `fund_flow_edges(account_ids)` in `common/source.py` — aggregates
  transfers among the network's accounts (and their offshore counterparties) into
  directional edges. Deterministic, no LLM.
- Fold the graph into `GET /api/alerts/{id}/detail` (`main.py:94`) so it is available the
  instant a case opens (before any agent run). `CaseDetail` type in `api.ts` gains a
  `network` field.

Fail-soft: no fingerprints / no transfers → single root node, empty edges (today's
behavior for an unlinked account).

### Frontend — `NetworkGraph.tsx` (new), hand-rolled SVG, no new dependency

A funnel has a **known layered topology**, so nodes are placed in three columns
(sources → collector → beneficiary) with a deterministic vertical spread — no force/physics
library needed. Reuses the `WorkflowGraph.tsx` SVG idiom (literal light-theme hex,
`viewBox` scaling, animated running state).

- **Fund-flow edges**: solid arrows, labeled with aggregated amount.
- **Shared-device edges**: dashed grey.
- **Nodes**: root highlighted (accent), offshore/beneficiary in red, sources neutral.
- Layout: column x by node `type`; within a column, evenly spread y. Curved/elbow edges via
  simple SVG paths.

**Alternative considered:** `react-flow` / `d3-force` — richer drag/zoom/auto-layout, but a
real dependency + bundle weight for a fixed 3-column topology. **Rejected (YAGNI)**; the
layered SVG covers the demo. Documented as a stretch if free-form graphs are ever needed.

### Where it renders

A collapsible **"Network"** card in `CaseWorkbench`, above `AgentPanel`, populated from the
`/detail` payload — the analyst sees the ring immediately on opening the case. When the
network worker runs, its prose findings annotate the same card (the graph does not re-fetch;
it is already drawn from `/detail`).

---

## Files touched (representative)

**Backend**
- `02_backend/api/main.py` — `_DISPOSITION_TO_STATUS`, alert-status update in
  `dispose_case`, `GET /api/alerts/counts`, `network` in `/detail`.
- `02_backend/common/db.py` — idempotent status backfill in the self-heal seam.
- `02_backend/agents/tools.py` — richer `get_network_graph` (typed nodes/edges, fund-flow).
- `02_backend/common/source.py` — new `fund_flow_edges(account_ids)`.
- `02_backend/data_generation/generate_synthetic_data.py` — funnel topology: second
  fingerprint cluster, collector→offshore legs, tagged source→collector transfers.

**Frontend**
- `03_frontend/src/components/AlertQueue.tsx` — bucket segmented control + counts.
- `03_frontend/src/components/CaseWorkbench.tsx` — `onDisposed`, read-only-when-closed,
  render `NetworkGraph`.
- `03_frontend/src/components/NetworkGraph.tsx` — **new**, layered SVG funnel.
- `03_frontend/src/App.tsx` — wire `onDisposed` → queue reload.
- `03_frontend/src/api.ts` — `network` on `CaseDetail`, `getAlertCounts`, status enum.

## Reuse (do not rebuild)
- Self-heal idempotent-SQL seam: `common/db.py` `get_connection()`.
- Alert list + `?status=` filter: `main.py:52` `list_alerts` (unchanged).
- SVG graph idiom (light-theme hex, viewBox, running animation): `WorkflowGraph.tsx`.
- Evidence + worker conventions: `workers.py` network worker (unchanged shape; richer data).

## Deferred / stretch (documented, not built)
- Force-directed / draggable graph (`react-flow`/`d3`) — only if free-form topologies needed.
- Multi-hop layering beyond 3 columns (source → intermediary → collector → offshore).
- SAR/STR filing workflow off the Proposed queue (today it is just a bucket + chip).

## Tests (pytest offline + `npm run build`)
- `test_dispose_routes_alert_status` — each disposition sets the mapped `alerts.status`;
  case still closes + annotation still written.
- `test_alert_status_backfill` — legacy `OPEN`-but-`CLOSED` rows get remapped; idempotent
  (second run no-ops); untouched open alerts stay `OPEN`.
- `test_alerts_counts` — `GET /api/alerts/counts` returns per-status counts.
- `test_network_graph_funnel` — `get_network_graph` on the collector returns typed nodes,
  both edge relations, fund-flow amounts; a lone account returns a single node (fail-soft).
- `test_fund_flow_edges` — aggregates transfers between the network accounts into directional
  edges with amount/count.
- `npm run build` clean; Network card renders on case open; queue buckets switch and the
  just-closed case moves Open → Proposed.

## Verification (end-to-end)
1. `pytest 02_backend/tests -q` green (new + existing).
2. Regenerate synthetic data → funnel present (two device rings + collector→offshore legs).
3. Open a case → Network card draws the funnel immediately (fund-flow arrows + device links).
4. Dispose `SUSPICIOUS` → case leaves **Open**, appears under **Proposed** with SAR/STR chip;
   `FALSE_POSITIVE` → Archived; `NEEDS_MORE_INFO` → Pending. Counts update.
5. Unlinked account → single node, no errors (fail-soft). Legacy DB → backfilled on startup.
