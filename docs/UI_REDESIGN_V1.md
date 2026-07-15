# Lumi UI Redesign V1：现状审计与实施决策

状态：**设计审计完成，实施与视觉验收未在本文档中宣称完成**
审计日期：2026-07-15
代码基线：`cd1ebcb`（重构开始前的已提交 `HEAD`）
适用范围：macOS Tauri 客户端、React 界面、固定八题直接练习与本机学习记录

## 0. 结论先行

Lumi 的业务闭环已经有可靠的机械基础：五个 Core-320 范围、固定八题、答案唯一必填、解释折叠、可选探查占用普通题位、无第九题、恢复会话、事实型总结和本机只读学习视图均已有代码或确定性测试支撑（`client/src/practiceScopes.js:1-50`、`client/src/smartPracticeState.js:236-456`、`client/tests/smartPracticeState.test.js:64-206`）。问题主要不在“功能缺失”，而在外壳和呈现仍把它压缩成一个高密度内部原型。

本轮最重要的设计判断是：

1. 去掉真实 Tauri 窗口里的 900 × 526 假窗口，让应用根节点直接占满原生窗口。
2. 全局只保留“首页 / 刷题 / 学习记录”一套导航；顶部栏只承载页面上下文。
3. 进入题目后切换到专注工作区，题干、材料和选项成为唯一视觉主角。
4. 将当前 7–10.5px 的核心文字提升到可阅读的语义字号；选项点击高度不低于 44px。
5. 把分散在“报告页”和练习页抽屉中的历史、错题、画像、模块证据合并为一套学习记录信息架构。
6. 保持现有 sidecar、题库、评分、证据、会话和回放协议不变；旧 lesson / staged-diagnosis 流程继续作为回归能力保留，但不恢复为默认入口。

这不是对学习效果、可用性、VoiceOver 完整性或外部发布就绪度的结论。仓库明确规定自动化只能证明机械行为，不能证明学习收益或真实可用性（`docs/CONTINUOUS_PRACTICE_V1.md:11-13`、`docs/COMPLETION_AUDIT.md:67-75`）。

## 1. 审计证据边界

### 1.1 本文看了什么

- 产品硬约束：`client/AGENTS.md:9-54`。
- 产品、练习与证据合同：`docs/PRODUCT_SPEC.md:5-19,65-76,83-108`、`docs/SMART_PRACTICE_V2.md:7-31,35-59`、`docs/CONTINUOUS_PRACTICE_V1.md:15-98,106-204,221-307`。
- 当前已提交客户端：`client/src/App.jsx`、`PracticeScreen.jsx`、`SmartPracticeWorkspace.jsx`、`smartPracticeState.js`、`hermesApi.js`、`practiceScopes.js` 及其 CSS/测试。
- 桌面窗口基线：`desktop/src-tauri/tauri.conf.json:12-21`。
- 官方参考研究与采用/拒绝清单：`docs/UI_REFERENCE_AUDIT.md:9-20,22-161,164-234,282-358`。
- 仓库已有视觉基线：`client/qa/*.png`。

本文所有客户端文件行号都指向重构前提交 `cd1ebcb`，避免并行实施中的行号漂移。并行工作区中的未提交实现不被倒推为“已完成”；结果应在文末“后续实现更新”中另行登记。

### 1.2 截图和浏览器限制

`client/qa` 中的 PNG 是**仓库原有基线**，不是本轮新截取的截图。它们在仓库历史中来自 2026-07-11，仍使用 Hermes 名称并展示旧的 Today / Tools / Reports 结构，例如：

- `client/qa/overview-1440x1024.png`
- `client/qa/reports-1440x1024.png`
- `client/qa/comparison-overview-full.png`
- `client/qa/comparison-tools-full.png`

这些图只用于识别旧视觉谱系：蓝色网页背景、居中小窗、重复导航、高密度小字、卡片/表格化呈现。它们**不能证明当前 Core-320 代码的视觉或可访问性状态**；仓库也已明确把早期截图定义为历史证据（`docs/COMPLETION_AUDIT.md:77-86`）。

本轮当前内置浏览器连接受环境兼容性阻断，无法可靠连接到正在运行的本地页面，因此没有伪装成“当前实现截图”的新图，也没有用旧 PNG 代替实时验证。该限制与现有完成审计记录一致：当前客户端机械测试通过，但 fresh visual/accessibility evidence 尚未捕获（`docs/COMPLETION_AUDIT.md:43-50,59-71`）；路线图把恢复受支持的截图/浏览器通道列为下一执行项（`docs/ROADMAP.md:42-50`）。

因此，本文是：

- **代码、合同和历史视觉谱系审计**；
- 不是当前构建的像素级截图审计；
- 不是 VoiceOver、200% 缩放、真实标题栏拖拽或多显示器行为的实机验收。

## 2. 产品合同：界面不能越过的边界

### 2.1 当前用户任务

当前里程碑是 Xingce-only、Core-320：言语理解、判断推理、数量关系、资料分析各 80 题，混合范围复用同一题池；常识判断/政治理论不在可见范围内（`client/AGENTS.md:29-37`、`client/src/practiceScopes.js:1-50`）。

默认学习路径必须保持：

```text
选择范围
→ 最多八个普通题位
→ 每题确定性评分与最短必要反馈
→ 一份事实型组末报告
→ 接受保守推荐或自行选择下一范围
```

依据：`docs/CONTINUOUS_PRACTICE_V1.md:15-30`。

### 2.2 不可破坏的交互不变量

- 正常会话目标固定八个题位，可提前结束；任何干预都不能创建第九题（`docs/CONTINUOUS_PRACTICE_V1.md:32-43`）。
- 答案是唯一必填输入；信心、思路、自我诊断和费曼复述都不能成为门槛（`docs/SMART_PRACTICE_V2.md:14-20`）。
- 正确时直接推进；解释默认折叠。第一次错误只给关键纠偏，重复独立证据才允许微教程或可选短探查（`docs/SMART_PRACTICE_V2.md:18-30`）。
- 只读视图必须保留真实 `null` 和空集合，不得补演示指标（`client/AGENTS.md:42-48`、`docs/CONTINUOUS_PRACTICE_V1.md:83-98`）。
- 错因是可撤回、带证据的假设，不是心理事实；“正确率/速度”是描述性事实，不是掌握度（`docs/CONTINUOUS_PRACTICE_V1.md:49-81`）。
- 本机优先是信任边界，不是每个页面重复出现的营销口号。核心练习和五个只读视图均通过 loopback sidecar 在一台 Mac 上运行（`docs/CONTINUOUS_PRACTICE_V1.md:292-307`）。

## 3. 当前信息架构审计

### 3.1 可达页面和入口

