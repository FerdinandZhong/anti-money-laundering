# AML Demo Implementation Review — 12 September 2026

## Status after rebuild

Part 1A, 1B, and 1C are materially complete in the regenerated local scenario.
The stale SQLite database and source CSVs were deliberately replaced with a clean,
reproducible 100,276-transaction dataset, a newly trained champion, and a fresh
20-alert queue.

The anchor alert is `ALERT-ML-0466899666` for Corp_0294. It retains its monitored
window, scoring time, model version, weighted account signals, queue percentile,
and reason codes. At the validated snapshot it is the top queue item at 94.06%
(displayed as 94%, CRITICAL), produced by `v20260912_103420`. Its 30-day observed
outflow is $3,545,467.63 against stated expected monthly turnover of $421,390.

The implementation now:

1. derives observed account flow and network direction from transaction endpoints,
   rather than from the ambiguous transaction direction label;
2. uses the same explicit three-day window for scoring eligibility and the “Why
   now?” timeline;
3. persists the six weighted account signals, their contributions, queue position,
   model version, and time boundaries for every fresh alert;
4. provides local synthetic **Source of Wealth** and **Beneficial Ownership**
   documents in the workbench without representing them as a production knowledge
   base; and
5. keeps the dedicated network canvas readable by showing the strongest 12 flows
   and disclosing the count of additional flows available in the transaction view.

Backend regression tests passed (`96 passed, 2 warnings`) and the frontend
production build passed. The remaining Part 1 acceptance task is a visual
browser-review of the regenerated Corp_0294 and network journey at demo
resolution. That is distinct from the data and API verification already completed.

## OCBC paper implications

The supplied OCBC paper supports a customer-level sequence of **detection →
attribution → constrained narration → analyst feedback**. Its relevant design
lessons are:

- compare recent activity against longer customer history across multiple windows;
- retain case-specific attributions rather than showing global feature importance;
- constrain each narrative claim to named evidence and use a fixed output schema;
- measure analyst yield and capacity alongside offline model metrics; and
- treat early-warning alerts as cases for time-bounded monitoring.

It does not itself establish a recursive agent workflow, web-search process, or
customer-document knowledge base. Those remain planned pilot extensions.

## Delivery order

### Part 1 — demo-ready now

1. Make flow totals and the network account-relative.
2. Score eligible accounts only from the explicit current monitoring window and
   state the batch boundary in the workspace.
3. Persist fresh score evidence and replace the stale local data with a clean,
   reproducible dataset, model, and queue.
4. Add a local source-of-wealth document tab and refresh EN/ZH storylines.
5. Browser-review Corp_0294 and the mule-network journey at demo resolution.

### Part 2 — pilot implementation

1. Customer-level temporal feature catalogue, temporal validation, calibrated
   probability and case-specific TreeSHAP.
2. Governed document retrieval with versioned citations, approved-source external
   verification and counterparty resolution.
3. Stateful plan/collect/critique/verify workflow with targeted re-entry and
   citation validation.
4. Analyst-yield feedback, monitored-case outcomes, evaluation gates, a genuine
   canary period, and rollback verification.

Authentication/authorization and platform-wide tracing remain deliberately
deferred.
