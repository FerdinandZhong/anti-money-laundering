# Regulatory source review packet — synthetic KYC controls

Checked 2026-09-26 against the issuers' own publication pages. This packet
identifies official text and prototype limits. It is **not** institutional
approval, legal advice or a statement that the demo controls satisfy the cited
obligations. The executable control pack remains `DEMO`; source links are
`SOURCE_REVIEW_ONLY`.

| Source and edition | Clause | Candidate business link | Prototype gap requiring policy review |
|---|---|---|---|
| [MAS Notice 626, revised 30 June 2025](https://www.mas.gov.sg/regulation/notices/notice-626) ([official PDF](https://www.mas.gov.sg/-/media/amld-amendments---30-june-2025/mas-notice-626.pdf)) | 6.11 | Account signing authority | A mandate name does not verify identity, due authority or signature. |
| Same | 6.13–6.14 | Registry owner, beneficial owner, disclosed ownership paths | A registry entry and path graph do not establish every ultimate natural person or effective control. |
| Same | 6.19–6.24 | Review date, activity deviation, source of funds | The synthetic 30-day comparison is not the bank's risk-based monitoring or CDD review process. |
| Same | 12.1–12.5 | Retained assessment and review event | App snapshots are only a subset of required records; retention clock, investigation holds, admissibility and custody require institution policy and infrastructure. |
| [HKMA AML-2, 25 May 2023](https://brdr.hkma.gov.hk/eng/doc-ldg/docId/20230525-4-EN) ([official PDF](https://brdr.hkma.gov.hk/eng/doc-ldg/docId/getPdf/20230525-4-EN/AML-2.pdf)) | 4.4.1 | Beneficial-owner terms, registry owner, controlling person | The demo does not verify identity or determine control through other means. |

The MAS publication page says its 30 June 2025 amendment took effect on
1 July 2025 and applies to banks in Singapore. The HKMA repository identifies
AML-2 as current for authorized institutions. Source metadata is versioned in
[`semantic/regulatory_source_register.yaml`](../semantic/regulatory_source_register.yaml).

Before a legal control is enabled, an institution must record its regulated
entity and products, applicable edition/effective interval, clause and
interpretation, evidence standard, exception handling, accountable approver,
approval date, and retention/legal-hold policy. These decisions cannot be
inferred from a synthetic account, a PDF label, or an analyst review event.
The runtime rejects a control pack unless it is explicitly classified `DEMO`
and every control ID begins `DEMO-`; this source packet cannot activate legal
controls.

| Sign-off field | Current state |
|---|---|
| Institution and regulated legal entity | Not supplied |
| In-scope products and jurisdictions | Synthetic SG/HK examples only |
| Approved edition, clause interpretation and evidence standard | Awaiting institutional legal/compliance review |
| Named approver and approval date | Not supplied |
| Retention start/stop clock and legal-hold procedure | Not supplied |
| Protected seal key and independent backup/WORM location | Demo key in project storage; production location not supplied |

The private Application review write path uses Cloudera's authenticated
`REMOTE-USER` and `REMOTE-USER-PERM` headers. Only `RW` users can submit a
review through the loopback proxy. Assessment and review seals use an
HMAC key. The AMP installer creates a git-ignored demo key in project storage.
For production, `AML_KYC_AUDIT_HMAC_KEY_FILE` must point to a protected secret
mount and the key must be backed up separately from the database. SQLite
project storage is not WORM: object lock, retention schedules and legal
holds require institution-managed infrastructure and policy.