| 当前表面 | 可达方式 | 内部内容 | 判断 |
| --- | --- | --- | --- |
| `overview` 学习首页 | 左侧栏“学习首页”；顶部“首页”；多个回跳按钮 | Hero、运行状态、四模块卡、三条学习记录入口 | 页面有价值，但不是当前默认页；内容承担了宣传、监控、选范围和记录导航四种职责。证据：`client/src/App.jsx:36-40,251-278,296-361,864-923`。 |
| `practice` 直接刷题 | 左侧栏“直接刷题”；顶部“刷题”；应用默认页 | 范围选择、开始/继续入口、错题本/学习档案抽屉、内容池说明、全屏八题工作区 | 核心页面，默认路由正确；入口页仍比开始一组所需内容更重。证据：`client/src/App.jsx:864-923`、`client/src/PracticeScreen.jsx:535-784`。 |
| `reports` 学习报告 | 左侧栏“学习报告”；顶部“学习记录”；侧栏底部“我的学习”；首页多个入口 | 模块证据、学习记录空态、复习状态空态 | 命名、入口和数据职责不一致；真实 history / wrong-book / profile 反而散落在练习页。证据：`client/src/App.jsx:238-278,353-359,657-775`。 |
| 设置 / 使用帮助 | 左侧栏次级按钮，右侧抽屉 | 本机记录说明、旧版帮助文案 | 应保持次级；帮助文案仍指向“今日任务/技能报告”，与固定八题默认路径不一致。证据：`client/src/App.jsx:238-241,846-860`。 |
| 错题本 / 学习档案 | 练习入口页两个按钮，右侧抽屉 | 只读 wrong-question / profile | 有真实价值，但不应只藏在“开始刷题”的页面上下文里；应并入“学习记录”。证据：`client/src/PracticeScreen.jsx:427-531,712-749`。 |
| 八题工作区 | 练习入口主 CTA 打开覆盖层 | loading、question、feedback、summary、error | 方向正确：它是专注层而不是右侧窄抽屉；但覆盖范围目前只到内部假窗口。证据：`client/src/PracticeScreen.jsx:692-710,773-780`、`client/src/SmartPracticeWorkspace.jsx:395-498`、`client/src/smart-practice.css:1-16`。 |

### 3.2 重复入口

1. `Sidebar` 和 `Topbar` 各自用同一组 `overview / practice / reports` 切页；两套控件承担完全相同的全局导航职责（`client/src/App.jsx:36-40,211-224,251-276`）。
2. `reports` 还从侧栏底部“我的学习”进入；首页“查看学习报告 / 本组结果 / 我的学习”继续重复指向同一页面（`client/src/App.jsx:243-246,311-314,353-359`）。
3. “学习记录”概念被拆成报告页的三个 tab、练习页的错题/档案抽屉和首页的三条入口。用户必须先理解代码组织，才能知道去哪里找真实记录。
4. 本机状态在侧栏连接块、顶部栏身份/隐私、首页状态卡与承诺、练习页角标、题目提交下方再次出现（`client/src/App.jsx:189-278,296-334`、`client/src/PracticeScreen.jsx:632-640,692-701`、`client/src/SmartPracticeWorkspace.jsx:462-464`）。状态是真实信息，但呈现次数过多。

### 3.3 旧流程、隐藏流程与死入口

以下代码在基线中仍存在，但没有从 `App` 的三个实际页面分支挂载：

- `ToolsScreen` 及其强制信心、probe、verification 的旧 staged flow：`client/src/App.jsx:365-635`。
- `AuxiliaryScreen`：`client/src/App.jsx:802-822`。
- `CommandPalette`：`client/src/App.jsx:824-844`。
- 静态 `SKILL_GROUPS`、`ACTIVITY_ROWS`、`REVIEW_ROWS`：`client/src/App.jsx:62-109`，基线无实际消费。
- `LegacyPracticeScreen`、`PracticePanel` 与 `LessonWorkspace`：`client/src/PracticeScreen.jsx:98-407`；实际 export 在 `client/src/PracticeScreen.jsx:535` 后直接进入 continuous practice。

这与产品合同相符：`/v1/lessons` 和 stepwise `/v1/attempts` 仍是回归接口，不是默认 learner path（`docs/COMPLETION_AUDIT.md:36-39,77-86`）。本次重构不应把它们重新暴露，也不应在未确认所有回归测试和调用方前直接删除。更稳妥的处理是：

- 从主文件和主 CSS 中逐步隔离为明确的 legacy/regression 模块；
- 不加入主导航或首页；
- 在后续独立清理任务中用调用图、构建、测试和 sidecar 回归证明可删性。

### 3.4 模态、抽屉、全屏与恢复状态

| 类型 | 当前实现 | 审计结论 |
| --- | --- | --- |
| 通用右侧抽屉 | `SidePanel` 使用 scrim、`role="dialog"`、`aria-modal`（`client/src/App.jsx:282-293`） | 适合设置/帮助等短次级内容；基线没有 Escape、焦点锁定和返回焦点代码，不应承载长学习流程。 |
| 错题/档案抽屉 | `PracticeInsightsPanel`（`client/src/PracticeScreen.jsx:427-531`） | 折叠错题详情合理，但应该从学习记录页面可达；同样缺少显式 Escape/焦点管理。 |
| 专注工作区 | `SmartPracticeWorkspace` 全覆盖层与 dialog 语义（`client/src/SmartPracticeWorkspace.jsx:395-498`） | 保留这一模式，并让它覆盖真实应用根区域；进入后隐藏全局导航。 |
| 工作区焦点 | 初始把焦点放在关闭按钮，手写 Tab trap，退出时归还焦点（`client/src/SmartPracticeWorkspace.jsx:284-313`） | 已有可访问性基础，但首焦点应服务答题；关闭按钮首焦点会增加键盘操作成本。 |
| 页面级离线 | sidecar 非 connected 时替换练习入口，提供重连（`client/src/PracticeScreen.jsx:617-629`） | 正确，应保持为页面状态，不新建“离线页面”。 |
| 工作区错误 | start/submit 可重试或结束（`client/src/SmartPracticeWorkspace.jsx:483-493`） | 基本恢复路径完整；`retryKind="continue"` 没有对应重试按钮，只能结束（`client/src/smartPracticeState.js:340-358`），需补明确恢复策略。 |
| 恢复会话 | overview 的 active session 锁定原范围并显示继续（`client/src/PracticeScreen.jsx:544-600,692-708`） | 正确；要清楚区分“用户主动提前结束”与“进程中断后恢复”。 |
| 关闭保存失败 | 先退出工作区，再显示“再次打开时尝试恢复”（`client/src/PracticeScreen.jsx:603-615,755`） | 能防止假成功，但提示应靠近下一次继续入口，并保留可操作的重试/恢复文案。 |

### 3.5 目标信息架构

```text
Lumi
├── 首页
│   ├── 开始推荐的一组（唯一主 CTA）
│   ├── 四模块 / 混合快捷选择
│   └── 最近一组极简摘要
├── 刷题
│   ├── 智能范围与四模块选择
│   └── 专注八题工作区
│       ├── 题目
│       ├── 最小反馈 / 按需解析
│       ├── 证据触发的微教程 / 可选探查
│       └── 组末总结 / 下一组
└── 学习记录
    ├── 最近练习
    ├── 错题
    └── 模块证据 / 可撤回错误模式

次级：设置、帮助；未来有真实跨页命令时再恢复 ⌘K
```

具体决策：

- 合并：当前 `reports`、练习页 profile/wrong-book 抽屉、未来 history/session report 统一到“学习记录”。五个只读 API 本来就从同一 trace 重建（`docs/CONTINUOUS_PRACTICE_V1.md:83-100,106-204`）。
- 移出主导航：设置、帮助；错因辨析、微教程、迁移验证、复习属于策略或上下文动作，不是一级产品模块。
- 不作为独立页：loading、offline、error、empty、resume 都是其所属页面/任务的状态。
- 延期：`⌘K` 只有在首页/记录/设置之间存在真实快捷命令集时再交付；依赖选择见 `docs/UI_REFERENCE_AUDIT.md:323-358`。
- 保留但隐藏：legacy lessons/tools 仅作回归，不以“功能丰富”之名重新进入可见 IA。

