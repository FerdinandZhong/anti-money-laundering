# Multimodal KYC and auditable regulatory semantics

Status: proposed implementation plan, 2026-09-23. This document is the deliverable for the planning request; application behavior has not been changed.

## Intended outcome

An investigator opens an account and can answer: which KYC facts are supported by which document pages, which regional obligations apply, how regulatory terminology maps to business fields, where evidence conflicts or is missing, and how the assessment can be reproduced later.

Build the two requirements as one evidence-to-control workflow:

`Business records + KYC documents → provenance-backed facts → contextual semantic mappings → applicable controls → findings → analyst review + replayable audit package`

Retrieval finds evidence. Versioned code evaluates approved controls. The LLM explains findings with citations. The existing ML score continues to rank alerts; a control gap is not a determination of financial crime.

## Findings from the repositories

| Area | Observed implementation | Consequence |
|---|---|---|
| Vehicle knowledge base | `../vehicle_manufacturing_blueprint/02_backend/knowledge/kb.py` uses `lance.write_dataset`, binary assets, ontology validation, caption embeddings, and brute-force cosine search | Reuse its asset/provenance pattern, but it is direct Lance rather than the LanceDB API, and caption search is not image understanding |
| Vehicle embeddings | Cached MiniLM with token-hash fallback; backend selected implicitly | Pin the embedding backend, model revision and dimension per index; never compare vectors from different embedding spaces |
| AML KYC generation | `02_backend/data_generation/generate_synthetic_data.py::write_demo_kyc_documents` writes two Markdown documents for one customer | Need actual PDFs, scanned pages, ownership diagrams and structured attachments |
| AML KYC retrieval | `02_backend/common/source.py::customer_kyc_documents` reads only local Markdown | Add versioned asset access and page-level search while preserving existing clients |
| Identity model | Customer has one `beneficial_owner` string; accounts lack booking entity/jurisdiction | Cannot represent layered ownership or determine account-specific regulatory applicability |
| Semantics | `02_backend/semantic/resolver.py::resolve_concept` returns the first exact/partial match | Ambiguous concepts can be silently resolved incorrectly |
| Metric execution | Context sums customer-account outbound amounts, has a 5,000-record/account cap, and does not normalize currencies in that sum | More complex data requires explicit grain, FX rules, complete aggregation and incomplete-data status |
| Audit evidence | `02_backend/common/evidence.py` stores payload hashes and a data-version string, not payload snapshots | Hashes alone cannot replay historical findings |
| Existing narrative | `source_of_wealth.md` primarily describes operating revenue and expected turnover | Model source of wealth, source of funds, and expected activity separately |

## 1. Synthetic multimodal KYC corpus

### Proposed first-release scope

Use a fixed seed and fixed scenario clock. Enrich 12 selected customer groups, including the current showcase customer, with approximately 30 accounts and 120 documents/versions. Keep the wider existing transaction dataset. Use Singapore and Hong Kong booking entities; include China and Malaysia counterparties/ownership links without implying that their domicile alone determines the account's governing obligations.

Create fictional names, identifiers and institutions with visible `SYNTHETIC DEMO` markings. Use reference documents for field structure, not copied customer records or purported QCC/registry-issued reports.

| Document family | Formats | Evidence purpose |
|---|---|---|
| Company profile / registry-style extract | Native PDF + structured JSON | Registered names, original script, identifiers, legal form, status, registered address, directors, filing dates |
| Incorporation / registration record | PDF + scanned PNG | Identity evidence; distinguish historic incorporation from current existence |
| Ownership declaration and register | PDF, CSV table, SVG/PNG ownership chart | Direct/indirect stakes, control roles, nominee relationships and historical changes |
| Account-opening and mandate forms | PDF + scan | Account purpose, expected activity, signatory authority and approval |
| Address evidence | Utility/lease-style PDF and scan | Registered, operating, mailing and residential address distinctions |
| Source-of-funds / source-of-wealth evidence | Separate declarations, statements, financial extracts | Funding of particular activity versus accumulated wealth; provenance and corroboration |
| Trade support | Invoices, purchase orders, shipping-document-style PDFs | Counterparty, amount, currency, purpose and transaction reconciliation |
| Screening and review records | HTML/PDF/JSON | Candidate matches, disambiguation, timestamps, reviewer rationale and unresolved evidence |

Include native text, tables, diagrams and image-only pages; English and Chinese; transliterations; rotated/blurred scans; expired and superseded documents; incomplete pages; and deliberate cross-source discrepancies. Do not add audio/video without a relevant investigation use case.

Generate a coherent underlying scenario first, then render source-specific records and controlled discrepancies. Store scenario truth separately from runtime evidence. Extraction must not read generator truth or answer labels. Provide a labeled `fixture` extraction mode for offline demonstrations and a separate OCR/parser evaluation mode that measures actual extraction.

