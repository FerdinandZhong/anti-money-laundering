# KYC evidence, controls and retained assessments

The prototype now connects real PDF/OCR extraction to LanceDB pages, strict semantic mappings, deterministic demo controls and retained control-input snapshots. It uses fictional SG/HK account profiles. All controls and thresholds are `DEMO`; no current regulatory obligation or independent identity verification is asserted.

## Current UI

Semantic context has three sections: a brief account interpretation, one
Ossie model and data-lineage graph, and optional original YAML files.
The account summary distinguishes declared profile values, observed activity
and review priority. Selecting a graph node shows its business meaning,
essential attributes, key function, physical source and declared links. The
separate LanceDB node shows PDF/OCR page indexing, retrieval and the number
of document versions received by the alert cutoff. Regulations remain in the non-executable
`aml_regulation.ossie.yaml` model and `/api/semantic/regulations` endpoint;
the simplified end-user tab does not determine legal applicability.

The KYC Documents tab shows indexed originals when available, existing Markdown
records otherwise, or a clearly labeled Markdown view of the recorded customer
profile. That profile view is not independent document verification. The local
LanceDB release covers 14 customers; only one of the current 20 open alerts has
indexed documents. The other alerts remain usable through the profile fallback.

AMP prepares PDF/OCR and the linked corpus by default. Registered CML jobs now
carry the same preparation defaults. No new job is introduced: preparation is
part of the existing generation job. Re-register existing jobs to update their
configuration before rerunning the chain.

## Prepare and run

Activate an environment with `02_backend/scripts/requirements-kyc-poc.txt`, then run:

```bash
python 02_backend/scripts/prepare_control_documents.py
python 02_backend/scripts/prepare_kyc_knowledge.py --manifest artifacts/kyc_poc/control_documents/knowledge_manifest.json
AML_ENABLE_KYC_DEMO_CONTROLS=1 python start_app.py
```

Add `--embedding-model-dir /path/to/bge-m3-onnx-int8` to ingestion for hybrid retrieval. Keyword retrieval and deterministic controls work without embeddings.

The generator creates five PDFs: the SG declaration and HK mandate are image-only scans processed by RapidOCR; the other three use native PDF extraction. Extracted text comes from document pixels/text, never CSV answer values. The full local release contains 16 documents and 17 chunks: nine earlier extraction fixtures, two legacy Markdown dossiers and five control PDFs. The earlier nine fixtures remain illustrative search samples, separate from the identity evidence used by these controls.

`prepare_kyc_knowledge.py --include-control-demo` still builds the lighter Markdown demonstration. That activates a different release; use the PDF manifest above for the scanned-document flow.

## Demonstration outcomes

Open `CUST-000294` / `ACC-0000294` in Semantic context for the account
interpretation and Ossie lineage. Open KYC Documents for indexed pages. The
controls API retains mappings, required/missing evidence, calculations and
outcomes for agent and programmatic use.

| Control at 2026-09-12 10:31:21 UTC | SG showcase | HK comparison |
|---|---|---|
| Ownership/controller assertions | Conflict: Lim Wei Ming in registry; Chen Min in scanned declaration | Satisfied |
| Funding/mandate | Funding insufficient: received September 18 | Scanned mandate satisfied |
| Disclosed ownership paths | Complete: Lim 40%; Chen 60% through a holding company | Complete: Anita 100% |
| Account external outflow, 30 days | Gap: USD 2,000 × 1.3 + SGD 100 = SGD 2,700 against SGD 1,000 expected and a demo limit of 2× | Satisfied: HKD 3,000 against HKD 10,000 expected |

The graph check assesses the supplied shareholding paths; it does not resolve the conflicting declarations or determine beneficial ownership under law. Cycles, unknown parties, unverified natural persons, invalid percentages, incomplete totals and traversal bounds require review.