## 4. 逐页视觉层级审计

### 4.1 应用外壳

**当前第一视觉焦点**：不是内容，而是蓝/白网页画布中居中的小应用框；历史 QA 图清楚保留了这一谱系。代码也把真实窗口再次缩成 `width: min(900px, ...)`、`height: min(526px, ...)`，外加 20px 画布、边框、圆角和阴影（`client/src/styles.css:78-98`）。

**主要问题**：

- 真实 Tauri 窗口基线本身已经支持 1320 × 880、最小 1024 × 680 和自由缩放（`desktop/src-tauri/tauri.conf.json:12-21`），内部假窗口浪费可用空间并迫使所有文字缩小。
- 侧栏只有 166px，顶部只有 47px，视觉像嵌入网页的 demo，而不是原生应用内容面（`client/src/styles.css:85-115,363-380`）。
- 滚动条被全局隐藏，用户无法感知长页面位置（`client/src/styles.css:454-465`）。

**决策**：应用根直接填满 Tauri content area；普通页面可滚动但保留低噪声滚动反馈；边框/阴影只用于真实浮层。窗口默认目标 1180 × 760，最小目标 960 × 640，最终值必须经过四尺寸压力测试后冻结。

### 4.2 首页

**当前第一视觉焦点**：Hero “刷题，就是学习。”，但右侧 Lumi 运行状态卡拥有接近同等面积和边框权重（`client/src/App.jsx:304-335`）。

**用户主要操作**：开始一组 8 题。代码同时给出“查看学习报告”、混合练习、四个模块卡和三个学习记录按钮（`client/src/App.jsx:311-359`）。虽然只有“开始一组”使用 primary 样式，但一屏有十余个可点击入口。

**问题**：

- Hero、状态监控、范围选择和记录导航并列，首页既像营销页又像 dashboard。
- 运行状态卡、顶部隐私、侧栏连接状态重复传达同一信任信息。
- 四张模块卡 + 三张记录卡形成卡片墙；用户在“直接开始”前要先扫描大量说明。
- 首页模块卡只跳到 practice，未携带所选 scope；按钮文字暗示已选择方向，实际还需二次选择（`client/src/App.jsx:342-349`）。

**决策**：首页只保留一个主 CTA；推荐范围和理由用一行文本；四模块/混合为紧凑列表或 segmented rows；最近一组用单行摘要；本机状态只保留一个侧栏底部低噪声指示。模块快捷入口必须把 scope 意图传入刷题页，不能只是泛跳转。

### 4.3 刷题范围入口

**当前第一视觉焦点**：四模块选择器，其后是大号“固定 8 题”入口块（`client/src/PracticeScreen.jsx:631-710`）。

**用户主要操作**：选择范围并开始/继续一组，方向正确且只有一个 primary CTA。

**问题**：

- 页面依次展示标题、范围说明、四模块、混合、入口大卡、两张记录卡、错误提示、版本化内容池与版权提示，开始动作下方仍有大量后台/内容运营信息（`client/src/PracticeScreen.jsx:642-770`）。
- “本机运行”“答案唯一必填”“内容版本”与全局信息重复；内容 SHA/版本对审计重要，但不应占据 learner 首页主层级。
- scope label 只有 7–9px（`client/src/smart-practice.css:793-817`），入口说明 8.5px（`client/src/smart-practice.css:853-899`）。
- active session 锁定选择器是正确的，但需要在视觉上明确“继续原组”优先，并把“结束原组后改范围”作为次级说明。

**决策**：压缩为 PageHeader + 一个范围列表 + 一个开始/继续区；内容包版本移到设置/关于或可展开详情；错题和档案移至学习记录。

### 4.4 专注刷题工作区

**当前第一视觉焦点**：问题卡；全覆盖层、进度、题号、关闭、选项和全宽提交按钮的结构是正确的（`client/src/SmartPracticeWorkspace.jsx:395-465`）。

**用户主要操作**：选择答案后提交；反馈后进入下一题。

**问题**：

- 内容最大宽度只有 620px，卡片被装进 900px 假窗口（`client/src/smart-practice.css:96-115`），未使用桌面空间，也无法形成资料分析双栏。
- 题干 10.5px、选项 8.5px、选项最小高度 33px；均低于阅读和 44px 点击目标（`client/src/smart-practice.css:137-186`）。
- 每道题下方重复“本次真实作答/本机”说明，和题目争夺末端注意力（`client/src/SmartPracticeWorkspace.jsx:462-464`）。
- 选择态除了颜色还保留 radio，语义尚可；但没有 A/B/C/D、1/2/3/4、上下键和 Enter/continue 的显式快捷逻辑。基线键盘监听只处理 Escape 与 Tab trap（`client/src/SmartPracticeWorkspace.jsx:284-313`）。
- 当前 question normalizer 只有 `prompt/options/ordinal/eyebrow`，没有结构化 `material`、图表或图形字段（`client/src/smartPracticeState.js:31-48`）。因此长材料、资料分析双栏、图形题不能在不改协议的前提下声称完成；本轮只能保证长 `prompt` 的排版与单栏退化。

**决策**：普通题内容宽 720–820px；题干 17px / 1.72；选项 15px、最小 48px；大窗口预留响应式材料/问题双栏容器，但只有现有合同真的提供结构化材料时启用，不从字符串猜测业务语义。

### 4.5 反馈、微教程与探查

**当前第一视觉焦点**：正误 verdict；其下依次是折叠解析、条件性微教程、条件性 probe（`client/src/SmartPracticeWorkspace.jsx:53-147`）。

**优点**：

- 正确/错误都没有常驻聊天或大庆祝页。
- 完整解析用 `<details>` 默认折叠（`client/src/SmartPracticeWorkspace.jsx:81-86`）。
- 微教程和 probe 只在 sidecar 返回时出现；测试验证普通错误不会自行制造干预（`client/tests/smartPracticeState.test.js:93-163`）。
- probe 明确“可选/占用下一题位/可跳过”，符合 frozen contract（`client/src/SmartPracticeWorkspace.jsx:99-140`）。

**问题**：

- 反馈正文、解析、微教程和 probe 大量使用 7–9px；教学内容可读性不足（`client/src/smart-practice.css:255-426`）。
- probe 选项最小 28px，不满足桌面点击目标。
- 反馈、微教程、probe 都被同一圈层的细边框包裹，层级靠多个小盒子而不是排版和间距。
- 探查保存失败后虽然可重试/跳过，但跳过同样需要 sidecar 接受；应解释“进度未丢失”，避免用户以为必须完成才能退出。

**决策**：反馈在原题上下文中就地替换；正确只显示一句关键点与“下一题”；错误显示正确答案、一句纠偏、折叠解析与“下一题”；微教程用浅色连续内容区，不做聊天气泡；probe 保留一个 primary “确认”和一个次级文本“暂时跳过”。

### 4.6 组末总结

**当前第一视觉焦点**：完成图标、结果标题、2 列摘要、错题折叠列表和“一键下一组”（`client/src/SmartPracticeWorkspace.jsx:150-207`）。

