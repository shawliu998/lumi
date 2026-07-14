# Lumi P2 数据、评估与 Terra 审计

状态：规划与验收契约；不授权 P2 生产实现。P0/P1 未通过前，本文件只定义后续数据契约、非生产评估脚手架和验收条件。

## 审计结论与边界

已审阅根 `AGENTS.md`、`docs/P0_P1_P2_EXECUTION.md`、`docs/EVALUATION.md`、`evals/` 合约与 harness、现有 `EventStore`，以及 `engine/hermes_kt/cohort.py`/`guardrails.py`。当前 trace 是本地、追加式、哈希链保护的运行轨迹；它不是已获同意的研究数据集。现有 cohort 代码已将未隐私审查或低于最小样本的 aggregate 回退为 `engineering_prior`，并使 `sample_size=0`。该行为是 P2 的起点，不构成真实 cohort、校准或有效性证据。

P2 对真实学习者数据只能使用显式同意、可撤回、用途受限的数据。夹具、合成内容、专家先验和本地单用户工程轨迹只能验证软件机制，必须标记为 `engineering` 或 `synthetic`，不能混入任何人口指标分母。经本次决定，P2 允许在严格隔离的 namespace/store 中生成可复现的合成学习者仿真数据；它同样不是 cohort、校准、因果或学习效果证据。

## 1. 可复现 synthetic learner simulation 层（提案契约）

P2 可以生成合成学习者数据，但它是**隔离的工程仿真层**，用于验证契约和算法机制，不是 consented learner event 的替代品。每个合成对象必须从生成到报告都携带 `synthetic: true`，并只写入独立的 `synthetic/` namespace 与 store；真实 learner store、导出管道、cohort 聚合输入和产品投影必须在路径、数据库/表、访问凭据和运行 ID 上隔离。跨 namespace 读写、联结或复制为 fail closed。

### 1.1 用途与硬边界

允许的用途：

- schema、hash-chain、lineage、export/delete/tombstone 和 redaction 的确定性测试；
- KT、scheduler、policy 的 dry-run replay 与状态不变量测试；
- delayed-retention harness、帮助层级、dropout、缺失、drift、冲突证据和 adversarial 输入的故障测试；
- 在**虚构机制**下验证 fairness guardrail 的字段隔离、切片抑制、禁止属性流入决策与报告标签，而非验证现实公平性。

禁止用途：

- 进入真实 cohort prior、产品 peer/“常见错因”文案、真实数据导出或真实 learner state；
- 作为校准、人群准确率、因果效应、学习效果或公平性表现的分母/证据；
- 以模拟的人口属性或 archetype 冒充真实人群、受保护群体或公平性证据；
- 覆盖真实同意规则：真实 consented `sample_size=0` 时，cohort、校准和因果输出仍必须是 `availability: "unavailable"`，原因保持 `no_consented_population_data`。

所有 simulation 报告标题必须以 **“Synthetic Simulation — 非人群证据”** 开头；每个表、图和 API payload 必须包含 `data_origin: "synthetic_simulation"`、`synthetic: true`、`simulation_run_id`、`generator_version`、`seed` 和 `synthetic_denominator`。禁止仅标注“样本量 N”而省略 synthetic 来源；不得把 synthetic 分母与 consented 分母相加。

### 1.2 最小 simulation schema

以下为非生产、版本化的最小 contract；字段可扩展但未知字段必须被记录为 schema rejection，不能悄然进入 replay 或指标。

| 对象 | 最小字段 | 约束 |
| --- | --- | --- |
| `simulation_run` | `simulation_run_id`、`schema_version`、`synthetic:true`、`namespace`、`generator_version`、`seed`、`scenario_id`、`archetype_id`、`created_at`、`config_hash` | `namespace="synthetic"`；同一 generator/config/seed 必须产生相同 canonical event stream/hash；`scenario_id` 与 `archetype_id` 是机制标签，不是人口属性。 |
| `latent_learner_state` | `synthetic_learner_id`、`lineage_root_id`、`skill_state`、`cause_state`、`engagement_state`、`latent_state_version` | 仅作为 oracle/测试标签，绝不暴露给产品、cohort、模型特征或教练视图；每个可见事件只引用可观测投影。 |
| `simulation_event` | `event_id`、`simulation_run_id`、`synthetic:true`、`synthetic_learner_id`、`seq`、`occurred_at`、`event_type`、`payload`、`previous_event_hash`、`event_hash`、`lineage_root_id` | 沿用 append-only 哈希链与幂等语义；payload 必须明确 `observed` 与 `oracle_only` 字段边界。 |
| `simulation_manifest` | `scenario_catalog_version`、`model_versions`、`item/rubric versions`、`seed`、`event_count`、`learner_count`、`synthetic_denominator`、`output_hash`、`retention_policy` | 记录可重现所需版本和参数；不能含真实 consent receipt、真实 learner ID 或真实 aggregate。 |
| `simulation_metric_report` | `title`、`data_origin`、`synthetic`、`simulation_run_id`、`metric_version`、`synthetic_denominator`、`availability`、`limitations` | 标题与限制必须说明模拟机制；禁止 `cohort_prior`、population calibration、causal uplift 或 real-world effectiveness 字段。 |

