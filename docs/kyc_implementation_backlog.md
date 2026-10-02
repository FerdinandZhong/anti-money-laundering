# KYC implementation backlog and confidence assessment

Planning deliverable · 2026-09-24. This backlog describes the full target; the implemented Step 2 retrieval slice is documented in [the knowledge backend guide](kyc_knowledge_backend.md), and the first Step 3 control slice in [the semantic controls guide](kyc_semantic_controls.md). Remaining gates below are not implied complete by those slices.

Inputs: [feature plan](kyc_multimodal_regulatory_semantics_plan.md) and [table catalog / schema diagrams](kyc_data_catalog_and_schema.md). The catalog defines the target data model; this backlog defines execution order and release gates.

2026-09-25 prototype milestone: required-source completeness fixed; actual scanned PDFs drive controls; retained input replay/export, bounded ownership traversal and decimal activity/FX checks are implemented. Eight typed tables have local publication artifacts. See [the current prototype guide](kyc_audit_and_multimodal_demo.md) for demonstrated scope and remaining full-plan gates. Remote Impala execution remains deferred.

## Scope and delivery strategy

2026-09-26 continuation: profile-worker retained assessments and deterministic narrative appendix are implemented. Optional knowledge preparation is wired into the existing generation job, with environment propagation through CML registration and Application launch. An isolated 12-group/30-account/120-version retrieval corpus and frozen 40-query benchmark are implemented; first hybrid run passed 36/36 Recall@5 and 4/4 scope/time checks. These corpus identities are not yet operational/semantic fixture enrichment. Actual CML execution and full CSV/Impala source parity remain pending. See the current prototype guide for commands and limits.

Later 2026-09-26 implementation: corpus IDs are linked to deterministic generated AML customers and accounts, and AMP now prepares 120 PDF versions plus five showcase PDFs by default. The extended semantic source has 32 account profiles and 234 assertion rows, read from CSV or explicitly selected Impala. Local Iceberg preparation emits typed Parquet, retry-safe overwrite SQL, validation queries and an activation environment file. SG/HK `KYC_CORPUS` demo packs cover registry, mandate, funds, wealth and periodic-review evidence. Review events are separately retained and hash-linked. The frozen 168-query linked suite passed 144/144 positives and 24/24 exclusions; a frozen 60-question paraphrase challenge passed 36/60 keyword and 60/60 hybrid. Candidate official source pointers remain non-executable pending institutional legal review. Actual CML and remote Impala execution remain unverified.

Deliver the agreed 12 enriched customer groups, approximately 30 accounts and 120 document versions, while retaining the existing baseline dataset, scorer-owned alert creation, investigation workflow and ModelOps behavior. CSV and Impala must expose the same source contract. Live case state stays in SQLite; knowledge assets/indexes use LanceDB and versioned object references.

First prove a complete flow for the existing showcase customer with SG/HK accounts and a clean comparison customer. Include representative-versus-owner ambiguity, conflicting documents and evidence received after the original cutoff. Then expand to the full corpus. All table contracts can be declared early; populate and implement each table family with its feature rather than creating an unused application layer around every table at once.

## Ordered implementation work

### 0. Establish baseline and resolve environment uncertainty

- Record existing backend/MCP tests and frontend build results using temporary databases. Classify any pre-existing failures before changes; keep unrelated workspace edits out of the feature work.
- Check local and CML Python/runtime compatibility. In an isolated environment, pin and test LanceDB/PyArrow and the chosen document/PDF/OCR dependencies. Exercise table create, reopen, scoped retrieval and unavailable-embedding behavior.
- Evaluate extraction on a small fixed set of English/Chinese native PDFs and scans, including rotation, blurred text and a table. Report actual extracted fields and failures; do not substitute generator truth.
- Perform read-only target Impala preflight when access is available: runtime, catalog/HMS, schema visibility and storage configuration. Build the isolated publication package before any remote writes. An unavailable cluster does not block local feature work, but leaves warehouse acceptance pending.
- Verify official regulatory editions and review status separately from dependency setup. The earlier MAS retrieval failed; current Singapore rules remain unpublished until verified. Continue local testing with explicitly labeled demo/policy controls.

Gate: baseline recorded, local dependency proof completed, extraction limitations measured, and external dependencies explicitly classified. No unexplained assumption is labeled verified.

### 1. Shared schema contract, history and safe migration

New: `config/data_contracts/aml_v2.yaml`, `02_backend/common/data_contracts.py`, release-manifest utilities and explicit SQLite migrations.

Extend: `02_backend/data_generation/schema.py`, `02_backend/common/source.py`, `02_backend/scripts/export_source_csv.py`, shipped config example.

