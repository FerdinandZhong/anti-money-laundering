# AML Investigation Platform — Demo Storyline (EN)

Scripted presenter narrative for the AML Investigation Platform. Full flow: 8–10 minutes. Accelerated flow: 4–5 minutes (skip the optional agent-detail and ModelOps sections).

**Demo customer:** `Corp_0294 Pte. Ltd.` / `CUST-000294` / account `ACC-0000294`
**Demo alert:** `ALERT-ML-0466899666`
**As validated on 12 September 2026:** 20 alerts are open; this is the top alert, with an account priority score of **94.06%** (shown as **94%**) and a **CRITICAL** band. It was produced by champion model `v20260912_103420` from the monitored three-day batch.

> The exact alert ID, score, timestamps, and transaction values will change after scoring or retraining. Start the demo by selecting the first alert in the risk-ranked queue, then use the on-screen values rather than memorising identifiers.

---

## What this demo takes from OCBC’s published approach (45 sec)

> “This is a Cloudera AML blueprint built on synthetic data; it is not OCBC’s production system and we do not claim OCBC’s results as our own. The design is informed by OCBC’s published end-to-end approach: detect suspicious customer behaviour, attribute it to traceable evidence, narrate the findings within constraints, and keep an analyst accountable for the outcome.”

> “That is why this demo starts with an account-level queue rather than a raw transaction list; keeps score inputs, transaction evidence, KYC context, and network connections together; and separates deterministic scoring from AI-generated investigation summaries.”

> “OCBC’s paper reports its own production outcomes—an 89% analyst-confirmed yield versus 61% for its rule baseline, and higher monthly adverse detection. Those are OCBC’s published results, not benchmarks achieved by this synthetic prototype.”

