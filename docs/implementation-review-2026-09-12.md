# AML Demo Implementation Review — 12 September 2026

## Status at review

The investigation workspace and the Corp_0294 synthetic storyline were largely
implemented, but the local database still contained an earlier alert batch. That
batch had no persisted score inputs, chronology fields, or Corp_0294 baseline
transactions. It could not support the improved demonstration faithfully.

The review found four Part 1 gaps to close before rebuilding the demo:

1. **Account-relative flow semantics.** A transaction's `direction` can describe
   the receiving account. Outflow and network direction must instead be derived
   from `from_account_id` and `to_account_id` relative to the selected account.
2. **Chronology consistency.** The score explanation must use the same monitored
   period that the “Why now?” timeline presents. The UI must not claim a historical
   threshold crossing that was not persisted.
3. **Reproducible score evidence.** Every freshly created alert must retain the
   account inputs, their contributions, the monitored batch rank, model version,
   and time boundaries. Compatibility arithmetic for older alerts is not a model
   explanation.
4. **KYC context.** The workbench needs a lightweight, local source-of-wealth
   document view for the demo customer, without presenting it as a production
   knowledge base.

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