生成器配置至少包含下列显式模型及其版本/参数 hash：

- **response model**：由 latent skill/cause、item difficulty、独立性和政策动作产生 correct/incorrect、置信度与用时；不能把未来结果写入决策时特征。
- **hint model**：由可观测困难、策略提供与 synthetic learner 行为决定 request/show/open；输出帮助层级、时点和是否使本次尝试不独立。
- **dropout model**：产生 session/后测缺失、恢复或永久退出，区分模型生成的 missingness type，不把失访自动标记为失败。
- **retention model**：从 index event 和潜在状态产生满足预注册间隔的后测结果；同会话重试不能伪装为 retention。
- **missingness/drift/adversarial models**：覆盖 MCAR/MAR/MNAR-like 缺失假设、题目/政策/行为分布漂移、乱序/重复/篡改 hash、提示泄漏、矛盾证据、极端时延和恶意字段；它们是压力模型，不是现实发生率估计。

### 1.3 Scenario 与 archetype 规则

`scenario_id` 描述测试机制（例如 cold start、high-hint pathway、delayed-retention loss、policy drift、trace tamper）；`archetype_id` 只描述学习过程参数组合（如 mastery/cause/engagement trajectory），不得使用、代理或映射真实人口、地区、年龄、性别、残障、族群、社会经济状况或考试身份。

每个 scenario/archetype 要有书面假设、参数范围、预期不变量和故障目的。可以测试“若一个虚构机制对两个参数组给出相同可观测证据，策略是否保持相同处理”；不能表述为“系统对真实群体公平”。当需要模拟敏感属性字段来验证拒绝/删除逻辑时，该字段须标为 `synthetic_sensitive_test_only`，不得进入 policy/KT 特征、分组性能报告、产品文案或 cohort 输入；测试只断言字段被拒绝、隔离或不影响输出。

### 1.4 Synthetic export/delete 与 oracle 隔离

Synthetic export 可以验证 manifest、field allowlist 和删除传播，但其 `export_id`、lineage root、tombstone 和归档路径必须属于 `synthetic` namespace，且 manifest 声明 `not_a_user_data_export: true`。Synthetic deletion 验证“删除 simulation run/learner 后派生 replay、报告和 snapshot 失效重建”；它不能被描述为完成真实 data-subject deletion。

Oracle latent state 只能用于测试断言（例如 KT 误差、scheduler 对已知到期事件的处理、回放是否泄漏未来 oracle）；不得作为运行时输入、模型训练标签、教练证据、用户可见诊断或真实效果估计。基于 oracle 的评分也只能称为“相对于已声明 simulation mechanism 的机制一致性”，不能称校准、准确率或学习效果。


## 2. Consented learner event（提案契约）

一个可进入 P2 受控数据集的事件必须同时满足下列条件；任何一项缺失即为 `ineligible`，保留在本地产品记录（如适用）但不得导出、汇总或用于模型/策略评估。