Activity uses Decimal arithmetic at account grain, deduplicates transaction IDs, rejects conflicting duplicates, records dated FX IDs and excludes explicitly classified internal transfers. The SG fixture excludes an internal SGD 50,000 transfer. Declared completeness, row counts and coverage dates are checked. Missing rows/FX or a window beyond coverage cannot pass. Completeness and internal-transfer classification are synthetic source metadata. The ledger ends September 12; a September 20 reassessment can see funding but reports incomplete activity coverage.

## Partial-evidence gap fixed

Document controls declare required sources. SG ownership requires registry **and** declaration evidence. Expected, in-time assertions remain visible as missing evidence if their document, page or field disappears. Removing the declaration or its CSV metadata therefore returns `INSUFFICIENT_EVIDENCE`, with the available registry assertion retained for inspection. Empty values cannot consume the next line. OCR confidence is capped by observed page confidence.

Exact field/source/jurisdiction/date mappings distinguish representative from beneficial owner and funds from wealth. The legacy discovery endpoint still permits partial-name exploration; it does not execute these controls.

## Retain, replay and export

The backend retention API stores inputs and results in the operational SQLite table `kyc_control_assessments`. Its history endpoint returns up to 100 retained assessments per alert; replay recomputes saved inputs and export downloads the package. These backend capabilities remain available, but their action buttons and reviewer inputs have been removed from Semantic context to keep the UI focused on understanding data.

Snapshots include account scope, cutoff, full mappings/control pack, extracted values, page text/OCR boxes, missing evidence, ownership/activity/FX rows, document release/version IDs, hashes and engine version/code hashes. Replay does not rerun OCR or query live CSVs, rules, LanceDB or an LLM. Saved document links use the retained release directly. Original binary availability depends on retaining that release directory.

Content hashes detect payload corruption and scoped reads reject another alert's assessment. Review events record `CONFIRM`, `DISPUTE` or `ESCALATE` with a reason against a retained control. They form a hash-linked, retry-safe event chain and appear in the JSON export without changing the computed outcome. Local mode uses a self-declared demo reviewer ID. A private CML Application instead derives the reviewer from signed proxy forwarding of Workbench `REMOTE-USER` and requires `REMOTE-USER-PERM=RW`; a public CML app cannot write reviews. `AML_KYC_AUDIT_HMAC_KEY_FILE` seals assessments, events and the review head, detecting rewritten records or a truncated trail. The installer creates a persistent, git-ignored demo key in project storage so a fresh AMP works; production custody requires overriding it with an independently protected key. This is tamper evidence, not WORM custody or a legal retention schedule. Engine versions must remain supported for recomputation.

| Relative to `/api/alerts/{alert_id}/controls` | Purpose |
|---|---|
| `GET` | Current evaluation; optional `release` |
| `GET /records/{assertion_id}?release=...` | Current evidence's original document |
| `POST /assessments?release=...` | Retain snapshot and result |
| `GET /assessments` | History |
| `GET /assessments/{id}` | JSON audit package |
| `GET /assessments/{id}/replay` | Recompute and compare |
| `GET /assessments/{id}/records/{assertion_id}` | Retained original document |
| `GET /reviewer` | Review mode and authenticated Workbench reviewer eligibility |
| `GET/POST /assessments/{id}/reviews` | Read or append review events; private CML writes require Workbench `RW` |

The demo flag is required. Alert scope is derived on the server. Private CML review writes use Workbench identity; other API authorization remains the deployment's responsibility. MCP exposes read-only `get_kyc_controls` and `replay_kyc_assessment`. The profile worker now evaluates controls using the alert's stored customer/account/cutoff, retains the assessment, and records its result and ID as investigation evidence. Deterministic outcomes are appended outside the LLM to the profile findings and final narrative. Missing inputs, disabled controls and retention failures are explicit unavailable results. This preserves the authoritative result alongside generated prose; it is not an automatic claim checker for that prose.

## CML preparation

