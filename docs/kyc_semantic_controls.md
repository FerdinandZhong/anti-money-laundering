# Step 3: contextual KYC semantics and demo controls

**Historical slice documentation:** the scanned-document flow, required-source fix, ownership/activity controls and retained audit replay are now described in [the current prototype guide](kyc_audit_and_multimodal_demo.md). The limitations and commands below describe the earlier implementation.

This is a working, bounded vertical slice. It uses two existing customer/account IDs and synthetic account profiles, assertion metadata, and source records in `data/kyc_semantic_demo/`. The source records are indexed in LanceDB; control values are parsed from indexed page text, not read from the CSV's `value` column. It does not publish current SG or HK law. All executable controls are classified `DEMO`, with source labels that say synthetic institution policy example.

First build a knowledge release containing the control records, then start the app with `AML_ENABLE_KYC_DEMO_CONTROLS=1` to opt into these fictional fixtures:

```bash
python 02_backend/scripts/prepare_kyc_knowledge.py --include-control-demo
AML_ENABLE_KYC_DEMO_CONTROLS=1 python start_app.py
```

Add `--include-poc` to include the separate bilingual PDF/OCR search fixtures; add `--embedding-model-dir` for hybrid retrieval. The control records in this slice are Markdown page text. The evaluator reads from the same LanceDB page interface that holds PDF/OCR text, but the control decision has not yet been run against a newly OCR-extracted scanned source record.

Open an alert for `CUST-000294` / `ACC-0000294`, then the Semantic context tab. The panel shows the account booking context, selected historical control version, outcomes, source-field mappings, conflicting values, received dates, document version and page links. `GET /api/alerts/{alert_id}/controls` uses the alert's customer, account and cutoff from SQLite. `GET /api/alerts/{alert_id}/controls/records/{assertion_id}?release={release_id}` opens the copied original from the same scoped knowledge release. Other alerts have no demo profile and return `available: false`; disabling the environment flag also returns an unavailable state. Existing alert scores are unchanged.

| Scenario | At 2026-09-12 | At 2026-09-20 |
|---|---|---|
| SG `ACC-0000294`: `受益所有人` vs `UBO` | `CONFLICTING_EVIDENCE`: registry says Lim Wei Ming, declaration says Chen Min | Still conflicting; newer demo control version selected |
| SG `ACC-0000294`: `funding_origin` | `INSUFFICIENT_EVIDENCE`: document received after the alert cutoff | `SATISFIED`: later funding record is now known |
| HK `ACC-0000295`: controller and mandate | Both `SATISFIED` in the comparison fixture | Same if no source/control changes |

`法定代表人` explicitly maps to `legal_representative` and is explicitly **not equivalent** to `beneficial_owner`. `funding_origin` maps to source of funds, while `wealth_origin` is a separate source-of-wealth concept. `expected_monthly_turnover` is merely related to expected activity; this demo never treats it as an equivalent financial measure. Exact source, field, jurisdiction, dates and reviewed mapping status are required for an executable equivalence. Ambiguous mappings yield `REVIEW_REQUIRED`; no mapped assertion or evidence received after cutoff yields `INSUFFICIENT_EVIDENCE`.

The control response includes the knowledge release ID, cited document version/page/chunk IDs, asset hashes, and hashes for the current CSV, mapping and control-pack files. These make the input chain reviewable; immutable snapshots of all inputs and replay from retained inputs belong to Step 4. The separate existing `/api/semantic/concepts/...` discovery API still has permissive partial-name matching for exploration and must not be used for a governed control decision.

To prepare the new source tables for a manual isolated Impala check:

```bash
python 02_backend/scripts/prepare_kyc_semantic_publication.py
```

The script requires the active knowledge release with control records. It parses each assertion value from the indexed page, rejects missing or multiple values, validates keys and CSV fields, round-trips typed Parquet, and writes `artifacts/kyc_poc/semantic_publication/publish.sql` for a uniquely named `aml_kyc_semantic_demo_*` database. The six published assertions include release, document-version, chunk and asset-hash columns; their `value` columns are the extracted page values. Execute the SQL manually in the target environment only when ready. SQL insert staging is meant for six small demo assertions; it is not the final bulk CSV/Parquet upload path or an activated production source. Each generation makes a new database name, avoiding a duplicate insert on repeated tests.

Current limitations: the control pack covers ownership consistency, funding presence, HK controller presence and mandate presence only. The fixture's `verified` flags are synthetic inputs, not independent verification. The CSV supplies field labels, source association, dates and verification flags; it retains a legacy `value` column for publication comparison, but the evaluator ignores it. There is no ownership-graph traversal, currency-safe activity control, current regulatory clause review, multi-account customer scenario, corpus-wide data contracts, 12-group dataset, full historical replay, or production authorization. These remain planned work; the deterministic outcomes above must not be described as legal certification.