**优点**：

- 有且只有一个 primary terminal action。
- UI 实际只显示 `primaryWeakness`，错误详情折叠；恢复会话不会补造缺失错题（`client/src/smartPracticeState.js:195-233`、`client/tests/smartPracticeState.test.js:243-276`）。
- 第八题会剥离 probe，确保没有第九题（`client/tests/smartPracticeState.test.js:165-206`）。

**问题**：结果描述 8.5px，事实 label 7px，错题说明 7–9px（`client/src/smart-practice.css:436-545`）；总结看似“简洁”，实际是靠缩小而不是删减信息。两列边框、错题边框、details 边框叠加，仍有内部 dashboard 感。

**决策**：以 6/8 结果为主标题；最多一个证据支持的薄弱点；“证据不足，暂不判断”直接显示；恢复不完整提示保留；错题用文档式 disclosure；下一组为唯一 primary，关闭保持标题栏控制。

### 4.7 学习报告 / 学习记录

**当前第一视觉焦点**：标题、三个 tab、四个筛选控件和技能表格（`client/src/App.jsx:698-756`）。

**问题**：

- 页面叫“学习报告”，顶部导航叫“学习记录”，概念不稳定。
- “学习记录/复习状态”两个 tab 目前只显示通往刷题的空态（`client/src/App.jsx:768-774`），真实错题和 profile 却在练习页抽屉。
- 筛选、表头、证据数和详情使用 7–9px（`client/src/styles.css:1122-1397`），桌面表格密度过高。
- `MasteryTrack` 用比例条表达“当前判断”，用户容易读成伪精确掌握度；冻结合同要求生产 profile 使用 `no_evidence / insufficient / needs_attention / developing / consistent` 等可解释分类，而不是 latent mastery（`docs/CONTINUOUS_PRACTICE_V1.md:65-76,145-165`）。
- `refreshSidecar` 用一个 `Promise.all` 同时加载 health、capabilities、skill report、catalog 和 lessons；任一非核心读接口失败都会把整个 sidecar 标为 offline/error 并阻断刷题（`client/src/App.jsx:870-891`）。报告失败不应冒充题目服务离线。

**决策**：改名“学习记录”，用列表/文档结构承载最近组、错题和模块证据；显示事实、证据量和分类状态，不画伪精确掌握条；各读模型独立降级，核心 health/capabilities 成功时刷题仍可用。

### 4.8 设置、帮助、离线、空态

- 设置/帮助适合作为轻量浮层或独立次级页面，但现有自研 dialog 需补 Escape、焦点锁定、初始焦点和返回焦点验证（`client/src/App.jsx:282-293,846-860`）。
- 离线状态说明“不会请求云端”且提供重连，符合本地优先边界（`client/src/PracticeScreen.jsx:617-629`）；不应同时保留顶部、侧栏、卡片和按钮下四份离线说明。
- profile/wrong-book 的真实空态保留零和 `null`，当前 normalizer 测试已经防止 demo 填充（`client/tests/practiceInsights.test.js:82-109,163-196`）。
- 错误提示应说明影响范围：报告失败不影响刷题、提交失败保留本题、结束失败将在下次恢复；不要统一显示“服务离线”。

## 5. 固定八题体验逐环节审计

| 环节 | 当前行为 | 状态 | V1 要求 |
| --- | --- | --- | --- |
| 选择范围 | 四模块 + 混合；默认资料分析；active session 覆盖新选择（`client/src/practiceScopes.js:7-50`、`client/src/PracticeScreen.jsx:580-600`） | 机械正确 | 首页快捷入口应传入 scope；继续本组始终高于新建组。 |
| 开始/恢复 | overview 读取 active session，显示已答和剩余题位（`client/src/PracticeScreen.jsx:692-708`） | 机械正确 | 明确“继续原组”，不要把推荐切换误写成强制。 |
| 加载 | 工作区显示准备 8 题和本机处理（`client/src/SmartPracticeWorkspace.jsx:430-436`） | 可用但重复 | 一次简短 status；超时后显示重试与返回。 |
| 题目 | prompt + option/text answer；答案为空时 submit disabled（`client/src/SmartPracticeWorkspace.jsx:438-465`） | 合同正确，视觉失败 | 题干 17px、舒适行长；长文本自然分段；不要重复本机说明。 |
| 选项 | 整行 label，可 selected（`client/src/SmartPracticeWorkspace.jsx:18-37`） | 语义基础好，尺寸失败 | ≥48px；hover/focus/selected/disabled 不只靠颜色；长选项不跳动。 |
| 快捷键 | Escape + Tab trap；原生表单可在部分焦点下 Enter（`client/src/SmartPracticeWorkspace.jsx:284-313,338-359`） | 不完整 | A–D、1–4、↑↓选择；Enter 提交/继续；Escape 退出或关闭次级层；防按键重复提交。 |
| 正确反馈 | verdict + folded explanation + next（`client/src/SmartPracticeWorkspace.jsx:68-86,141-145`） | 产品逻辑正确 | 压缩成内联反馈；不庆祝、不强制读解析。 |
| 首次错误 | correct option + key principle + folded explanation（`client/src/SmartPracticeWorkspace.jsx:68-86`） | 产品逻辑正确 | 纠偏优先，解析次级；仍只有一个主动作。 |
| 微教程 | 只在 payload 提供时出现（`client/src/smartPracticeState.js:51-68,84-98`） | 机械正确 | 30–60 秒可读；不是聊天；字号和行高达标。 |
| 可选探查 | 可跳过、提交后 server count 消耗一个题位（`client/src/SmartPracticeWorkspace.jsx:99-140`、`client/src/smartPracticeState.js:374-398`） | 机械正确 | 选项 ≥44px；最后题位绝不显示；失败说明进度状态。 |
| 第八题 | final probe 被客户端去除；continue 后 summary（`client/src/smartPracticeState.js:301-350`） | 正确 | 继续保持 deterministic guard，不只依赖视觉。 |
| 组末 | 真实得分、最多一个主要薄弱点、错题折叠、下一组（`client/src/SmartPracticeWorkspace.jsx:150-207`） | 逻辑正确，层级过密 | 保留事实/假设区别；唯一 primary 是下一组。 |
| 提交失败 | reducer 保留 answer/question，提供返回本题重试（`client/src/smartPracticeState.js:416-434`） | 正确 | 错误靠近操作；焦点回错误标题/重试；不清空选择。 |
| 缺下一题 | 进度保留但 `retryKind=continue`（`client/src/smartPracticeState.js:340-358`） | 恢复不完整 | 提供“重试加载下一题”或清楚结束并保证可恢复，不能只落入无对应动作的 error。 |
| 主动退出 | Escape/关闭调用 end-early；saving 时禁用关闭（`client/src/SmartPracticeWorkspace.jsx:238-247,413-422`） | 基础正确 | 若已有作答，清楚说明这是“提前结束”而非“稍后继续”；中断恢复是另一语义。 |
| 崩溃/中断恢复 | active session 与 pending probe 可恢复（`client/src/smartPracticeState.js:260-299`、`client/tests/smartPracticeState.test.js:278-306`） | 正确 | 恢复后总数权威、旧错题细节不补造；视觉显示数据覆盖范围。 |
| 长材料/图表 | 当前 normalizer 没有独立结构字段（`client/src/smartPracticeState.js:31-48`） | 未建立视觉证据 | 本轮只可验证长 prompt；图表/双栏需现有协议出现对应数据后单独验收，不能伪造支持。 |