### Source and fact model

Add source tables behind `common/source.py`, with equivalent CSV and Impala schemas:

- `parties`, `party_identifiers`, `party_aliases`, `party_addresses` with identifier/address types and valid dates.
- `ownership_edges` with ownership/voting percentages, control type, role, validity, and evidence reference.
- `account_regulatory_profiles` with booking legal entity, branch, jurisdiction, product, customer type and relationship dates.
- `kyc_reviews`, `expected_activity_profiles`, `funding_sources`, `wealth_sources`, `account_mandates`.
- `document_manifest`, `document_versions`, `extracted_facts`, `screening_results`, `fx_rates`.

Preserve raw field names and values. Each normalized fact records source-system/record/field, raw value, canonical concept, normalized value and unit, document/page/bounding box where relevant, extraction method/version/confidence, effective time and observed time. Conflicting facts coexist with explicit resolution state; ingestion must not silently overwrite them.

### LanceDB implementation

Use embedded LanceDB over Lance storage for the new AML knowledge module. Reuse the vehicle project's source/ops/knowledge separation, ontology-linked assets, deterministic IDs and explicit provenance. LanceDB adds a supported hybrid-search path; see [official hybrid-search documentation](https://docs.lancedb.com/search/hybrid-search).

- `kyc_assets`: document/version IDs, customer/account/party links, MIME type, hash, source, language, validity and access scope. Store small demo binaries directly; support content-addressed object URIs for larger/Ozone-backed assets.
- `kyc_chunks`: page/section/table chunks, extracted text, page coordinates, entity links, validity, embedding metadata and vectors. Retrieve metadata/snippets; fetch binaries separately.
- `regulatory_chunks`: a separate corpus with issuing authority, instrument/version, clause, jurisdiction, institution/product applicability, publication/effective dates, source URL and hash.
- Pre-filter by authorized customer/account scope and applicable dates; combine exact identifier lookup, full-text search and semantic retrieval. Apply deterministic tie-breaking and deduplicate copies of the same source evidence.
- Pin an explicitly configured embedding model/revision/dimension and preprocessing version in an index manifest. If unavailable, retain lexical/structured retrieval with a visible degraded status; do not silently replace semantic embeddings with hash vectors.
- Start with text/OCR retrieval across multimodal documents and a page viewer. Add a separate image/text embedding index only with a visual-retrieval benchmark; describe caption/OCR retrieval accurately.
- Build and validate a new corpus generation before activating it. Keep old document and index versions referenced by audit snapshots; do not blindly overwrite the only copy.

## 2. Regulatory semantics and audit complexity

### Meaning requires context, not just synonyms

| Business/document expression | Canonical concept | Mapping constraint |
|---|---|---|
| `acct_holder`, `client_no`, `CIF` | Customer/party and identifier | CIF identifies a customer record; account and legal person remain distinct entities |
| `UEN`, company number, `统一社会信用代码` | Legal entity identifier | Preserve issuer, jurisdiction and identifier scheme; these values are not interchangeable |
| `shareholder`, `实控人`, `UBO`, `legal_representative` | Ownership interest / controlling person / beneficial owner / representative | Separate relationships; legal representative or shareholder does not automatically establish beneficial ownership |
| `mail_addr`, `reg_addr`, `business_address` | Mailing / registered office / principal place of business | Addresses may legitimately differ; use the role required by the obligation |
| `monthly_sales`, `expected_credit`, `expected_monthly_turnover` | Revenue / expected inflow / declared activity | Compare only compatible grain, direction, currency and period |
| `funding_origin`, `wealth_origin` | Source of funds / source of wealth | Distinct concepts with distinct evidentiary needs |
| `risk_rating`, model score, PEP candidate hit | KYC risk tier / ML priority / screening candidate | No shared numeric meaning; a candidate hit is not a verified match |
| `last_updated`, `review_completed_at` | Record modification / completed KYC review | Updating a row does not demonstrate a completed review |

Introduce `semantic/aml_source_mappings.yaml` and extend the three existing semantic contracts. A mapping carries source path, canonical concept, relationship type (`equivalent`, `narrower`, `related`, `not_equivalent`), transformation, units/grain, contextual predicates, provenance, effective dates and version/review status. Similarity can propose candidates, but only published mappings execute. Resolution returns resolved, ambiguous, unmapped or unsupported-context outcomes; remove first-match partial resolution for governed decisions.

### Regulatory applicability and control packs

Select rule packs by booking legal entity/branch, regulated activity, customer/legal-person type, product, relevant event and assessment time. Record why a rule applies or does not apply. Cross-border facts may trigger additional checks; customer country is not a substitute for applicability logic. Combine applicable obligations explicitly; unresolved conflicts go to review.