- Encode table grain, logical keys, nullability, enums, decimal precision, typed CSV codecs and valid/recorded time semantics.
- Replace duplicated four-table source lists with one allow-listed registry; add feature-specific completeness checks and release-aware caches.
- Preserve existing customer/account/transaction responses and IDs. Backfill legacy owner strings as unverified assertions; unknown booking jurisdiction stays unknown.
- Treat a data release as immutable input. Feature flag the enriched investigation path and make schema changes additive.

Gate: CSV/Parquet round-trip of multilingual strings, nulls, identifiers and decimals; duplicate/dangling-key rejection; historical cutoff behavior; repeat migration succeeds on a copied legacy DB. Existing source/semantic/scorer tests remain passing or have a documented intentional contract change.

### 2. Scenario and document generator

New: `02_backend/data_generation/kyc_scenarios.py`, `generate_kyc_documents.py`, document templates and test-only expectations.

- Generate internally coherent parties, accounts, ownership, mandates, KYC profiles, reviews, screening snapshots and FX observations.
- Produce PDF, scan, diagram and table evidence from scenario records; inject controlled discrepancies through declared scenario parameters.
- Stable IDs, seeded content, pinned scenario time and reproducible document metadata. Keep operational export timestamps outside canonical fixture content hashes.
- Save manifests and original record snapshots. Keep truth labels outside source releases, extraction inputs and search indexes.

Gate: two scenario groups render correctly; document references resolve; repeated generation has equal canonical hashes; clean and discrepancy cases have hand-specified expected findings. Expand to 12 groups after the vertical slice passes.

### 3. Extraction, LanceDB retrieval and document access

New: `02_backend/knowledge/ingest.py`, `kb.py`, `retrieval.py`, extraction adapters and index manifest.

Extend: customer KYC API routes and response types, preserving legacy fields during migration.

- Separate fixture extraction mode from measured parser/OCR mode. Retain original text, normalized assertions, page coordinates, extraction versions and confidence.
- Separate assets, KYC chunks and regulatory chunks. Pin model/revision/dimension; no automatic substitution into an incompatible embedding space.
- Exact identifier lookup plus full-text/vector search; scope before ranking, stable tie-breaks, source deduplication and explicit degraded lexical mode.
- Asset retrieval validates the same case/customer context as search. A document association is not an authorization grant. Reuse the app's available identity context; full enterprise SSO/ABAC is a separate integration requirement if absent.

Gate: page citations open the intended file version; invalid IDs/path traversal and cross-customer requests are rejected; missing model/index does not crash the workbench. Freeze a 40-query benchmark before retrieval tuning; target at least 90% Recall@5, with English/Chinese and exact-ID results reported separately. OCR accuracy is reported independently of retrieval and fixture performance.

### 4. Contextual semantics and deterministic controls

New: `semantic/aml_source_mappings.yaml`, control-pack definitions, `02_backend/compliance/applicability.py` and `evaluator.py`.

Extend: existing ontology, semantic model, context registry and resolver.

- Return explicit resolved/ambiguous/unmapped/unsupported outcomes; remove first-partial-match behavior for governed decisions.
- Select controls by account booking context, product/customer type and historical dates. Preserve REGULATORY/POLICY/DEMO distinctions and clause provenance.
- Implement bounded identity, ownership/control, authority, document validity, review evidence and activity checks first; then funding/wealth, screening and record-evidence controls.
- Ownership traversal detects cycles and uncertainty. Do not equate a representative with an owner or infer missing natural persons.
- Correct financial metric grain, decimal/FX handling, internal-transfer policy and complete aggregation. A capped query yields incomplete status, not a passing result.
- LLM narration cannot modify controls, mappings, outcomes or alert scores.

Gate: curated cases produce exactly the specified outcomes; missing evidence/rules and ambiguous terms never silently pass. Same facts with a different applicable rule version can produce a traceable, independently reproducible result. Unsupported controls remain visibly review-required.

### 5. Audit replay and the first complete investigator flow

New: `02_backend/compliance/audit.py`, assessment/result/input persistence, audit-export and replay utilities.

Extend: `common/evidence.py`, agents/tools/workers, FastAPI routes, MCP tools, `CaseWorkbench.tsx`, `SemanticExplorer.tsx`, frontend API types. Add focused document viewer/control matrix/audit timeline components.

- Persist source snapshots or immutable references together with hashes, dataset/mapping/rule/code versions, valid/known cutoffs and calculation inputs.
- Cite findings to original page/record; display conflicting assertions together and show the mapping used.
- Record analyst overrides as new events with actor and reason. Legacy cases lacking snapshots are labeled non-replayable.
- Narration has a deterministic fallback. Add document-to-finding navigation and JSON/readable audit exports.

Gate: investigate the showcase account, inspect the contradictory documents, explain the terminology distinction, record a review action and export the audit package. Change current documents/rules and replay the original result unchanged. A later reassessment is a new run. Frontend build and API/MCP contract tests pass.

### 6. Impala publisher and backend parity