## 6. 工程结构审计

### 6.1 主要债务

| 问题 | 证据 | 风险 | 决策 |
| --- | --- | --- | --- |
| 巨型 `App.jsx` | 929 行；页面、sidecar 读取、dead tools、report、dialog 混在一处 | 每次改 shell 都可能碰到旧产品流；难以确认死代码 | 拆 `AppShell`、Home、LearningRecords；App 只管路由与顶层数据状态。 |
| 新旧练习同文件 | `PracticeScreen.jsx` 784 行；98–407 是 legacy，535–784 是当前入口 | 旧信心/lesson 逻辑容易误回到默认路径 | 保留行为，物理隔离 legacy；本轮不删除协议。 |
| CSS 单体过大 | `styles.css` 2882 行，`smart-practice.css` 1371 行 | 全局选择器和残留规则难以追踪，响应式互相覆盖 | 先建 tokens + shell/page/practice 分层；按已迁移组件删除确认无调用的规则。 |
| token 不完整 | `:root` 只有颜色为主（`client/src/styles.css:1-20`）；字号、间距、圆角散落 | 7、7.5、8.5、9、10.5px 大量出现，无法系统修复 | 增加语义 typography/spacing/radius/control tokens；禁止核心组件任意字号。 |
| 全局样式污染 | `.button`、`.screen`、`.side-panel`、`.empty-state` 与多页面特殊样式共存；页面滚动条全局隐藏（`client/src/styles.css:454-465,1100-1120,1508-1568`） | 新页面继承不相关密度/尺寸 | shell 基础样式只负责布局与 primitives；页面样式局部命名。 |
| 数据可用性耦合 | 五个启动请求使用 `Promise.all`（`client/src/App.jsx:870-891`） | lesson/report 失败会阻断核心练习 | 核心运行能力与次级只读模型分开加载、分开错误状态。 |
| 自研 dialog 行为不统一 | workspace 有 focus trap；SidePanel/insight panel 只有 ARIA 和 scrim | 键盘/屏幕阅读器体验不一致 | 先抽统一 Dialog 行为；若手写实现无法稳定通过测试，再按条件引入 Radix Dialog。 |
| 命令面板只有死组件 | `CommandPalette` 定义但未挂载（`client/src/App.jsx:824-844,914-927`） | 宣称 ⌘K 与实际不符 | V1 要么实现真实命令注册和键盘测试，要么明确延期，不保留假入口。 |

### 6.2 可复用的良好基础

- `smartPracticeReducer` 已把题目、反馈、probe、summary 和 error phase 结构化，适合保留为展示层的权威状态（`client/src/smartPracticeState.js:236-456`）。
- API 层有 5 秒超时、request ID、contract/response/unavailable 区分和严格 schema 校验（`client/src/hermesApi.js:14-29,71-174,452-505`）。
- scope 和 Core-320 digest/数量被固定校验，不应把这些规则复制进组件（`client/src/practiceScopes.js:1-94`）。
- HTML 已大量使用 `fieldset/legend`、`details/summary`、`progress`、`aria-live` 与 dialog 语义，是重构可访问性的起点（`client/src/SmartPracticeWorkspace.jsx:18-49,68-147,395-495`）。
- fixed-eight、probe、末题、resume、duplicate submit、空 read model 已有确定性测试；视觉重构应围绕这些测试保持行为，而不是重写学习协议（`client/tests/smartPracticeState.test.js:64-206,243-330`、`client/tests/practiceInsights.test.js:82-196`）。

### 6.3 组件边界建议

本轮只提取有至少两个真实使用场景或能隔离高风险行为的组件：

- `AppShell`：侧栏、页面上下文栏、主内容、低噪声本机状态。
- `PageHeader`：标题、说明和最多一个页面动作。
- `Button` / `IconButton`：尺寸、focus、disabled、loading。
- `DialogSurface`：Escape、focus trap、initial focus、return focus、scrim。
- `InlineNotice` / `EmptyState` / `LoadingState`：跨首页、记录、练习复用。
- `QuestionCanvas` / `AnswerOption` / `PracticeProgress`：专注练习核心。
- `AnswerFeedback` / `ExplanationDisclosure` / `MicroTutorial` / `DiagnosticProbe`。
- `GroupSummary` / `RecordList`。

不建设大而全的 design-system package，也不为了 shadcn 初始化 Tailwind。参考和依赖结论见 `docs/UI_REFERENCE_AUDIT.md:282-358`。

## 7. 最严重的五个界面问题

| 排名 | 严重问题 | 为什么严重 | 直接修复判断 |
| --- | --- | --- | --- |
| P0-1 | 真实窗口内再次绘制 900 × 526 假窗口 | 浪费大部分桌面空间，是所有小字号、密度和“网页 demo 感”的上游原因 | 删除 `.desktop-canvas` 展示画布和 `.app-window` 固定盒；根布局 100% 填满 Tauri。 |
| P0-2 | 题干 10.5px、选项 8.5px/33px，高频阅读与点击不合格 | 直接影响每一题的速度、准确性、疲劳和可访问性 | 题干 17px，选项 15px/≥48px，核心正文不低于 14px。 |
| P0-3 | 一套页面有两套全局导航，学习记录又被拆成报告页和练习抽屉 | 用户无法建立稳定位置记忆，也不清楚“报告/档案/错题/记录”的关系 | 只保留左侧三项；统一“学习记录”页面；顶部只显示上下文。 |
| P0-4 | 专注刷题缺少完整键盘路径与长材料布局证据 | 桌面学习产品无法高效连做八题；资料分析/图形题的真实压力尚未被 UI 承接 | 增加 A–D、1–4、方向键、Enter、Escape；长 prompt 先可靠排版，结构化材料另行合同验收。 |
| P1-5 | 首页、范围页和总结依赖卡片/边框与重复本机说明制造层级 | 题目和开始动作被状态、说明、版本信息及多入口稀释 | 用排版、留白、列表和一个主 CTA；本机状态全局只保留一处，错误时再上下文化。 |

工程上的最高风险补充是启动请求的 `Promise.all` 耦合和 modal 行为不一致；它们会把次级数据错误放大成核心不可用或键盘陷阱，必须与视觉重构同时修正。

## 8. V1 设计决策

### 8.1 北极星

**安静的学习工作台**：打开应用后几秒内开始一组；做题时只看题目；Agent 只在证据需要时出现；结束后只看到下一步真正需要知道的事实。

### 8.2 桌面框架

- 默认窗口目标：1180 × 760；最小目标：960 × 640；可自由缩放。
- 保留 macOS 原生窗口装饰和标题栏能力，不用全自绘标题栏换取表面“沉浸”。Tauri 取舍依据见 `docs/UI_REFERENCE_AUDIT.md:50-72`。
- 展开侧栏 216px，收起 64px；三个主导航 + 弹性空白 + 一个本机状态 + 设置。
- 顶部上下文栏不再显示全局 tabs；只显示当前页标题/范围和少量当前操作。
- 专注工作区覆盖应用内容，隐藏侧栏和普通顶部栏，只留范围、题号、进度、退出。