| 字段组 | 最小字段 | 语义与约束 |
| --- | --- | --- |
| 事件身份 | `event_id`、`event_type`、`occurred_at`、`schema_version`、`event_hash`、`previous_event_hash` | 不可变 ID；UTC 时间；版本化；同一 learner stream 的哈希链可验证。重试以稳定 `idempotency_key` 去重。 |
| 伪名主体 | `learner_pseudonym`、`device_or_installation_pseudonym` | 不导出直接身份标识符。映射仅留在本机、独立加密存放，不能随 research export 导出。 |
| 同意快照 | `consent_receipt_id`、`consent_version`、`purpose`、`granted_at`、`withdrawn_at`（可空） | 事件发生时的同意版本与用途必须可验证。用途至少区分产品改进、聚合 cohort、研究/评估；未勾选即不处理。撤回后不得再进入新导出。 |
| 学习观察 | `attempt_id`、`item_id_pseudonym`、`item_version`、`skill_ids`、`domain`、`response_outcome`、`independence_status`、`assistance_exposure` | 最小必要观察。独立性不能由模型推断；帮助暴露记录显示/展开层级、时间与版本。原始自由文本、音频、题面和 PII 默认不出域。 |
| 决策可审计性 | `policy_version`、`model_or_tool_versions`、`decision_id`、`decision_reason_evidence_ids`、`state_delta_ref` | 可关联既有 trace/状态变更，但导出只含必要、脱敏投影及版本摘要。 |
| 数据治理 | `retention_class`、`redaction_version`、`lineage_root_id`、`processing_status` | 明确保存期限、脱敏规则、源 lineage 与指定用途的处理资格。 |

允许的 `event_type` 应来自版本化枚举：attempt submitted/scored、hint shown/opened、probe answered、independent verification、review due/completed、consent granted/withdrawn、export requested/completed、deletion requested/completed。未知字段/类型、未来时间、失配用途、无效 hash、重复 `event_id` 或撤回后处理均须 fail closed，且不能创建部分 cohort 输入。

`independence_status` 至少为 `independent`、`assisted`、`not_assessable`；只有明确无帮助的独立尝试可进入 independent accuracy、错因解决和延迟保持的分子。帮助出现后不能通过“答对”追溯改写为独立。现有 `hints_used` 与 `independently_answered` 是有用前身，但 P2 需要可版本化的帮助暴露语义，而不只是一个计数。

## 3. 导出、删除与 lineage

所有对象使用不可猜测 ID，且 `lineage_root_id` 从原始本地事件延续至派生行、聚合、评估运行和报告。每个转换记录：`input_lineage_ids`、转换/代码版本、参数 hash、操作者/自动任务身份、开始/结束时间、输出 hash、用途、同意快照和保留到期时间。导出和删除本身也写入审计事件，但不含可恢复的原文或直接 PII。

导出流程：

1. 验证请求主体、范围、目的、同意仍有效、未超过保留期，以及所有输入事件的处理资格；按最小化字段投影并运行版本化脱敏。
2. 生成 manifest（schema、过滤条件、row count、lineage roots、代码/指标版本、hash、生成时间、接收方/用途、到期时间）；导出物加密并记录 `export_id`。
3. 不可资格行必须计入排除原因而非静默补齐；`sample_size` 只计入合格且去重后的分母。导出不能包含原始 trace payload、自由文本、音频或本地身份映射。

删除/撤回流程：

1. 写 `deletion_requested`，冻结该主体的未来导出、训练、cohort 刷新和评估；后续事件的 consent snapshot 视为无效。
2. 由 `lineage_root_id` 找到本地原件、可再生派生表、活跃 cohort snapshot、评估切分与未发布导出；删除或加密擦除可识别原件，失效/重建受影响派生物，并写 `deletion_completed`（对象类别、数量、版本、不可逆确认）。
3. 已发给批准外部接收方的不可回收副本必须在同意文本和 manifest 中预先披露；记录通知与处置。已发布 aggregate 仅在达到隐私门且不可回溯个人时可保留，否则失效重算。

删除不会改写 append-only 原事件或哈希链：保留最小 tombstone（不可逆 subject commitment、请求/完成时间、处理版本），删除可读 payload 与本地映射。审计记录须证明“已处理”，不能重新识别学习者。

## 4. 指标词典

所有结果都应带分母、时间窗、版本与 `availability`（`available`、`unavailable` 或 `not_applicable`）。分母为零、字段缺失、未满足同意/隐私门、独立性或切分规则不满足时必须为 `unavailable`，附 machine-readable reason；不得显示 `0%`、估计值、模拟值或空置信区间来冒充结果。

