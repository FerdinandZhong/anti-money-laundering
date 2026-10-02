# Bilingual extraction and isolated Impala publication POC

Executed 2026-09-24. Extraction and local serialization completed. Remote Impala execution was blocked before authentication by DNS resolution. No remote objects were created and no application dataset/configuration was changed.

## Extraction results

Actual PDF extraction with PyMuPDF and actual image OCR with RapidOCR/ONNX Runtime, running locally on CPU. Three document languages (English, simplified Chinese, mixed) each have a native PDF, clean image-only scan (220 dpi), and blurred/rotated scan (120 dpi, Gaussian blur 0.8, rotation 2 degrees). Nine pages total; seven named fields and a two-row ownership table per page. Scanned PDFs are checked to contain no hidden text layer. No LLM or external OCR API was used.

| Input | English fields | Chinese fields | Mixed fields | Exact ownership tables |
|---|---:|---:|---:|---:|
| Native PDFs | 7/7 | 7/7 | 7/7 | 3/3 |
| Clean scans | 7/7 | 7/7 | 7/7 | 3/3 |
| Blurred/rotated scans | 6/7 | 6/7 | 4/7 | 3/3 |

Clean/native gate: **42/42 fields and 6/6 tables**, passed. Degraded scans: **16/21 fields**, reported as limitations, not automatically accepted. Across the corpus there are 58 correct field values, one incorrect value and four missing fields. Exact comparison normalizes Unicode compatibility forms, case and whitespace; it does not erase punctuation or change numbers.

Observed degraded failures:

- English company name: `Blue Harbor Trading L.td.` instead of `Blue Harbor Trading Ltd.`; OCR confidence about 0.887 does not prove correctness.
- Chinese review-date field missing from the parsed result.
- Mixed company name, legal representative and registered-address fields missing from the parsed result.

Every assertion retains raw OCR boxes/native coordinates, page number, method, confidence where available, and source file hash. The simple field parser depends on known English/Chinese labels; OCR and parsing errors both count against the field score. Ownership rows are paired geometrically. This is not yet a general document layout or arbitrary-table extractor. There is no identity verification or document-authenticity assessment.

The first run failed the clean-scan gate: the fixture's CJK font assigned excessive Latin character spacing, and label/value boxes were split. The inputs and results remain under `artifacts/kyc_poc/extraction_attempt_1/`. The generator now uses appropriate Latin/CJK font runs with a clipping assertion; extraction reconstructs lines from geometry. The second run retains the same field/table requirements. Because this is a small development fixture that informed the correction, it is not an independent held-out benchmark. Broader fonts/layouts, traditional Chinese, real document samples and CML execution remain to be evaluated.

## Publication results

The prepared dataset uses actual extracted assertions (including the OCR error), with three synthetic party records, nine document-version records and 59 extracted-field rows. Party test rows deliberately contain Chinese/mixed names, an apostrophe, leading-zero IDs, NULL versus empty string, timestamps and `DECIMAL(20,4)` amounts including a large precise amount. They are serialization probes, not verified customer master data.

| Check | Result |
|---|---|
| CSV explicit-type round-trip | Passed for all three tables |
| Parquet schema/value round-trip | Passed for all three tables |
| Logical key uniqueness and document/fact references | Passed locally |
| Synthetic SQL staging / Iceberg statements generated | Completed; not server-executed |
| Configured Impala DNS/TCP preflight | Blocked, also outside sandbox |
| Remote authentication, CREATE, INSERT, joins and readback | Not reached |
| External Parquet upload to cluster storage | Not tested |
| Interrupted publication recovery / idempotent load / rollback | Not tested |
| Active application release changed | No |

Configured hostname: `qzhong-datahub-gateway.qzhong-a.a465-9q4k.cloudera.site`.
Error: `[Errno 8] nodename nor servname provided, or not known`.
This establishes a name-resolution failure, not a credential or permission failure. The cause (outdated endpoint, private DNS, VPN or other network configuration) is not established.

`kyc_impala_publication_poc.py --execute` uses a unique `aml_kyc_poc_<timestamp>_<suffix>` database, first checks connectivity, then creates SQL-managed Parquet staging tables and Iceberg targets, inserts the synthetic rows, checks exact readback twice and validates joins. It never drops tables or switches the active dataset. This tests the SQL publication path when reachable; it does not substitute for the future external Parquet upload/atomic-release pipeline. Test objects would be retained for inspection if created. The report's database name is a proposed namespace, not evidence that it exists remotely.

The current hostname must be corrected or made resolvable before the remote test can finish. The user was asked asynchronously for the current gateway/HTTP path or required VPN; credentials should remain in the configured environment/local credential file.

## Artifacts and rerun

- [Extraction runner](../02_backend/scripts/kyc_extraction_poc.py)
- [Publication runner](../02_backend/scripts/kyc_impala_publication_poc.py)
- [Optional POC dependencies](../02_backend/scripts/requirements-kyc-poc.txt)
- [Extraction report](../artifacts/kyc_poc/extraction/report.json)
- [Publication report](../artifacts/kyc_poc/publication/report.json)
- [Generated publication SQL](../artifacts/kyc_poc/publication/publication.sql)
- [Environment and model checksums](../artifacts/kyc_poc/environment.json)
- [Mixed clean PDF example](../artifacts/kyc_poc/extraction/mixed_scan.pdf)
- [Focused tests](../02_backend/tests/test_kyc_pocs.py)

```bash
/tmp/aml-kyc-poc-venv/bin/python 02_backend/scripts/kyc_extraction_poc.py
python 02_backend/scripts/kyc_impala_publication_poc.py
python 02_backend/scripts/kyc_impala_publication_poc.py --execute
python -m pytest 02_backend/tests/test_kyc_pocs.py -q
```

The temporary environment uses system site packages and can disappear on reboot; recreate an isolated environment using the pinned POC requirements. The publisher supports `IMPALA_HOST`, `IMPALA_PORT`, `IMPALA_HTTP_PATH`, `IMPALA_USER` and `IMPALA_PASSWORD` overrides, with shipped/local configuration and the existing credential-file fallback. Running the publisher refreshes its local report/SQL; archive those files first if preserving an earlier run.

Four focused tests cover extraction of unseen values, distinct representative/owner roles, absence of invented fields on a blank page, typed serialization and SQL literal handling. All four passed; PyMuPDF emitted deprecation warnings. No app/frontend behavior changed, so an application build was not required for these standalone proofs.

## Updated confidence

Confidence in clean bilingual extraction on these controlled layouts is higher, with measured evidence. Confidence in arbitrary/degraded scans remains medium and requires review/abstention behavior. The portable engine avoids a macOS-only dependency, but this run does not establish Linux/CML compatibility. Local CSV/Parquet serialization is verified. Impala publication confidence remains unverified for this environment until the DNS blocker is resolved and actual writes/readback succeed.