### 8.3 视觉 token

建议最小语义层级：

| Token | 建议值 | 用途 |
| --- | --- | --- |
| `--font-caption` | 12px / 1.45 | 极次要、非交互元数据 |
| `--font-body-sm` | 13px / 1.55 | 次级说明 |
| `--font-body` | 15px / 1.65 | 普通正文、选项 |
| `--font-body-lg` | 17px / 1.72 | 中文题干 |
| `--font-section` | 18px / 1.4 | 小节标题 |
| `--font-page` | 28px / 1.25 | 页面标题 |
| `--control-sm/md/lg` | 32 / 40 / 48px | 控件高度；答案选项使用 lg |
| `--space-*` | 4/8/12/16/20/24/32/40/48/64 | 统一间距 |
| `--radius-*` | 6/8/12/16px | 小控件/输入/面板/浮层 |

颜色保持白色主内容面、中性灰背景、接近黑正文和低频 Lumi 紫；正确/错误使用低饱和绿/砖红并配文字或图标，不只靠颜色。阴影只给 dialog/menu/popover。该方向符合 `client/AGENTS.md:15-27` 和参考审计的拒绝项（`docs/UI_REFERENCE_AUDIT.md:74-96,121-161`）。

### 8.4 页面决策

- 首页：一个“开始一组”主 CTA；推荐范围/理由；紧凑五范围；最近一组；一个低噪声本机状态。
- 刷题入口：选择范围后直接进入，不加配置向导；active session 优先继续。
- 工作区：题目最高权重；不显示 Agent 头像、聊天、报告、服务状态或内部 ID。
- 反馈：正确快速前进；错误最小纠偏；完整解析折叠；微教程/探查只由现有 policy payload 触发。
- 总结：真实结果 + 最多一个薄弱点 + 恢复数据范围说明 + 折叠错题 + 下一组。
- 学习记录：最近练习、错题、模块证据用文档/列表呈现；空值保持空，不用 demo 指标或掌握百分比。

### 8.5 Agent 介入形式

允许：一句关键纠偏、折叠解析、短微教程、一个最小 probe、一个推荐理由、一个组末证据摘要。
拒绝：常驻聊天栏、大头像、每题对话、强制反思、连续工具市场、把错误模式写成心理事实。

### 8.6 依赖决策

- V1 默认不新增依赖，继续 React + 语义 HTML + 原生 CSS + Phosphor。
- Radix 只在统一 Dialog/Popover 的焦点与键盘测试无法靠现有代码可靠通过时，按单原语引入。
- 不初始化 shadcn，不迁移 Tailwind，不引入新状态管理或动画框架。
- `cmdk` 与 `⌘K` 同步决策：没有真实命令集合就一起延期，不保留无入口死组件。

完整依据：`docs/UI_REFERENCE_AUDIT.md:282-358`。

## 9. 纵向切片

V1 先交付一条可完整验证的 learner slice，而不是先把所有静态页面“换皮”：

```text
真实 Tauri 窗口
→ 首页一个主 CTA / 传入范围
→ 五范围选择或继续 active session
→ 题目 loading
→ 普通题选择 + 键盘提交
→ 正确最短反馈
→ 首错最小纠偏 + 折叠解析
→ policy 返回时的微教程 / 可跳过 probe
→ 第八题总结
→ 一键下一组
→ 学习记录看到同一 trace 的本组/错题/模块事实
```

同时贯穿三条降级支线：

```text
启动失败 → 重试 / 返回
提交失败 → 保留本题与答案 → 重试
进程中断 → 恢复同一 session / pending probe → 不补造旧明细
```

实施顺序：

1. 建 token 和真实窗口 shell；移除重复顶部导航。
2. 让首页 CTA、模块快捷入口和刷题入口共享明确的 scope intent。
3. 重排 `SmartPracticeWorkspace`，同时补键盘、焦点、长文本和错误恢复。
4. 保持 reducer/API 合同，重做 feedback/probe/summary 的视觉层级。
5. 合并 Learning Records，逐 read model 降级，不让报告失败阻断刷题。
6. 在四个窗口尺寸复验全部关键状态，再清理已确认无调用的旧 CSS。

每一步都应先运行客户端测试和 build；最后再运行仓库核心验证。不得为了视觉交付删除 fixed-eight、resume、empty/null 或 contract-fail-closed 测试。

## 10. 明确非目标

V1 不做：

- 修改 Core-320 题库、答案、证据 family、评分、推荐阈值、diagnosis 或 KT 语义；
- 把 common/political knowledge、Shenlun、Interview 暴露到当前客户端；
- 恢复 mandatory lesson / confidence / Feynman / self-diagnosis；
- 常驻 Agent chat、AI 输入框、工具市场、雷达图、积分、连胜或排行榜；
- 云同步、账户、多用户、协作或 cohort dashboard；
- 全量导入 Perseus/OATutor、Tailwind/shadcn 或新的状态管理框架；
- 直接删除 legacy lesson/attempt API 或未完成调用图证明的旧组件；
- 在没有结构化材料/图表合同的情况下假装完成资料分析双栏或图形题渲染；
- 宣称学习收益、掌握度、心理原因、延迟保持提升、内容外发权利或生产发布就绪。

这些非目标与冻结合同一致（`docs/CONTINUOUS_PRACTICE_V1.md:274-307`、`docs/COMPLETION_AUDIT.md:92-100`）。

## 11. 风险与缓解

| 风险 | 影响 | 缓解/证据要求 |
| --- | --- | --- |
| 当前浏览器通道不可用 | 无法在本轮可靠生成当前 before/after 截图 | 不复用旧 PNG 冒充新图；恢复通道后补 1440×900、1200×760、960×640、最小尺寸。 |
| 并行实施导致行号/文件漂移 | 审计与最终实现混淆 | 本文固定 `cd1ebcb`；实际变更只写入文末更新区并附 commit/diff。 |
| 放大字体后内容溢出 | 表格、侧栏、长选项、中文材料可能破版 | 不缩回 8px；改重排、换行、滚动和信息删减；四尺寸压力测试。 |
| 资料/图表结构未进入 client question model | 无法真正验证双栏和图形题 | 先保证长 prompt；把协议能力缺口列为单独产品/合同任务，本次不猜字段。 |
| 旧 CSS 与 dead components 仍在 | 新旧规则互相覆盖、bundle/维护成本高 | 先隔离再删；每批清理用 `rg` 调用图、测试、build 和实际状态截图证明。 |
| dialog 手写行为分叉 | 焦点丢失、Escape 不一致、VoiceOver 读序错误 | 建统一行为测试；不能稳定满足时单独引入 Radix Dialog。 |
| read-model 错误被放大为全局离线 | 用户无法刷题或误以为数据丢失 | 核心 health/capabilities 与报告/history/profile 分开状态；错误文案明确影响范围。 |
| 快捷键与文本输入冲突 | A–D/Enter 可能误触 textarea 或重复提交 | 只在非文本编辑目标激活；检查 composing/repeat/disabled/submitting；加确定性测试。 |
| 提前退出与中断恢复语义混淆 | 用户以为稍后可继续，实际 session 已 ended_early | 关闭控件明确“提前结束”；崩溃/连接中断才显示“继续本组”。 |
| 视觉更新被误读为产品有效性 | 成熟外观可能掩盖尚未完成的真实 learner evidence | 继续保留事实/假设/未知边界；遵守 `docs/EVALUATION.md:192-208,234-247`。 |