| 指标 | 合格分母与分子 | 不计入/解释 |
| --- | --- | --- |
| 独立正确率 | 固定评估窗内，`independence_status=independent`、评分可判定、题目/评分器版本明确的去重尝试；分子为正确。报告 micro 和按 learner macro（如可用）。 | assisted 答对、未评分、重复、答案泄漏或材料已训练/已见均排除；它是描述性表现，不等于学习增益。 |
| 提示依赖 | 有资格学习机会中，至少一次实际打开/显示会改变解题信息的帮助的尝试数 ÷ 全部有资格尝试数；同时报告帮助层级、每尝试帮助次数和帮助后正确率。 | 仅帮助按钮可见不算暴露；未知帮助日志为 `unavailable`，不能当 0；不表示“帮助导致依赖”。 |
| 错因解决 | 对先前 `unconfirmed_hypothesis` 的 cause，在目标 probe/教学后，未来独立、等值或迁移题满足预注册反证规则；分子为达规则且无反向证据的 cause episodes。分母须有可判定基线、目标干预、合格后测和观察窗。 | 正确初始题不产生 cause；模型重排序、单次 assisted 正确、主观感受、未完成 probe 都不算解决。报告 `resolved/not_resolved/inconclusive`。 |
| 延迟保持 | 合格基线/教学后，在预注册最短间隔（默认至少 7 天，具体协议固定）的首次独立、未泄漏等值/迁移复习；分子为正确且符合评分。分母为已到窗口、有可用后测或明确失访状态的 episodes。 | 同会话再做、有提示、复用答案、间隔不足或题目泄漏均不计；失访单列，不能当失败或成功。 |
| 弃答/拒答 | 对需诊断、推荐或评分但证据不足/冲突/超出能力的合格决策机会，分子为结构化 `abstain/defer` 且无伪造结论；分母为全部此类机会。专家/后验标签存在时另算弃答恰当性。 | 用户跳题不是系统 abstention。无专家标签只能报频率与理由，不能声称 abstention quality。 |

每个指标行还需记录 `metric_version`、cohort/切分定义、计数单位（attempt、episode、learner）、重复规则、评分器/题目版本、置信区间方法和可用性原因。小样本只可呈现隐私允许的描述性计数/区间，不能推出群体规律。

## 5. 时间切分与泄漏防护

模型选择、阈值设定和报告按 learner 的事件时间切分，不得随机打散 attempt。对同一 learner，训练窗口早于验证窗口，验证早于冻结测试窗口；同一 attempt、session、其派生诊断/状态 delta 与延迟后测只能属于一个评估角色。cutoff 后出现的标签不能回写为 cutoff 前特征。

至少执行以下检查：

- learner、attempt、session、lineage root 和 trace hash 在 train/validation/test 间无交叠；同一原题和近重复/同模板族按题目族隔离。
- 特征只读取决策时已存在且同意有效的事件；禁止最终 mastery、未来正确率、后续 probe/教师标签、人工复盘或已删除数据。
- intervention、提示内容、题库、rubric、policy/model 版本按时间冻结；测试期变更按版本分层，无法分层则 `unavailable`。
- 延迟保持的 index date、最短/最长窗、首个合格后测和失访规则在看数据前固定，不能挑选容易题或仅有结果的 learner。
- 多次记录相关时，使用 learner/episode 聚类区间或明确仅为描述性计数；样本不足切片不发布。

P2 前的合成 fixture 仅可断言屏障会拦住泄漏；不能拟合阈值、估计校准或报告留出集效果。

## 6. 策略反事实回放：允许与禁止

反事实回放仅是离线、观察性、dry-run 工具。输入为可验证的历史决策日志；输出是“在记录状态和已观察到的 action/outcome 上，候选策略会选择何 action”的覆盖率、分歧率、成本/帮助暴露的预测性描述，以及 unsupported action 比例。回放不得写 learner state、不得触发工具/模型、不得把候选 action 的未观察结果补成成功或失败。

只有在记录了行为策略/版本、action propensity 或确定性选择规则、决策时状态、支持重叠检查、预注册估计量、权重截断和敏感性分析，且全部行有相应处理同意时，才可报告带 propensity/权重的探索性 off-policy estimate。即便如此，必须标注 `observational`，给出未覆盖行动比例和未测混杂风险。

回放不能证明候选策略提高学习、减少提示依赖、解决错因、改善公平性或优于历史策略；不能为历史未选择的干预捏造 outcome；不能以 synthetic fixture 或 `sample_size=0` 生成效应估计。因果/有效性结论需要另行预注册的随机或准实验设计及延迟保持终点。

## 7. 教练视图：最小数据投影

教练视图服务当前学习者的证据复核和复习队列，不是 cohort dashboard，也不展示他人数据。每个投影带 `projection_version`、生成时间、来源 `event_id`/trace hash、版本和 stale 标志，只显示完成任务所需字段。