The reference is OCBC’s 2026 paper, [*Detection, Attribution, Narration*](https://arxiv.org/abs/2607.17586). Use it as design inspiration, not as a claim of deployment equivalence.

---

## Why XGBoost and rules work together here (45 sec)

> “We use XGBoost because the current AML dataset is structured, tabular data: transaction amount, timing, channel, country, KYC tier, account age, expected turnover, recent activity, and network flags. XGBoost is a strong, mature choice for this type of data. It learns non-linear combinations—for example, a near-threshold payment matters more when it is also cross-border and part of a rapid sequence—while training and scoring efficiently in a nightly batch.”

> “The design is deliberately hybrid. XGBoost scores each transaction. The account scorer then combines that ML signal with transparent behavioural rules: the strongest model signal, the persistence of high-scoring activity, 24-hour velocity, fund-flow intensity, shared-device exposure, and cross-border share. This gives the analyst a stable account queue and a reproducible arithmetic trail.”

> “Be precise about the current explanation: HIGH_MODEL_SCORE and SUSTAINED_RISK originate from transaction scores produced by XGBoost. The velocity, fund-flow, shared-device, and cross-border reasons are transparent rule-derived account signals. We do not yet claim that an individual XGBoost feature caused a particular transaction score.”

> “Per-transaction TreeSHAP is the next pilot enhancement. It would show how each input feature moved a specific prediction from its baseline to its final score. We have intentionally not added SHAP filtering or attribution to this limited synthetic feature set; first we need a richer, governed feature catalogue and real evaluation labels.”

---

## Setup (before the audience arrives)

1. Open the CML Application URL and go to **Investigation**.
2. Confirm the backend indicator is green and that the Alert Queue has open alerts. If it is empty, run **Score Transactions** or **Run retraining** in ModelOps and wait for the queue to refresh.
3. Sort the queue by **Risk score** and select its first row: `Corp_0294 Pte. Ltd.`.
4. For a clean full demonstration, do not dispose the alert until the human-decision section. The hosted environment may already contain an investigation; that is safe to show as existing audit history.

---

## 1. Set the scene — the daily queue (45 sec)

Point to the **Alert Queue**.

> “AML teams do not begin with a pile of manually curated cases. Every scoring cycle, the platform evaluates transaction behaviour and creates a fixed, reviewable queue of the highest-risk accounts. The analyst starts with the most urgent work.”

> “This queue is risk-ranked. Our first customer is Corp_0294 Pte. Ltd. Its 94% account risk score puts it in the CRITICAL band. The score prioritises review; it is not a conclusion that the customer has committed a crime.”

Point to the status tabs.

> “Open is today’s work. Proposed is awaiting a SAR/STR filing decision, Pending needs more information, and Archived contains false positives. These outcomes become governed feedback for the next model cycle.”

---

## 2. Open Corp_0294 — explain the evidence (1.5 min)

Click the first alert and point to the customer header, score, triggered-rule chips, and transaction table.

> “The case opens with the customer context and the evidence behind the priority. The customer’s KYC rating is LOW, so this is an important reminder: behaviour can be inconsistent with an otherwise ordinary profile.”

> “The system has triggered HIGH_MODEL_SCORE, SUSTAINED_RISK, HIGH_VELOCITY, LARGE_FUND_FLOW, and CROSS_BORDER_PATTERN. These are evidence-oriented reason codes, not an opaque red light.”

Point to several transaction rows.

> “Here we see repeated outbound FAST transfers, often in the roughly $45,000 to $49,000 range — just below the $50,000 reporting line — with counterparties in Singapore and Malaysia. The table calls out the associated flags: near-threshold payments, cross-border exposure, and, where applicable, off-hours activity.”

> “Individual rows have transaction-model signals around 99%. One payment alone warrants review; the repeated pattern is why the account moves to the top of the queue. Use the selected row’s on-screen amount and score rather than quoting a fixed value after a new scoring run.”

---

## 3. How we get the account score (2 min)

Use this section when the audience asks “where did 94% come from?” It is also the core technical story.

> “There are two levels of scoring. First, the champion XGBoost model scores **each transaction**. It uses behavioural and context features: amount, round-number behaviour, channel, cross-border indicator, customer risk tier, account age, expected turnover, hour and day, 24-hour transaction count and amount, and shared-device exposure.”

> “For Corp_0294, the scoring job rolls transactions in the explicit three-day monitoring window into an **account-level composite** so the analyst can prioritise a customer rather than chase isolated rows. Longer customer history remains visible as context.”

Show or describe the implementation-level formula:

```text
composite = 0.45 × maximum transaction-model score
          + 0.15 × share of transactions above the decision threshold
          + 0.15 × normalised 24-hour transaction velocity
          + 0.10 × normalised 24-hour transaction amount
          + 0.10 × shared-device indicator
          + 0.05 × cross-border transaction share
```

> “The job considers accounts with a genuine transaction-model signal in this three-day batch, removes accounts that already have an open alert, and takes the top 20. It then percentile-ranks that selected batch into a stable presentation range, with a tiny deterministic account-specific adjustment. That produces the 94.06% shown here and maps it to CRITICAL.”

> “So 94% means ‘near the top of this review batch after combining model and behavioural signals’; it does **not** mean a 94% legal probability of money laundering. In a production deployment we would calibrate the probability and document the threshold policy, while preserving this evidence and reason-code trail.”

For this case, tie the formula back to the UI:

| Account evidence | Contribution to the queue decision |
|---|---|
| Repeated transactions with transaction-model signals around 99% | High model score and sustained risk |
| Many payments within 24 hours | High velocity |
| Roughly $45k–$49k transfer pattern | Large fund flow and structuring context |
| Payments to Malaysia | Cross-border pattern |
| Low KYC tier | Input context, not a reason to dismiss the behavioural signal |

---

## 4. Investigate with the agent team (2 min)

Click **Investigate** (or show the stored analysis if the case has already been run).

> “Now the platform separates prioritisation from investigation. Specialist workers gather bounded evidence; they do not get to make the filing decision.”

As the cards complete, narrate:

- **Profile** — “Compares KYC, account age, expected turnover, and alert context.”
- **Pattern** — “Reviews transaction history and model explanation for structuring, rapid movement, unusual channels, frequency, and amounts.”
- **Network** — “Maps fund flows and shared-device links to look for collector, mule, and beneficiary relationships.”
- **Screening** — “Checks profile-level risk and available adverse-screening indicators.”
- **Verification** — “Where configured, validates factual claims against approved external/MCP sources and labels them confirmed, refuted, or unverified.”

> “Each worker saves evidence references. The LLM writes concise findings, but it does not create the risk score, alter the data, or decide whether to file. If the LLM or a verification source is unavailable, the platform fails soft: deterministic data and the analyst workflow remain available.”

> “This is the current demo boundary: KYC documents are local, synthetic source-of-wealth records, and any external verification is optional and explicitly labelled. A pilot phase would add governed document retrieval, source citations, counterparty resolution, and a stateful collect–critique–verify loop.”

---

## 5. Analyst decision and learning loop (1 min)

Point to the disposition control.

> “The analyst remains accountable. After reviewing the evidence, they can mark this as Suspicious, Needs more info, or False positive, with a rationale and their name. The action is persisted as an audit record and the alert leaves the Open queue.”

> “The analyst can also label individual transactions as suspicious or clean. Those transaction-level labels override synthetic labels during future training. This keeps the feedback signal precise: an account disposition manages workflow; transaction labels improve the model.”

Use a non-final phrasing for the live case:

> “For this demonstration, the pattern supports escalation for review. The final SAR/STR decision remains with the authorised investigator under the institution’s policy.”

---

## 6. ModelOps — governed change, not black-box retraining (1 min, optional)

Open **ModelOps**.

> “ModelOps makes the learning loop governable. We can see the champion, historical training metrics, score distribution, alert bands, and feature drift.”

> “When retraining runs, the workflow streams PREPARE, TRAIN, CANARY, PROMOTE, SCORE, and NARRATE. A candidate is tested before promotion; the promoted champion re-scores the queue. If it fails policy or operational checks, it can be rolled back.”

> “The current champion shown for this regenerated scenario is `v20260912_103420`. Treat the displayed PR-AUC and recall as monitoring metrics on a synthetic dataset, not proof of case guilt or a production benchmark.”

---

## 7. Close (30 sec)

> “The platform turns transaction data into a focused daily queue, explains why an account was prioritised, equips an analyst with transaction and network evidence, and closes the loop with governed human feedback and model operations. AI accelerates the investigation; accountable people make the compliance decision.”

> “The next pilot step is not simply ‘more AI’: it is calibrated customer-level risk, case-specific attribution, governed KYC and external-source evidence, and measurement of analyst yield and capacity—the operating disciplines reflected in the OCBC-inspired design.”

---

## Likely questions

**Is the 94% a probability of money laundering?**
No. It is a batch-relative account-prioritisation score built from transaction-model and behavioural signals. It should not be presented as a calibrated legal or regulatory probability.

**Why is a LOW-KYC customer CRITICAL?**
KYC tier is one input. The alert is led by observed behaviour: high transaction-model scores, repetition, velocity, fund flow, and cross-border activity.

**Why keep a top-20 queue instead of a fixed cutoff?**
The daily review capacity is stable even if a newly trained model’s raw probability distribution changes. A production programme should separately govern capacity, calibration, and risk appetite.

**What happens if the LLM is unavailable?**
The score, queue, data views, and deterministic workflow still operate. The agent narrative uses a fail-soft fallback; it does not determine the risk score or disposition.

**Is this production customer data?**
No. This blueprint runs on synthetic data locally and can use governed Impala/Iceberg data in production without changing the application code.

**Did this prototype achieve the OCBC results quoted in the presentation?**
No. Those figures belong to OCBC’s published production study. This demo adopts relevant architectural principles and must be evaluated separately on a governed institution dataset.