## 12. 可验证验收清单

以下条目是实施验收，不是本文已通过的声明。

### 12.1 信息架构与窗口

- [ ] `App` 根内容直接占满 Tauri content area；DOM/CSS 中没有居中 900 × 526 假窗口和网页展示边距。
- [ ] 初始窗口在 1120–1200 × 720–800 范围，最小窗口在 900–960 × 620–660 范围；可缩放且关键操作不重叠。
- [ ] 全局只有“首页 / 刷题 / 学习记录”一套导航；顶部不重复这三项。
- [ ] 专注刷题时不显示侧栏、报告入口、本机状态卡或普通页面 tabs。
- [ ] 设置/帮助为次级入口；legacy tools/lesson 不进入可见 IA。

### 12.2 视觉层级

- [ ] 首页最多一个 primary CTA，模块入口不会与它同权竞争。
- [ ] 核心正文与选项 ≥14px，题干 16–18px，关键 caption ≥11px；不存在 7–10px 核心交互文字。
- [ ] 普通内容靠留白、分组和 divider 建层级；阴影仅用于浮层。
- [ ] Lumi 紫只用于主操作、选中和 focus；正确/错误还带图标或文字，不只靠颜色。
- [ ] 本机状态正常时全局只出现一处；连接/保存失败时才在上下文额外说明。

### 12.3 固定八题与数据真实性

- [ ] 五个 scope 可选；选择某模块后开始的是同一 scope，而不是再回默认资料分析。
- [ ] 每题答案是唯一必填项；无 confidence/reasoning/self-diagnosis gate。
- [ ] probe 可跳过、消耗普通题位；第八题后无第九题。
- [ ] 正确反馈可立即进入下一题；解析默认折叠。
- [ ] 首错只显示正误、正确答案、一句纠偏、折叠解析与下一题。
- [ ] 微教程/probe 只在 sidecar payload 提供时出现。
- [ ] 总结显示真实结果、最多一个主要薄弱点、折叠错题和唯一 primary “下一组”。
- [ ] resumed summary 不补造恢复前错题；`null` 和空集合不被 demo 指标替换。
- [ ] 学习记录的本组、错题和模块事实能追溯到同一 read model/trace。

### 12.4 键盘、焦点与语义

- [ ] A/B/C/D 与 1/2/3/4 选择答案；↑/↓移动；Enter 提交或继续；Escape 关闭次级层/退出专注模式。
- [ ] 快捷键不在 textarea/input 编辑或 IME composing 时劫持输入，不对 key repeat 重复提交。
- [ ] 所有 interactive target ≥44px（关闭图标可用足够 hit area）。
- [ ] Dialog 有初始焦点、Tab loop、Escape、返回焦点；错误出现后焦点/announce 可感知。
- [ ] `fieldset/legend`、`progress`、`details/summary`、`aria-live/busy` 语义继续保留。
- [ ] `prefers-reduced-motion` 生效；200% 缩放不隐藏主操作。
- [ ] VoiceOver 读序、系统高对比度和不同显示缩放需在真实 macOS 上人工验收。

### 12.5 错误与恢复

- [ ] health/capability 成功时，report/lesson/history/profile 单项失败不会阻断刷题。
- [ ] start failure 可重试；submit failure 保留选择并可重试；next-question failure 有明确重试或安全退出。
- [ ] active session 与 pending probe 能恢复；主动提前结束不会被写成“稍后继续”。
- [ ] 所有错误都说明影响范围，不声称数据已保存或丢失，除非 sidecar 有确定证据。

### 12.6 工程与回归

- [ ] 页面/shell/practice 样式分层，语义 tokens 成为字号、间距、圆角和控件尺寸的来源。
- [ ] `App` 不再包含 tools/report/home/dialog 的全部实现；legacy 逻辑已隔离但未无证据删除。
- [ ] 没有无理由新增依赖；每个新增依赖记录用途、替代、成本和未引入风险。
- [ ] `cd client && npm test` 通过。
- [ ] `cd client && npm run build` 通过。
- [ ] `python3 scripts/verify_core.py` 通过。
- [ ] 如环境允许，Tauri dev/build、sidecar 启停、窗口标题栏与 resize 通过。

### 12.7 视觉证据

- [ ] 对 1440 × 900、1200 × 760、960 × 640、实际最小尺寸各做当前构建截图。
- [ ] 至少覆盖：首页、范围选择、普通题、长材料、首次错误、微教程或 probe、总结、学习记录、离线/错误。
- [ ] 每张图检查截断、溢出、题目优先级、按钮可见性、焦点、中文行长和材料/问题关系。
- [ ] 清楚标出自动截图、仓库历史截图和真实 macOS 人工截图，不混用证据等级。

在 fresh visual/accessibility evidence 补齐前，不得把上述视觉条目标记为完成。仓库现状也保留这一 release gate（`docs/COMPLETION_AUDIT.md:59-71`）。

## 13. 实现更新（2026-07-15）

### 13.1 实际完成的设计/代码变更

已完成：

- 真实窗口：移除 900 × 526 假窗口运行结构，React 根内容直接占满 Tauri content area；Tauri 默认窗口改为 1180 × 760、最小 960 × 640、保留原生装饰并允许缩放。
- 应用框架：全局导航收敛为“首页 / 刷题 / 学习记录”；顶部栏只保留页面上下文和 `⌘K`；侧栏收起状态由 React 与 CSS 同一状态驱动。
- 首页：使用真实 `/v1/practice/overview`，只保留一个主 CTA、四模块快速入口和最近一组；未知 scope 与 0/null 指标不再静默回退为伪记录。
- 刷题入口：五个 Core-320 scope 直接进入固定八题；未完成会话阻止切换范围并可继续；read-model 失败不阻断核心刷题。
- 专注工作区：全屏内容层隐藏全局 chrome；题干 16–18px、选项整行 ≥52px、答案唯一必填；A–D、1–4、↑/↓、Enter、Escape 可用，IME、文本输入、repeat 和提交锁保持安全；已有作答时退出会先说明“提前结束”语义并确认。
- 教学反馈：正确时紧凑前进；错误时先给正确答案与一句关键纠偏；完整解析默认折叠；微教程与 probe 只消费 sidecar 返回内容，probe 可跳过。
- 总结：普通题正确数与 probe 题位分开；恢复会话的缺失明细明确标注；只展示一个主要错误模式、一个待确认判断、一个下一组验证方向和折叠错题。
- 学习记录：三个 ARIA tabs 分别读取 history/profile/wrong-question API；每组可按需读取 session report 并核对 trace/replay；单项失败独立呈现；空值、空集合、撤销/不足证据不填充 demo 数据。
- 设计系统与清理：新增系统字体、语义字号、4px 间距、圆角、颜色和焦点 tokens；删除 1,371 行旧 `smart-practice.css`，把 2,882 行旧 `styles.css` 收敛为 48 行基础 reset；`App.jsx` 从 974 行收敛为 186 行。
- 桌面与可访问性：所有核心交互热区至少 44px；Command、Settings、Practice 三类 modal 防止叠加，保留初始焦点、Tab loop、Escape 和返回焦点；支持 reduced motion。

暂未完成：