| 视图 | 可显示投影 | 不显示 |
| --- | --- | --- |
| 证据 dossier | learner 本地别名、技能/题目版本、独立性/帮助暴露、评分与 rubric evidence、候选错因及 `unconfirmed` 状态、支持/反驳 evidence IDs、probe/验证结果、模型/策略版本、状态前后差异 | 原始 PII、他人记录、将候选原因写成事实、未同意研究属性、隐藏 chain-of-thought。 |
| 复习队列 | task/review ID、到期、技能、安排理由/evidence IDs、预期时长、成功准则、skip/postpone 后果、完成/取消状态 | 同龄人百分位、群体常见错因、未验证掌握结论、依据 cohort 的精确承诺。 |
| 数据权利/状态 | consent purpose/版本、导出/删除状态、可导出类别、保留期限、云边界/脱敏版本 | 可恢复身份映射、已删除 payload、无权限接收方的原始数据。 |

未来合格的 cohort prior 也只能作为有 source version、审查状态、最小样本门和不确定性说明的诊断输入；不得变成“你和某群体一样”的比较或身份属性推断。

## 8. Cohort prior 隐私与最小样本门

现行 engine 默认 `min_attempts=50`、需要 `privacy_reviewed=True`，并对合格 aggregate 做 shrinkage。这是工程默认值，不是正式隐私证明。P2 上线前，隐私审查记录必须固定 cohort 定义、敏感属性禁用清单、最小总样本/单元格阈值、抑制规则、可发布维度、保留期和复审人；只有 aggregate counts 能到 prior builder，绝不输入 learner-level rows。

通过门的条件：

- 输入事件均已同意该用途且未撤回，taxonomy/version 一致；
- aggregate 完成隐私审查，且总数和所有发布/使用细胞达到批准阈值；
- 无小组差分、稀有组合或时间窗的可重识别风险；
- 每个 prior 带 cohort definition、`sample_size`、source/aggregation version、审查记录和 fallback level。

任一条件失败，count 不得影响诊断、不得暴露小 cell，且必须退回版本化 `engineering_prior`。

特别门禁：cohort/校准/因果输出的有效样本为 `sample_size=0` 时，响应必须为 `availability: "unavailable"`，并给稳定 reason（如 `no_consented_population_data`）和非群体替代（个人证据或 `engineering_prior`）。不得输出 cohort prior 数值、校准曲线、置信区间、排名、“常见错因”、人群基线或因果效应，也不得以 synthetic/fixture 替代。工程诊断若使用 `engineering_prior`，每个 hypothesis 必须显式标示该来源，且不得出现 `cohort_prior`；这与现有 cohort guardrail 的 fail-closed 语义一致。

## 9. P2 分步测试矩阵

| 阶段 | 确定性测试 | 必须失败关闭 | 通过证据 |
| --- | --- | --- | --- |
| A. 事件资格 | 同意版本/用途、撤回时间、hash 链、幂等去重、字段白名单、独立性/帮助 schema | 无同意、用途失配、撤回后处理、未知字段、重复/断链、未知独立性进入指标 | 输入 fixture、拒绝原因和不可变审计事件。 |
| B. 导出 lineage | 最小投影、PII/redaction 扫描、manifest hash、row count、lineage 完整性、过期过滤 | 原始 payload/身份映射出域、无 consent receipt、导出后不可追溯、分母静默变化 | 可复算 manifest、脱敏样本、hash 验证。 |
| C. 删除 | root→派生→aggregate→eval 影响图、冻结、擦除/重建、tombstone、幂等重试 | 删除后仍可导出/训练、派生物未失效、删除破坏历史 hash、tombstone 可识别 | 请求到完成 audit trail 与重建清单。 |
| D. 指标 | 分子/分母、去重、help/独立、缺失、失访、版本冻结 | assisted 计入 independent、正确题生成 cause、短间隔算 retention、零分母显示 0% | 边界 fixture 精确计数与 availability 断言。 |
| E. 时间/泄漏 | learner/session/attempt/item-family/lineage 交集、cutoff 特征、延迟窗、版本隔离 | 未来标签、同题族跨 split、同 episode 多角色、挑选后测 | split manifest、零泄漏报告、故意泄漏 fixture 被拒。 |
| F. 回放 | replay hash、只读性、行为策略版本、support/positivity、propensity 账本、分歧统计 | 触发工具、写状态、未观察 action 生成 outcome、无 propensity 报效应 | dry-run trace、写入计数为零、coverage 报告。 |
| G. Coach projection | allowlist、来源链接、候选状态、权限/单人隔离、stale | PII、跨 learner、隐藏推理、将 hypothesis 显示为事实、展示 cohort 比较 | 投影快照与负向字段扫描。 |
| H. Cohort 门 | consent、撤回、privacy review、总样本/细胞门、taxonomy、sample 0 fallback | 小/未审 aggregate 影响概率/泄露 count；sample 0 仍给 cohort/calibration/causal 输出 | engineering prior 标签、unavailable 响应、扩展现有 cohort 测试。 |
| S. Synthetic simulation | 固定 seed 的字节/哈希复现、namespace/store 隔离、oracle 不可见、response/hint/dropout/retention/missingness/drift/adversarial scenarios、synthetic export/delete | `synthetic:false`、跨 store 联结、oracle 进入特征/视图、标题/分母缺 synthetic、模拟属性进入 policy 或公平性报告 | run manifest、canonical stream hash、负向隔离扫描、带 Synthetic Simulation 标题的报告。 |
| I. 端到端 | 资格→导出→撤回/删除→重建→指标→回放→视图 | 任一 lineage 缺失、无效输出被缓存/展示 | 可复放审计包与版本清单。 |