The AMP template now enables multimodal evidence and synthetic controls by default. Installation adds the CPU PDF/OCR runtime, including packaged OCR models. After baseline CSV export, generation creates five bilingual showcase control PDFs plus 120 bilingual corpus PDFs, runs real extraction and builds LanceDB. Legacy onboarding Markdown is included when present. This fresh-project flow does not depend on pre-existing POC artifacts. No additional job is introduced.

AMP defaults: `AML_PREPARE_KYC=1`, `AML_ENABLE_KYC_DEMO_CONTROLS=1`, `AML_KYC_DOCUMENT_MODE=pdf`, `AML_KYC_EXPANDED_CORPUS=1`, `AML_KYC_SEMANTIC_DIR=data/kyc_semantic_runtime`, `AML_KNOWLEDGE_DIR=data/knowledge`, `AML_KYC_AUDIT_HMAC_KEY_FILE=data/kyc_audit_demo.key`, with manifest and embedding paths blank. The Application explicitly disables authentication bypass and inherits project settings. Bilingual keyword retrieval is the default; a provisioned embedding model enables hybrid retrieval. Here, multimodality means native and scanned PDF evidence, OCR text/boxes and original-document links, not visual-language-model reasoning.

For the separate `cai_integration/create_jobs.py` deployment path, set these variables before registering jobs:

```bash
export AML_PREPARE_KYC=1
export AML_ENABLE_KYC_DEMO_CONTROLS=1
export AML_KYC_DOCUMENT_MODE=pdf
# Optional: use a previously extracted manifest instead of generating PDFs
# export AML_KYC_MANIFEST=/path/to/knowledge_manifest.json
# Optional: a provisioned local BGE-M3 ONNX directory
export AML_EMBEDDING_MODEL_DIR=/path/to/bge-m3-onnx-int8
```

With a supplied manifest, its PDFs must exist in project storage and preparation consumes its previously extracted pages. Without a manifest, `pdf` mode generates and OCRs documents automatically; `markdown` mode selects the lightweight text demo. Installation downloads Python packages; generation does not download external models or contact Impala. An explicitly requested preparation failure fails the generation job instead of reporting a successful new release; the previous knowledge pointer remains intact if building fails. Set `AML_PREPARE_KYC=0` to skip preparation and `AML_ENABLE_KYC_DEMO_CONTROLS=0` to disable controls. Outside AMP, an unset preparation flag preserves baseline generation behavior.

Registration forwards preparation variables to installation and generation, and the control/index/model settings through launch into the Application. Re-register existing jobs to apply these environment changes. New AMP projects use the template defaults; existing projects need their environment updated and installation/generation rerun. Local PDF/OCR bootstrap and mocked registration/application handoff are tested; actual CML execution remains unverified. Generated assets: `artifacts/kyc_poc/amp_documents/` and `amp_corpus/`; the active eight-table CSV source is `data/kyc_semantic_runtime/`; report: `artifacts/kyc_poc/pipeline_report.json`.

## Expanded retrieval corpus and benchmark

The linked corpus has **12 generated AML source customers, 30 source accounts, 60 logical documents and 120 versions**. Five bilingual families cover registry roles, account mandates, source of funds, source of wealth and periodic reviews. Four registries change their owner in revision 2; later versions have later receipt dates. Mandates and funding records belong to each group's first account, so missing evidence on other accounts is explicit. It contains 108 native PDFs and 12 image-only mandate PDFs processed with real RapidOCR. Rendering truth is stored separately and is not ingested.

The IDs are `CUST-000296`–`CUST-000307`, their generated first accounts and 18 additional `ACC-KYC-*` accounts. The normal source CSV export carries them, and the same identities appear in the versioned document index and eight semantic source tables. The local publication has 32 account profiles, 234 assertion rows, 54 ownership parties, 94 edges, 32 roots, 32 activity profiles, 34 transactions and one shared FX rate, including the original showcase rows. Source assertion values come from indexed PDFs, not the metadata CSV. The new `KYC_CORPUS` product has five evidence-presence controls plus ownership-path and activity controls per jurisdiction. A linked SG main account passes all seven at the September 20 cutoff; an intentionally anomalous fourth group reports `GAP` for activity. An extra account with no mandate/funding PDF reports missing evidence for those controls. These are synthetic coverage examples, not regulatory thresholds.

