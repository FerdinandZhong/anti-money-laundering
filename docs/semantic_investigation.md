# Semantic investigation — stages A and B

The investigation now prepares one alert-scoped input bundle before dispatching
workers. The Semantic context tab remains unchanged. AI Findings shows source
observations, separately labelled AI interpretations, evidence and next steps.

```text
Alert account + recorded cutoff
  → retained input bundle + semantic contracts + pinned KYC release
  → parallel profile / pattern / network / screening workers
      profile: regulatory questions → bilingual evidence searches + configured controls
      pattern: full available 30-day window → currency-separated totals + recorded model signals
      network: currency-separated fund flows + dated shared-device observations
      screening: explicit availability of dated screening results
  → optional existing MCP verification
  → deterministic summary + retained structured report
```

## Scope and calculations

Both investigation API entry points use the alert's account, not the first account
returned for the customer. The context validates the case/alert/customer match
and checks account ownership when an account source record is available. Missing
cutoffs never become the current time: historical transaction and document
retrieval becomes unavailable while regulatory questions remain available.

`source.investigation_transactions` reads the uncapped available source window
`(cutoff - 30 days, cutoff]`. It excludes known later receipts. CSV and Impala
queries use the same interval; the SQL is parameterized. The MCP source adapter's
result-size guarantee is unknown, so its totals are withheld. A complete query
is not certification of the upstream ledger. Sources without receipt timestamps
cannot establish historical ingestion-time completeness.

`account_recorded_outflow_by_currency` is declared in semantic model version 0.2.
It sums outgoing amounts using Decimal, deduplicates transaction IDs, and keeps
currencies separate. Conflicting duplicate rows or malformed amounts prevent a
complete total. Internal transfers are included. Fund-flow edges use the same
records and retain currency. Customer expected turnover remains customer-level
context; the agent does not divide an account total by it. The configured control
ledger has separate definitions and is not silently substituted for operational
transactions. The alert's saved model version/features replace the current
champion's global feature importances as the investigation's model evidence.

Dated shared-device observations are restricted to the cutoff. They establish
observed fingerprint sharing, not common ownership; ingestion-time provenance
and completeness are not certified. Customer profiles are current reads, retained
at investigation time, not historical profile snapshots.

## Regulatory questions and retrieval

The existing regulatory Ossie-style model supplies requirement meaning,
conditions, evidence types and business concepts. A known booking jurisdiction
narrows candidate requirements. Unknown booking jurisdiction retains SG and HK
questions with applicability undetermined; customer residence is not substituted.
All requirements remain condition-based, not automatic legal applicability checks.

Requirements with the same term share a search. Up to four searches combine the
term, business concepts and declared equivalent bilingual field names. Retrieval
pins one LanceDB release and filters by customer, account and alert cutoff.
Original assets are integrity-checked before snippets enter the retained bundle.
Search hits are labelled candidate evidence. They never automatically satisfy a
control or establish source agreement. The existing deterministic control engine
continues to establish configured-control outcomes, including conflicts and gaps.

## Findings and retention

Each finding has a stable run-local ID, concept, observation, source status, scope,
retained evidence reference and next step. Document findings also link to the
original asset/page; regulatory findings include meaning and clause references.

The LLM receives these findings plus semantic contracts. It may return short
interpretations keyed by supplied finding IDs. Unknown IDs, malformed JSON and
unavailable models cannot overwrite observations, calculations or statuses. The
interpretations are labelled AI suggestions: key validation is not a guarantee
that their prose is factually correct. Evaluation against the configured live
model is still required.

The final summary counts findings, conflicts, gaps and worker failures. A final
LLM call can suggest a disposition with one to three valid finding IDs; displayed
supporting observations come from those retained findings, not new prose. Invalid
citations and clearance suggestions with unresolved checks are withheld. An
unavailable model leaves the source summary available. Existing MCP verification remains
optional and fail-soft; its verdicts are not regulatory compliance decisions.

New `evidence_payloads` rows retain JSON alongside the existing hash/metadata.
The table is created idempotently on connection for existing and fresh ops DBs.
Old evidence records remain readable with `payload_available=false`. New read
endpoints verify payload hashes and enforce case scope:

- `GET /api/cases/{case_id}/evidence/{evidence_id}`
- `GET /api/cases/{case_id}/investigation/latest`

A hash detects payload inconsistency; it is not a tamper-proof archive or an
independent source attestation. Storage retention/access policies are unchanged.
The latest report restores finding cards after reload. Both streaming case and
non-streaming customer investigation endpoints use the same workflow; the latter
also returns structured findings. Inputs are retained as read, not as an atomic
transaction across external source systems.

## Deployment and validation

No new dependencies, AMP variables or CML jobs. Rebuild the frontend and restart
the application after updating source. Existing deployment/authentication applies.
Remote AMP and Impala execution remain deferred.

```bash
python -m pytest 02_backend/tests -q
npm --prefix 03_frontend run build
# Set these paths to a prepared local knowledge and semantic release:
AML_KNOWLEDGE_DIR=artifacts/kyc_poc/full_integration/knowledge \
AML_KYC_SEMANTIC_DIR=artifacts/kyc_poc/full_integration/semantic \
python 02_backend/scripts/investigation_browser_smoke.py
```

The browser script copies the ops DB, uses the real API and source records, and
stubs the LLM and external verification. It checks conflict display, original
source links, retained inputs, saved report reload and browser errors. It does
not mutate the live ops DB or claim to evaluate model quality.

## Remaining stage C

- Bounded supervisor follow-up driven by unresolved findings and alert signals.
- Configured-model evaluation of useful interpretations, factual accuracy,
  citation relevance, latency and tool-call cost against the prior workflow.
- A comparable account-level expected-activity contract where deviation ratios
  are required; certified source coverage and FX rules for converted totals.
- Dated screening source integration; current absence is explicitly unavailable.
