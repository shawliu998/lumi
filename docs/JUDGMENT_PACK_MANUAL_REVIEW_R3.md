# Lumi 判断推理题包：人工审阅包（第三稿）

> 审阅副本，不是发布批准。本稿绑定 `lumi-conditional-reasoning-v0`
> 的第三稿工件；在两位**不同真人**按本页哈希作出 `approve` 签核前，
> 题包始终是 `draft_unreviewed`，不得注册到产品运行时。本页、AI 预审、
> 测试夹具与模拟数据都不能替代真人签核。

## 本次审阅范围

| 项目 | 值 |
| --- | --- |
| 题包 | `lumi-conditional-reasoning-v0` |
| 版本 / 状态 | `0.1.0-draft` / `draft_unreviewed` |
| 题目数量 | 9 道单选题 + 3 个教学资产 |
| 内容来源 | Lumi 原创声明；不得包含外部真题、截图、答案或题库素材 |
| 许可目标 | CC-BY-4.0；权利审核前不得据此发布 |
| 学习链 | 入口观察 → 最小探查 → 针对性教学 → 无提示独立迁移 → P3D 延迟复测 |

权威源在 [`domains/content/judgment/lumi-conditional-reasoning-v0`](../domains/content/judgment/lumi-conditional-reasoning-v0)。完整题干、选项、答案、形式化、证明和逐选项候选证据映射以同目录的 `records.json` 为准；这些信息**只能给审阅者，不能给学习者端**。

## 当前工件哈希（SHA-256）

| 工件 | 哈希 |
| --- | --- |
| `records.json` | `758182201844ca78c7214e1eb1a383507d92820dabbf1abb8b5f9c391dd01847` |
| `skill-graph.json` | `a5f3454a28d6726580152374018fcd32ea7d591c64d78f63f7e35739c2e6689e` |
| `misconception-taxonomy.json` | `fed38066cc90a031bd9251bb92ed6e5c9bcbdf35af2c3257d8bc08e47db3aba0` |
| `README.md` | `ee64ac33820e5a42e2e3b23645526449ea812bad25b8afe866350d23a1a48e2b` |
| `LICENSE-CONTENT.md` | `7ebd943de88d3d59c81060fbefd0cb7bb579ffb654205d0f353c339de80241c0` |

任一工件或记录变化，即使只改一个字，也必须重新计算哈希并重新审核；不能复用本页签核。

## 本稿修订（响应 AI 预审的 changes requested，不构成真人审核）

| 预审问题 | 第三稿处理 |
| --- | --- |
| P02 选项 A 是非区分性的正例，却被作者映射为 M-ROLE `support` | A 改为明确的“把必要条件当作充分条件”的错误判断；其对 M-ROLE 的 `support` 现在直接来自选项文字，而不是对一个相容正例的猜测。D 仍是唯一兼容反例，正确项仍反驳 M-ROLE/M-READ。 |
| T02 使用“动作发生前必须具备证件”的类比，可能把逻辑必要性误解为时间先后 | 教学文案改为集合/蕴涵关系：领取者都已登记，不代表已登记者都领取；再以“已登记但未领取”的相容情形检验。 |

受影响的记录哈希：P02 为 `67f62efda086beda2f79d4c3a1368aa313ee38c236d622251b759e5ca26494f3`，T02 为 `8f8fa3f593cc4529b1b4e4f570ca0454b00d8f715beae1acaccb0e248bd8c659`。

## 两份独立签核

### A. 逻辑与测量审核（不可与 B 为同一人）

- [ ] 每题恰有一个正确答案，形式化、证明、正确选项一致。
- [ ] P02 的 A 是明确的必要→充分误读，D 是唯一兼容反例；逐选项映射只更新未确认候选。
- [ ] P01/P02/P03 的 `candidate_evidence_map` 与审阅判断一致，且没有一次作答就确认错因。
- [ ] T01/T02/T03 仅在相应 `support` 映射时出现，且教学后作答不算独立证据。
- [ ] V01/V02 是无提示、新情境、不同作答格式的迁移题；R01/R02 不复用原句或正确项位置。
- [ ] 九道单选题正确位置分布为 A=2、B=3、C=2、D=2；延迟复测分别绑定 V01/V02 与 P3D。

```text
review_kind: logic
reviewer_id: ____________________
reviewed_at: ____________________  (UTC RFC3339，例如 2026-07-13T01:05:05Z)
reviewed_artifact_hashes: 与本页五个哈希逐项一致 / 已附新哈希
decision: approve / changes_requested
notes_and_required_changes:

signature: ____________________
```

### B. 编辑与权属审核（不可与 A 为同一人）

- [ ] 已查看作者、提交与素材来源记录，能够支持“原创 Lumi”主张。
- [ ] 未使用外部真题、截图、答案键、题库表达或近似改写。
- [ ] 文案清楚、中性；封闭逻辑限定只用于正式逻辑题设而不误导现实判断。
- [ ] `LICENSE-CONTENT.md`、贡献者授权与 CC-BY-4.0 分发范围已核验。

```text
review_kind: editorial_rights
reviewer_id: ____________________
reviewed_at: ____________________  (UTC RFC3339，例如 2026-07-13T01:05:05Z)
reviewed_artifact_hashes: 与本页五个哈希逐项一致 / 已附新哈希
decision: approve / changes_requested
notes_and_required_changes:

signature: ____________________
```

## 审核后的唯一可执行路径

若有修改意见，先修源题包、重新计算哈希，再请相关审核人复核。只有两位不同真人都对同一版工件哈希签署 `approve`，才可以创建受哈希绑定的 `release_ready` 副本，打包受控桌面资源并开展真人本地浏览器验收。