Keep three types distinct: regulatory obligation, institutional policy, and synthetic demo assumption. No invented universal ownership percentage, refresh interval, or retention period. An executable rule needs an exact source version/clause, reviewed interpretation, applicability predicate, required evidence, parameters, calculation, exceptions, and expected outcomes. Text search does not publish executable law.

Start with bounded controls for identity/current existence, beneficial ownership and control, mandate authority, document validity, KYC review requirements, expected versus observed activity, screening review evidence, source-of-funds/wealth evidence, and record retention/retrievability. Model ownership percentages along supported paths with cycle detection; control through other means is a separate relation, not a percentage shortcut.

Outputs: `SATISFIED`, `GAP`, `INSUFFICIENT_EVIDENCE`, `CONFLICTING_EVIDENCE`, `NOT_APPLICABLE`, `REVIEW_REQUIRED`. These are assessments against the selected control, not legal certification or proof of crime. Missing/low-confidence inputs and retrieval outages must never yield a passing result.

### Metrics that demonstrate the semantic layer

- Evidence-backed CDD coverage = satisfied applicable controls / all applicable controls; separately show unknown applicability, gaps and insufficient evidence.
- Beneficial-owner verification coverage = verified identified owners / identified owners, accompanied by an ownership-completeness flag. Unknown ownership cannot report 100% coverage.
- Review overdue days calculated using the applicable policy/rule version and historical assessment date, not a generic `last_updated` field.
- Unresolved document/business discrepancy count and age, deduplicated by underlying fact conflict.
- Expected/observed activity deviation with explicit customer/account grain, flow direction, currency, FX date/source and window. No turnover-versus-outflow equivalence unless the profile definition supports it.
- Audit traceability coverage = findings with a complete source/mapping/rule/input chain / findings assessed.

Move aggregate calculations to complete source-side queries or bounded paginated aggregation. Return row coverage and incomplete-data state when capped or missing; never present partial totals as complete. Use decimal currency arithmetic and documented FX conversion. Transaction truth labels remain excluded from investigation evidence and runtime feature inputs.

### Replayable audit trail

Extend ops storage with `control_assessments`, `assessment_inputs`, `finding_evidence_links`, `review_actions` and an evidence-snapshot manifest. Retain payload snapshots or immutable content-addressed references alongside hashes. A finding records:

`case/account + assessment/as-of times + applicable rule/clause/version + mapping version + source snapshot + document/page/fact links + calculation inputs/output + code version + extraction/index versions + reviewer decisions`

Separate what was effective at the time from what was known at the time. Support both historical replay and an explicitly labeled later reassessment. Preserve corrections and analyst overrides as new events with actor, reason and before/after state. Export JSON plus a readable report and evidence manifest. Local hashes and append-only application behavior support reproducibility; production immutability requires access-controlled retention/object-lock facilities, not just SQLite or a hash.

## 3. Integration and investigator experience

- Add `02_backend/knowledge/{kb,ingest,retrieval}.py`, `02_backend/compliance/{applicability,evaluator,audit}.py`, and document/scenario generators. Extend existing `common/source.py`, schema/migrations, semantic resolver and tests.
- Add customer-scoped document list/search/page/asset routes; account-scoped control assessment and finding-explanation routes; case audit-export routes. Publish matching MCP tools. Derive scope from the authorized case, not just a client-supplied filter. Validate IDs, MIME types, file access and document authorization at both search and asset retrieval.
- Extend profile and screening workers to consume cited facts and deterministic assessments; preserve network/pattern responsibilities. Verification checks fact/rule citations and unresolved conflicts. LLM prose cannot change control outcomes, mappings or alert scores.
- Upgrade `CaseWorkbench.tsx` with PDF/image preview, page-level highlights, extracted facts, source/version badges and discrepancy comparisons. Extend `SemanticExplorer.tsx` to show business term → mapping → canonical concept → control → evidence. Add a control matrix and audit timeline/export.
- Preserve the legacy Markdown document response during migration. Old cases lacking snapshots must show `legacy/non-replayable`, rather than fabricated historical evidence.
- Add deterministic corpus preparation to the existing generate job, including index build after document/fact generation. Preserve the CML `__file__` guard and source/ops separation. If a distinct new job is needed later, update `jobs_config.yaml` and rerun `create_jobs.py`.
- No LLM/Impala/embedding service: use template narration, configured CSV source and lexical/structured evidence access. Missing knowledge assets produce an explicit unavailable state without crashing the workbench. Never mix synthetic fallback records into a real production case silently.

## 4. Scenario and acceptance matrix