```bash
# Run in the OCR environment
python 02_backend/scripts/prepare_kyc_corpus.py
python 02_backend/scripts/prepare_kyc_knowledge.py \
  --manifest artifacts/kyc_poc/corpus/knowledge_manifest.json \
  --output artifacts/kyc_poc/corpus/knowledge \
  --embedding-model-dir /path/to/bge-m3-onnx-int8
python 02_backend/scripts/benchmark_kyc_retrieval.py \
  --root artifacts/kyc_poc/corpus/knowledge \
  --output artifacts/kyc_poc/corpus/benchmark_hybrid.json
```

The original frozen 40-query report remains an earlier prototype artifact. The current linked corpus has a frozen 168-query suite (`queries_v2.json`): 144 English, Chinese, identifier and historical positives plus 24 account/cutoff exclusions. Keyword retrieval passed **144/144 Recall@5 and 24/24 exclusions**. A separately frozen 60-question paraphrase challenge (`queries_challenge_v1.json`) exposed a gap: keyword reached **36/60 Recall@5 (60%)**, while the locally provisioned BGE-M3 hybrid index reached **60/60 (100%)**, MRR@5 0.867. Reports and query hashes are under `artifacts/kyc_poc/full_integration/`. These are synthetic document families with held-out wording, not a production or OCR field-accuracy estimate. AMP defaults to keyword until a local embedding model path is configured.

## Impala handoff

```bash
python 02_backend/scripts/prepare_kyc_semantic_publication.py
```

The script generates typed Parquet and isolated Iceberg SQL for eight tables: accounts, assertions, ownership parties/edges/roots, activity profiles/transactions and FX rates. Amounts, percentages and FX use `DECIMAL(28,8)`. Assertion values and confidence come from indexed evidence and carry release/version/chunk/hash references. Keys, references and Parquet round trips are checked. With `AML_KYC_SEMANTIC_DIR=data/kyc_semantic_runtime`, the local package has 32 account rows and 234 versioned assertion rows. Output is `artifacts/kyc_poc/semantic_publication/`: `publish.sql` uses `INSERT OVERWRITE` so retrying the same isolated database bundle does not append duplicates; `validate.sql` checks row counts and duplicate keys; `activate.env.example` names the database to select only after validation. Set `AML_KYC_SOURCE_BACKEND=impala` and `AML_KYC_IMPALA_DATABASE` to read those eight tables through the same assessment contract. Explicit Impala mode fails if unavailable. Remote publication and parity execution remain deferred to the user.

## Validation and remaining scope

Regressions cover partial source loss, empty fields, late evidence, scope isolation, immutable versions, poisoned CSV values, ownership cycles, missing ledger rows/FX and snapshot corruption/replay. `02_backend/scripts/kyc_browser_smoke.py` exercises the built frontend and real FastAPI routes against a temporary ops database copy. Artifacts and actual OCR/control results are in `artifacts/kyc_poc/control_documents/`.

Current validations cover the linked account/CSV keys, strict Impala adapter selection, real OCR bootstrap, scoped retained review event integrity, browser review/export flow and typed local publication. Actual CML/Linux runtime and remote Impala execution remain unverified.

The official MAS 626 (30 June 2025 revision) and HKMA AML-2 editions and selected clause locations are now verified and versioned as non-executable source candidates. [The clause review packet](kyc_regulatory_review_packet.md) details the evidence gaps. Remaining decisions: institutional approval of applicability and interpretation, protected audit-key provisioning and independent retention/legal-hold infrastructure. Actual CML/Linux execution and remote Impala publication/parity remain user-deferred. Parsing still expects labeled fields; arbitrary document understanding and native image/diagram reasoning are outside this implementation. [Audit concept linkage](kyc_audit_concept_linkage.md) shows the current scope and governance boundary.