New: `02_backend/scripts/prepare_source_release.py`, `publish_impala_release.py` and generated staging/target DDL. Names are proposed, not existing commands.

- Generate typed Parquet and warehouse DDL from the same contract as CSV.
- Publish into a new isolated namespace using cluster-accessible staging storage; retain a manifest of per-table snapshots, hashes and row counts.
- Use one publisher per release, explicit retry/idempotency rules and activation only after all validations. Failed loads leave the previous release active.
- Pin each assessment to one release. Support rollback to the previous manifest; handle backend/cache switching explicitly.
- Export SQLite audit events incrementally with stable event IDs and committed watermarks. This is a reporting mirror, not a second case write authority.

Gate: on the actual target cluster, compare CSV/Impala logical rows, decimals and representative control results; verify duplicate-free retry, interrupted-publication isolation and rollback. DDL generation alone does not count as Impala support validated.

### 7. Full corpus, CML integration and release

- Expand to all 12 groups and the complete planned scenario matrix. Verify baseline alert/scoring behavior after fixture changes rather than assuming it is unchanged.
- Add document/index preparation to the existing generation chain where practical. If adding a separate warehouse publication job, update `jobs_config.yaml` and register through `create_jobs.py`. Keep new entry scripts compatible with Jupyter kernels lacking `__file__`.
- Update installer/dependencies, configuration, API docs, user guide, demo storyline and handoff. Test startup with no LLM, no Impala and unavailable embeddings; never mix synthetic fallback records into a production case silently.
- Run affected tests during development, then one full backend/MCP regression and frontend build at release. Do a browser-based investigation/export check and the CML smoke test. Repeat checks only when changes or unresolved failures justify them.

Gate: feature acceptance matrix and 40-query evaluation recorded against the delivered release; local demo accepted; target Impala and CML acceptance reported separately; rollback exercised. No production-ready claim based only on a local demo.

## Dependencies and packaging

Sequence: `0 → 1 → 2 → 3 → 4 → 5 → 7`; warehouse work `6` can begin after `1` and finishes before warehouse release acceptance. Regulatory source verification starts in `0` and gates publication of regulatory controls in `4`, not synthetic fixture work.

Use reviewable changesets for contracts/migrations, generation, retrieval, semantics/controls, audit/UI, and publisher/deployment. Define the assessment snapshot shape in phase 1 even though replay lands in phase 5. This avoids an evidence retrofit. Keep the full scope in the backlog; the first end-to-end demonstration is a milestone, not completion of the entire request.

## Confidence, grounded in current evidence

These are engineering judgments about delivering the stated scope, not measured success probabilities or claims that features already work.

| Feature | Confidence now | Evidence / remaining uncertainty | What raises confidence |
|---|---|---|---|
| Typed synthetic records and CSV releases | High | Existing deterministic scenarios/export path; new history and schema breadth need implementation | Reproducibility, integrity and round-trip tests |
| Synthetic PDF/scan/diagram corpus | High | Controlled fictional inputs and bounded templates | Visual review, page/manifest validation |
| Contextual mappings and bounded controls | High | Existing semantic contracts/resolver and unit-test seams; rules can be explicit pure functions | Ambiguity, negative and temporal scenario tests |
| Audit snapshots and replay | Medium-high | Existing evidence/case structures, but payload retention is currently absent | Replay after source change and deliberate hash-corruption test |
| Document viewer and API/MCP integration | High | Existing KYC tab, semantic explorer, APIs and MCP surface | Browser flow, frontend build, tool contract checks |
| LanceDB scoped hybrid retrieval | Medium-high | Vehicle Lance asset pattern and documented retrieval approach; AML integration not run | Pinned dependency smoke test and frozen bilingual retrieval benchmark |
| English/Chinese OCR on degraded scans | Medium | No extraction evaluation yet; layout/language/scan quality matter | Independent measured extraction set, field-level errors and abstention behavior |
| Target Impala publication and parity | Medium | Existing Impala read adapter; no publisher or tested target DDL | Cluster preflight, isolated load, parity and failure-recovery tests |
| Current regional regulatory correctness | Conditional | Source verification and interpretation remain incomplete, especially Singapore | Exact official editions/clauses and reviewed applicability before publication |

Overall: high confidence in delivering the scoped local demonstration; medium confidence in the complete warehouse deployment until target-environment tests pass. Regulatory authority is a separate acceptance condition, not something a confidence score can replace. Native cross-modal image similarity, live registry feeds, broad jurisdiction coverage and production identity/retention integration remain follow-on scope as previously stated.

## Completion evidence to retain

Release manifest; fixture/schema integrity report; extraction evaluation distinguishing fixture and real OCR modes; frozen retrieval-query results; deterministic control expected/actual report; audit replay and corruption checks; API/MCP regression results; frontend build and browser-flow evidence; CSV/Impala parity and publication-recovery report; CML smoke result. Tests use temporary databases/releases and do not overwrite the working demo.