| Scenario | Required behavior |
|---|---|
| English trading name vs Chinese registered name | Resolve through identifier/alias evidence; never name similarity alone |
| Legal representative mistakenly treated as UBO | Reject equivalence; show missing ownership/control evidence |
| Layered ownership, nominee or ownership cycle | Explain traced paths and unresolved control; no invented terminal owner |
| Registry status differs from customer declaration | Show both dated facts and the supporting document pages |
| Mailing and registered addresses differ | Respect address roles and avoid an automatic discrepancy finding |
| Expired document or unreadable scan | Return the appropriate evidence gap/uncertainty, not a pass |
| Operating revenue offered as wealth evidence | Preserve the source-of-funds/source-of-wealth distinction |
| Multiple accounts, currencies and internal transfers | Correct grain, direction, FX and deduplication; no raw currency sums |
| Similar-name screening hit | Candidate review, with identifier disambiguation; no automatic confirmed match |
| Rule or ownership change after alert cutoff | Historical result remains reproducible; later reassessment is separate |
| Genuine clean dossier | Correctly satisfied controls and no artificial discrepancy |
| Missing rule pack, scope denial or service outage | Explicit unavailable/review state; no cross-customer leakage or passing-by-default |

Target a 40-query benchmark spanning English, Chinese, identifiers and ambiguous terms: at least 90% Recall@5 for evidence retrieval, 100% correct explicit ambiguity handling on curated cases, and zero unauthorized cross-customer results. Measure fixture lookup and real OCR extraction separately. Verify all expected deterministic control outcomes; all findings must have complete rule/input/source references or be explicitly insufficient. Replay must reproduce outcomes after source/rule updates. Check schema migrations and CSV/Impala contract parity, existing scorer/semantic/API regressions, frontend build, and an end-to-end offline investigation/export.

## 5. Delivery order

| Phase | Concrete deliverable | Exit criterion |
|---|---|---|
| 1. Contracts and vertical-slice fixtures | Entity/document schemas, mapping contract, rule-pack schema, one SG and one HK account scenario | Hand-worked expected findings, applicability and citation chain specified |
| 2. Corpus and retrieval | PDF/scan/table/diagram generator, LanceDB index, document APIs and viewer | Seeded artifacts reproducible; scoped search and real page citations work |
| 3. Semantics and controls | Contextual mappings, ownership traversal, deterministic evaluator, currency/grain-safe metrics | Scenario outcomes and ambiguity tests pass; missing evidence never passes |
| 4. Audit and investigation | Snapshot persistence, replay/export, worker/MCP integration, control and lineage views | One account can be investigated and its historical assessment replayed end to end |
| 5. Breadth and deployment | Full 12-group corpus, 40-query evaluation, migrations and CML preparation | Acceptance matrix, regression tests, frontend build and offline smoke test pass |

Implement the first vertical slice around the existing showcase customer: declaration and registry-style record disagree about control; a representative is incorrectly stored as beneficial owner; one account is booked in SG and another in HK. Show the mapping distinction, account-specific applicability, documentary conflict and replayable finding. Then expand coverage using the same contracts.

## Reference grounding and remaining decisions

- [QCC company-search description](https://www.qcckyc.com/news-detail/qcc-free-company-search): reference for registration, officers, ownership links and risk signals. The page describes a product; it is neither a downloaded customer dossier nor a regulatory source. No live QCC integration is assumed.
- [ACRA sample business profile](https://www.acra.gov.sg/docs/default-source/bp-and-bc/business-profile---business-v12.pdf): public structural reference for registry-style documents. Generate new synthetic content and do not imply ACRA issuance.
- [HKMA AML-2, revised May 2023](https://brdr.hkma.gov.hk/eng/doc-ldg/docId/getPdf/20230525-4-EN/AML-2.pdf): inspected reference for customer verification, document currency and record-keeping. Sections 4.3.7/4.3.14 and 8.3 provide useful initial control examples. Pin this edition as a source snapshot; confirm applicable amendments before publishing a current rule pack.
- [MAS Notice 626 landing page](https://www.mas.gov.sg/regulation/notices/notice-626): returned a maintenance page during research. Singapore rule thresholds and current clause text remain unverified. Obtain the applicable official edition before publishing regulatory controls; until then use explicitly labeled institutional/demo controls or an unavailable rule-pack state.
- [LanceDB hybrid search](https://docs.lancedb.com/search/hybrid-search): verified capability reference; pin/test a compatible dependency version during implementation.

Planning assumptions: SG/HK first, corporate KYC/KYB first, English UI with bilingual evidence, embedded local LanceDB, no paid vendor/API dependency. Macau/other jurisdictions, production SSO/ABAC integration, live registries and image embeddings are follow-on scope. These assumptions are adjustable without changing the core evidence/mapping/audit contracts.
