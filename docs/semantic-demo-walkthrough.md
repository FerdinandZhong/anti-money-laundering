# Semantic context demo (EN / ZH)

## English

Open an alert and select **Semantic context**. This is a read-only explanation of the selected account, not an investigation run.

1. **Account interpretation.** Read the recorded customer profile, expected monthly turnover, 30-day observed outbound activity and review priority. Expected turnover is a declaration; outbound activity is recorded account data. The priority score ranks work and is not a probability of wrongdoing. Keep the account ID and data cutoff in view.
2. **Ossie model and lineage.** Select Customer, Account, Transaction, Alert, Case or Evidence in the graph. The node explains its business meaning, essential attributes, key function, physical source and declared relationships. Solid arrows come from the published Ossie-style model; they show joins, not suspicious transfers between specific accounts. Select **KYC page index** to see the separate PDF/OCR → LanceDB documents/chunks → evidence-retrieval path, shown with a dashed arrow. Full-text indexing is present; vector search requires a configured embedding model. The account-specific value is displayed separately from the model definition.
3. **Original files.** Expand the optional YAML panel to inspect the semantic model, ontology and AML extensions. These are the source contracts for the graph and agents, not official Ossie examples.

The backend semantic query, regulation and control APIs remain available to agents and other clients. They are no longer separate panels in this end-user view.

The prototype uses a lightweight Ossie-style YAML contract and a bounded resolver; it does not run the Apache Ossie execution engine. The source and claim limits still apply to AI findings.

## 中文

打开预警，进入 **Semantic context**。此页只读解释当前账户，不会启动调查。

1. **账户解读。** 查看客户资料中的预期月营业额、账户近 30 天实际转出金额，以及审查优先级。预期营业额是申报值，转出金额来自账户交易记录；优先级分数用于排序，不是违法概率。注意页面上的账户编号和数据截止时间。
2. **Ossie 模型与血缘。** 在图中选择 Customer、Account、Transaction、Alert、Case 或 Evidence。节点展示业务含义、关键字段、主要作用、物理数据源和已声明的关系。实线箭头来自发布的 Ossie 风格模型，表示数据集连接，并非某个账户的可疑转账网络。选择 **KYC page index** 可查看单独的 PDF/OCR → LanceDB 文档与文本片段 → 证据检索路径（虚线箭头）。全文索引可用；向量检索需要配置嵌入模型。当前账户的取值与模型定义分开显示。
3. **原始文件。** 需要详细定义时，再展开 YAML 面板查看语义模型、本体和 AML 扩展。这些是项目的源契约，并非 Ossie 官方示例。

后端语义查询、法规及控制 API 仍供 Agent 和其他客户端使用；它们不再作为终端用户页面中的独立面板。当前原型使用轻量 Ossie 风格 YAML 契约和受限解析器，并未运行 Apache Ossie 执行引擎。
