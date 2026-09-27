# KYC audit concept linkage and release gates

At 2026-09-26, the executable layer is a **synthetic institutional policy demo**.
The separate regulatory source register is a candidate review queue. Its terms
never make a DEMO control legally compliant by implication.

```text
AML customer/account (operational source CSV, optional Impala)
      │ customer_id/account_id and historical alert cutoff
      ▼
KYC source metadata (8 CSV tables, typed local Iceberg publication)
      │ document_id + receipt + page + scoped account
      ▼
Native PDF / image-only PDF ── extraction + OCR boxes/confidence
      │ immutable sha256, version_id, chunk_id
      ▼
LanceDB page evidence ── exact approved_demo mapping ── concept
      │                                            │
      │                               dated DEMO control pack
      │                                            │
      └───────────────────── deterministic assessment / missing evidence
                                                    │
                          retained snapshot + replay + original source links
                                                    │
                         separate analyst review event hash chain

HKMA / MAS official source pointers ── candidate term links ── legal review gate
                                               (not executable today)
```

| Business label / source | Concept in executable demo | Audit meaning and limit |
|---|---|---|
| `受益所有人` in SG registry and `UBO` in declaration | `beneficial_owner` | Both are required in the original SG showcase; disagreement is a conflict. `法定代表人` is explicitly excluded. |
| `significant_controller` in HK registry | `controlling_person` | Separate HK concept; no automatic equivalence to a signatory. |
| `funding_origin` / `Funding origin / 资金来源` | `source_of_funds` | Payment funding evidence; it does not establish accumulated wealth. |
| `Wealth origin / 财富来源` | `source_of_wealth` | Separate accumulated-wealth evidence. |
| `Authorized signatory / 授权签字人` | `account_signing_authority` | Account-specific mandate evidence; no ownership inference. |
| `Review due date / 复核到期日` | `periodic_review_due` | Evidence-presence check; it does not assert review timeliness. |
| Company registry owner label in linked corpus | `registry_owner_record` | Evidence-presence check; it does not identify the legal beneficial owner. |
| Shareholding edges and root IDs | `disclosed_ownership_paths` | Complete declared paths, cycles and percentages; no undisclosed control-through-other-means determination. |
| Account transactions, profile and dated FX | `account_external_outflow_30d` | Synthetic completeness and anomaly check, not a regulatory threshold. |

The current HKMA repository lists AML-2 (25 May 2023) as current and the PDF's
paragraph 4.4.1 discusses identifying and reasonably verifying a beneficial
owner. That is a candidate source link, not an approved control interpretation.
The [MAS Notice 626 publication page](https://www.mas.gov.sg/regulation/notices/notice-626)
identifies the 30 June 2025 revision and its bank scope. The official PDF's
clauses 6.11, 6.13–6.14, 6.19–6.24 and 12.1–12.5 are now located and mapped
as related candidates in the [source register](../semantic/regulatory_source_register.yaml).
The [review packet](kyc_regulatory_review_packet.md) records clause-by-clause
prototype gaps. Institutional review must set applicability, interpretation,
evidence standard and approval before promotion beyond `DEMO`.

The expanded AMP flow now links 12 generated source customers, 30 generated
accounts and 120 PDF versions to assertion, ownership and activity source rows.
The local eight-table package has 32 account profiles, 234 assertions, 54
ownership parties, 94 edges, 32 roots, 32 activity profiles, 34 transactions
and one FX rate (including the original two showcase accounts). Some
account-specific mandate/funding evidence only belongs to a group's first
account; controls on its other accounts therefore report missing evidence.
Local review events keep a self-declared demo ID. The private CML Application
path derives `RW` identity from Workbench authentication; signed loopback
headers prevent substituting a reviewer ID at the backend. Snapshots, events
and the review head can be HMAC-sealed with a separately provisioned key.
Storage-level immutability, retention clocks and legal holds still require
institution-managed storage and policy.