P2 engineering readiness 只能在 A–I 与 S 的确定性测试通过后声明；仍不等于 population efficacy 已证明。真实数据接入、隐私审查、阈值选择或研究设计变更均需新的 owner 授权与 P0/P1 放行。

## 10. P2 实施顺序（放行后）

1. **先写 non-production contract 与隔离门。** 固定 simulation schema、namespace/store ACL、manifest、报告标签与 synthetic=true 拒绝规则；先用负向测试证明 synthetic 不能写入真实表、cohort prior、产品投影或真实导出。
2. **实现可复现生成与 lineage。** 固定 generator/scenario catalog 版本、seed、config hash、canonical ordering、事件 hash 链和 synthetic export/delete/tombstone。先验证同配置重复运行完全一致、变更 seed/version 必然可见。
3. **实现机制模型和 oracle 隔离。** 依次加入 response、hint、dropout、retention、missingness、drift、adversarial model；每项先有可测的参数合同与未来-oracle 泄漏拒绝测试，再接入 KT/scheduler/policy dry-run。
4. **接入非生产 harness。** 将 synthetic runs 只接入 schema/lineage/delete-export、KT/scheduler/policy replay、delayed-retention、fairness-guardrail 和故障测试；所有输出以 synthetic simulation 指标单列。
5. **运行扩展矩阵并审计文案。** A–I 与 S 全部通过，且每份报告/API/视图负向扫描均拒绝混源、peer/cohort 文案和人群/因果字段后，才可声明 P2 synthetic engineering readiness。
6. **真实数据是独立后续工作。** 仅在 P0/P1 放行、真实 consent、隐私审查和研究设计另行批准后，才评估真实事件管道；不可用 synthetic 结果缩短该门或替代真实样本。

## 11. 不允许的群体与因果主张

在没有满足上述 consent、隐私、样本、时间切分和研究设计条件的证据前，产品、报告、API 和演示不得声称：

- Lumi 提升学习成绩、独立迁移、延迟保持或长期考试结果；
- 某提示、诊断、教学策略或模型导致更好/更差结果，或优于另一策略；
- 某错因“在用户群中常见”、某 learner 属于某群体、某群体更弱/更依赖帮助，或任何人口属性比较；
- 诊断/KT 已校准、具有人群准确率、适用于新 cohort，或存在可靠 percentile/benchmark；
- `sample_size=0`、synthetic、fixture、专家先验或单用户轨迹代表真实用户、cohort 或外部世界；
- 以 synthetic scenario/archetype 或模拟人口属性证明、暗示或比较真实受保护群体的公平性；
- 观察性回放的关联是因果效应，或未完成/失访者的结果与完成者相同。

允许的表述限于可验证工程事实，例如“该次本地独立验证的评分为正确”、“当前证据支持/未确认该错因假设”，或“当前没有获同意的人群数据，因此群体输出不可用”。Synthetic run 只可声明为“在已声明的 synthetic mechanism/seed 下，某个 schema、lineage、隔离门或状态不变量通过/失败”；不得省略 synthetic 标识。更强的学习效果、校准、公平性或因果主张须经预注册、隐私审查的真实数据研究设计，并以独立与延迟保持终点报告。