- 当前构建的多尺寸截图和同尺寸 before/after 对照。仓库内 `client/qa/*.png` 是 2026-07-11 的旧界面基线，只可作为 before，不能作为本轮 after。
- 真实 Tauri 窗口中的交通灯、resize、200% 缩放、VoiceOver、高对比度和多显示器行为；确定性配置与 managed-sidecar 验证已通过，但不能替代人工可用性检查。
- 资料分析真实长材料/图表与双栏状态。Core-320 当前安全题目投影只有 `prompt/options`，本轮只保证长 prompt 在单栏滚动画布中可读；没有猜测 material/image 字段或虚构图表数据。

与审计预案的取舍：

- 未新增 Radix、cmdk、Tailwind 或状态管理依赖。现有对话框和命令面板在本轮范围内已补齐焦点约束；若 VoiceOver 人工验收暴露问题，再以单个 primitive 为单位评估 Radix。
- Tauri 使用 `titleBarStyle: "Visible"`，而非预案中的 Transparent。原因是本轮优先保留完整原生窗口行为，且没有新建自定义拖拽区；这与“不为视觉效果关闭系统能力”的原则一致。
- 没有增加题型筛选。当前稳定客户端合同只有五个 scope；在服务提供可审计的题型筛选合同之前，不用客户端伪筛选改变出题语义。

### 13.2 文件变更清单

| 文件 | 变更 | 职责 |
| --- | --- | --- |
| `client/src/App.jsx` | 重写 | 最小应用编排、sidecar health/capability、一次性练习启动请求、可访问设置对话框。 |
| `client/src/AppShell.jsx` | 新增 | 真实全窗口框架、三项侧栏导航、上下文工具栏、命令面板与全局快捷键。 |
| `client/src/HomeScreen.jsx` | 新增 | 基于真实 overview 的今日建议、模块入口、最近一组和离线/错误状态。 |
| `client/src/PracticeScreen.jsx` | 重写 | 五 scope 选择、active session 恢复、专注工作区启动和退出刷新。 |
| `client/src/SmartPracticeWorkspace.jsx` | 修改 | 固定八题专注画布、长 prompt、键盘、最小反馈、probe、总结、退出确认和错误恢复。 |
| `client/src/LearningRecordsScreen.jsx` | 新增 | history/profile/wrong-question 三类真实记录与独立 loading/error/empty 状态。 |
| `client/src/practiceKeyboard.js` | 新增 | 无 DOM 副作用的答案选择与 Enter 行为解析。 |
| `client/src/practiceInsights.js` | 修改 | overview 最近会话的 scope/status/count 校验与 fail-closed 规范化。 |
| `client/src/smartPracticeState.js` | 修改 | 材料字段、恢复摘要完整性、普通题与 probe 计数分离。 |
| `client/src/styles/tokens.css` | 新增 | 语义字体、间距、圆角、色彩、焦点与浮层 token。 |
| `client/src/styles/redesign.css` | 新增 | shell、首页、范围、记录、设置、命令和专注工作区样式。 |
| `client/src/styles.css` | 重写 | 仅保留 reset、全窗口基础和 `sr-only`。 |
| `client/src/smart-practice.css` | 删除 | 旧小字号/旧假窗口耦合的练习样式已由新语义样式替代。 |
| `client/src/LessonWorkspace.jsx`、`client/src/lesson.css` | 删除 | 调用图确认不在当前 App/Practice 路径；移除旧强制教学工作区与 7–10px 死样式，保留底层 lesson policy/API/tests。 |
| `client/src/main.jsx` | 修改 | 加载 token 与重构样式层。 |
| `client/tests/practiceKeyboard.test.js` | 新增 | A–D/1–4、方向键、Enter、IME、编辑目标与 repeat 测试。 |
| `client/tests/practiceInsights.test.js` | 修改 | 未知 scope、0/null 最近会话与 read model fail-closed 测试。 |
| `client/tests/smartPracticeState.test.js` | 修改 | 恢复组总结完整性与普通题分母测试。 |
| `desktop/src-tauri/tauri.conf.json` | 修改 | 1180 × 760、最小 960 × 640、可缩放、原生装饰/标题栏。 |
| `desktop/scripts/check-config.mjs` | 修改 | 对窗口尺寸、缩放、装饰和标题栏做确定性断言。 |
| `docs/UI_REFERENCE_AUDIT.md` | 新增 | 14 个一手参考的 Lumi 采纳/拒绝记录。 |
| `docs/UI_REDESIGN_V1.md` | 新增 | 基线审计、决策、实施记录、验证与剩余风险。 |

### 13.3 实际执行的验证

| 命令/步骤 | 结果 | 日期 | 证据 |
| --- | --- | --- | --- |
| `cd client && npm test` | PASS，30/30 | 2026-07-15 | Node TAP 输出；覆盖 practice policy/state/read-model/keyboard/退出确认。 |
| `cd client && npm run build` | PASS，Vite 6.4.2，4583 modules | 2026-07-15 | `client/dist`；CSS 44.28 kB、JS 326.45 kB（未压缩）。 |
| `cd desktop && npm run check:config` | PASS | 2026-07-15 | 窗口、Core-320、sidecar 计划与 dist 入口断言。 |
| `cd desktop && npm run build:fast-app` | PASS | 2026-07-15 | sidecar health/五 scope/终止检查通过；生成 debug `Lumi.app`。 |
| `python3 scripts/verify_core.py` | PASS，13/13 gates | 2026-07-15 | 包含 18/18 release evidence、client build、managed app 与边界检查。 |
| `git diff --check` | PASS | 2026-07-15 | 无 whitespace error。 |
| 调用图与静态审查 | PASS（已修复发现项） | 2026-07-15 | 删除前用 `rg` 验证 legacy UI 不在当前 App 调用树；独立代理复核数据与键盘状态。 |

`verify_core.py` 的外部 100 题有界样本仍报告既有 mapping gaps（module 94、skill 100、misconception 100，3 条 `needs_review`），门禁状态为预期的 `pass_with_mapping_gaps`；本轮未修改外部题库。

### 13.4 当前构建视觉证据

- 历史 before：`client/qa/overview-1440x1024.png`、`tools-1440x1024.png`、`reports-1440x1024.png`。这些图展示旧 900 × 526 假窗口和高密度页面，不代表当前实现。
- 当前 after：未生成。按 Product Design 浏览器约束优先调用 in-app Browser，但其运行时在初始化时因 `Cannot redefine property: process` 失败；没有静默切换到未经用户授权的 Playwright CLI，也没有把旧图冒充新图。
- 待补尺寸：1440 × 900、1200 × 760、960 × 640（也是当前最小窗口）及关键状态九类。
- 待真实 macOS 人工验收：标题栏/交通灯、拖拽与 resize、VoiceOver、200% 缩放、高对比度、多显示器与真实长图表。

### 13.5 剩余风险与最多三个下一步

1. 获得 Playwright 许可后，在相同 seed/temp DB 下补齐四尺寸、九关键状态的 after 截图，并与历史 before 组合审查可见差异。
2. 在真实 Tauri 窗口完成 VoiceOver、200% 缩放、键盘全路径、交通灯/resize 和提前退出恢复的人工验收。
3. 若后端后续增加 versioned material/chart projection，建立至少一组长材料、图表与无图替代文本 fixture，再做双栏与单栏的视觉回归。
