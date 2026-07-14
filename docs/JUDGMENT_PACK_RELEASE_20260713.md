# Lumi 条件逻辑题包：受控本地发布记录

## 状态

`lumi-conditional-reasoning-v0-0.1.0-reviewed-local-20260713` 是一个可由
本地 Lumi sidecar 加载的 `release_ready` 副本。其作者草稿仍保留在
`domains/content/judgment/lumi-conditional-reasoning-v0`，并继续保持
`draft_unreviewed`；发布副本不会回写或篡改该草稿。

本次发布由仓库所有者直接授权，范围为 `local_controlled_release`。它不
证明人群效果、校准、因果、公平性、外部考试题库权利或公开生产分发。

## 审核转录与精度

第三稿人工审核工作簿中的两位不同真人审核人使用匿名稳定标识 `1` 与
`2`，分别完成逻辑与编辑/权属审核。原表只记录日期 `7.12` 与 `7.13`，
未记录时分秒；因此发布记录保留为 `2026-07-12` 与 `2026-07-13` 的
`day` 精度，绝不虚构审核时刻。

审核工件本身不提交到 Git。发布副本中的 `review-evidence.json` 保存其
文件名与 SHA-256、作者草稿的 manifest/工件/记录哈希、审核转录以及本
次所有者授权的 UTC 记录时刻。加载器要求该证据文件与发布 manifest 和
两份分别按 `logic`、`editorial_rights` 分类的批准同时一致。

## 可复核命令

```bash
PYTHONPATH=domains python3 -c '\
from pathlib import Path; from hermes_domains.reasoning_pack import validate_reviewed_reasoning_pack; \
print(validate_reviewed_reasoning_pack(Path("domains/released/judgment/lumi-conditional-reasoning-v0-0.1.0-reviewed-local-20260713")))'
```

或运行完整模块测试：

```bash
PYTHONPATH=domains python3 -m unittest domains.tests.test_reasoning_pack
```

任一发布工件、审核证据、记录映射或来源草稿发生变化，都必须重新运行
`domains/tools/create_reviewed_judgment_release.py`，产生新版本并重新进行
受控审核与验证。
