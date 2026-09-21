# Semantic context demo (EN / ZH)

## English: a three-minute demonstration

Open an alert, then select **Semantic context**. This tab calls the existing semantic APIs. It does not run an investigation, change labels, or create alerts.

1. **Compare KYC with activity.** Click the first preset. “Expected turnover” resolves to `kyc_declaration`; “observed outflow” resolves to `observed_outbound_flow_30d`. Show the definition, value and source for each. One is an onboarding declaration; the other is observed outbound activity. Retain the displayed account scope and 30-day cutoff. A mismatch is a lead, not proof of crime. Do not assume turnover and outbound flow are interchangeable accounting measures.
2. **Explain the priority score.** Click the second preset. “Risk score” resolves to `account_priority_score`. Show the priority definition, model/rule signal details, recorded pattern dates, and claim limitations. This is a prioritisation score, not a crime probability. These explanations are not SHAP attributions.
3. **Test the intent boundary.** Click the third preset. The same risk-score term is now unavailable because the request is scoped to `kyc_review`. Expected turnover is still returned. This demonstrates actual backend fact-selection rules, not a warning appended to a generated answer. It is not a user-authorisation boundary: a caller can select another declared intent.
4. **Show the model and handoff.** The Customer → owns → Account → sends → Transaction path comes from the ontology. It describes business relationships, not a detected suspicious network. Expand Coverage and agent handoff to inspect the returned JSON and unavailable fact providers. Profile and screening workers use KYC context; pattern and network workers use their own intent bundles alongside other tools. MCP clients use the same resolver.

**Closing line:** “The semantic layer gives our agents shared business meaning, a bounded retrieval scope, and explicit interpretation limits. It does not replace the model, the evidence, or the analyst.”

### Honest boundaries

- Results are fresh previews, not the exact inputs of a previous worker run.
- Definitions and claim guidance are passed to agents; generated-answer compliance is not mechanically guaranteed.
- Flow is aggregated across the listed customer accounts. The priority score belongs to the selected alert account.
- Current retrieval is capped at 5,000 transactions per account. Do not claim complete aggregation on larger datasets.
- Evidence-reference count is not a count of independent corroborations.
- Some declared concepts have no fact provider in this bundle. Separate worker tools supply additional data; ontology declaration alone does not make a query executable.
- Source of wealth is not an alias for expected turnover. Review supporting documents under KYC Documents instead.
- The app demonstrates a lightweight YAML contract and bounded resolver, not deployment of the Apache Ossie execution engine.

## 中文：三分钟演示

打开一个预警，进入 **Semantic context**。此页调用现有语义 API，只读查询，不启动调查、不修改标签，也不生成新预警。

1. **比较 KYC 与实际行为。** 点击第一个示例。“Expected turnover” 被映射为 `kyc_declaration`，“observed outflow” 被映射为 `observed_outbound_flow_30d`。展示各自的定义、数值和来源：前者是开户申报，后者是实际转出记录。必须保留账户范围、30 天窗口及截止时间。差异是调查线索，不是犯罪证据；营业额与转出金额也不一定是相同的会计口径。
2. **解释优先级评分。** 点击第二个示例。“Risk score” 被映射为 `account_priority_score`。展示评分定义、模型与规则信号、行为模式时间和结论限制。此分数用于安排调查优先级，不代表犯罪概率，也不是 SHAP 特征归因。
3. **验证查询范围限制。** 点击第三个示例。同样的 risk score，在 `kyc_review` 目的下不予返回，但 expected turnover 仍可返回。这是后端真正执行的事实筛选，不只是生成答案后的提示。它不是用户权限控制，因为调用者可以选择另一种已声明的调查目的。
4. **说明本体与 Agent 的连接。** Customer → owns → Account → sends → Transaction 来自本体声明，表达业务关系，不代表已发现可疑资金网络。展开 Coverage and agent handoff，展示返回 JSON 和未提供事实的概念。客户画像与筛查 Worker 使用 KYC 上下文，交易模式和网络 Worker 使用各自的目的上下文，并结合其他工具获取证据。MCP 调用同一个解析器。

**收尾：**“语义层为 Agent 提供统一的业务含义、限定的查询范围和明确的解释边界，但不会替代模型、证据或分析师。”

### 演示边界

- 此页是当前查询预览，不是过去某次 Worker 输入的精确回放。
- 结论限制会传给 Agent，但系统尚未保证每次生成的答案都严格遵守。
- 转出金额汇总列出的客户账户，优先级评分对应当前预警账户。
- 每个账户最多读取 5,000 笔交易，大规模数据下不能宣称已完整汇总。
- 证据记录数量不等于独立交叉验证的数量。
- 本体中声明的部分概念尚未在本查询中提供事实；其他 Worker 工具可补充信息。
- 财富来源不等于预期营业额，应在 KYC Documents 查看支持材料。
- 当前实现是轻量 YAML 契约及受限解析器，不代表已部署 Apache Ossie 执行引擎。
