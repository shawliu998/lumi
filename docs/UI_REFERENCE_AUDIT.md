# Lumi UI 参考研究与取舍

> 调研日期：2026-07-15
>
> 范围：仅提炼会影响本轮 Lumi macOS 客户端实现的原则；不把参考产品当作视觉模板。
>
> 证据标记：**来源事实**表示一手资料明确说明；**Lumi 推断**表示基于该事实与 Lumi 学习闭环得出的实现决策。

## 结论先行

Lumi 应采用“原生窗口骨架 + 安静内容画布 + 渐进披露教学”的组合，而不是把桌面客户端做成一个带假窗口边框的网页、一个数据后台或一个常驻聊天工具。

本轮应落实的共同原则：

1. 真实 Tauri 窗口可自由缩放；保留 macOS 原生窗口能力，以透明标题栏融合内容，不关闭全部系统装饰。
2. 侧栏只承担全局一级导航；工具栏只表达当前页面上下文与少量动作；专注刷题时侧栏可收起。
3. 题目、材料与选项是刷题页唯一高对比内容。提交答案是唯一必填动作，Agent 反馈按“短纠偏 → 可展开解析 → 必要时微教程”递进。
4. 首页只回答“现在最值得做什么”；学习记录采用文档/列表流；中性色、排版、对齐和留白优先于卡片、渐变与彩色状态。
5. 键盘效率是加速层，不是隐藏层：所有核心操作同时可见、可点击、可聚焦，标准快捷键与焦点规则优先。
6. 借鉴 Perseus 与 OATutor 的职责边界和数据契约，不引入它们的运行时或内容协议；复杂交互原语按需采用 Radix，拒绝为了 shadcn/ui 全面迁移 Tailwind。

## A. macOS 与应用框架

### 1. Apple Human Interface Guidelines

一手来源：[Designing for macOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos)、[Windows](https://developer.apple.com/design/human-interface-guidelines/windows)、[Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)、[Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)、[Keyboards](https://developer.apple.com/design/human-interface-guidelines/keyboards)、[Focus and selection](https://developer.apple.com/design/human-interface-guidelines/focus-and-selection)、[Menus](https://developer.apple.com/design/human-interface-guidelines/menus)

**来源事实**

- macOS 用户会移动、缩放、最小化窗口并同时使用多个应用；Apple 建议支持可调整窗口和全屏，并利用大屏减少嵌套与不必要的模态。
- 侧栏用于访问同级内容区域，适合较扁平的信息架构；应允许隐藏，在窗口变窄时可自动收起，层级一般不超过两层。
- 工具栏服务当前视图的标题、导航、搜索和常用操作，不是一级页面切换器；工具栏可能被隐藏或自定义，所以命令仍应存在于菜单栏。
- Mac 用户长期使用物理键盘；应尊重系统快捷键、支持完整键盘访问，并使用可预测的焦点环或整行高亮。

**Lumi 采纳**

- 应用根节点直接填满 Tauri 窗口；支持缩放与全屏。最小尺寸由题目、选项、反馈和退出操作不重叠的压力测试决定，而不是用极小字号硬塞内容。
- 全局侧栏只保留“首页 / 刷题 / 学习记录”。设置及低频动作进入菜单或命令面板；刷题工作区允许收起侧栏，菜单栏仍可执行返回、退出本组和设置等命令。
- 顶部栏只显示当前范围、题号/进度、退出及必要的上下文动作，不再重复全局导航。
- 选项使用原生单选语义或等价的可访问控件；Tab 进入题目操作组，方向键在选项内移动，`Enter`/`Return` 提交，提交后焦点移动到反馈标题或“下一题”，并保持可见焦点样式。
- 窗口失焦时降低非核心 chrome 的强调，不改变题目内容状态；恢复焦点时不擅自跳到别的控件。

**拒绝 / 不照搬**

- 不绘制网页式“假 Mac 窗口”，不固定演示稿比例，不禁止缩放。
- 不用顶部标签与侧栏同时切换同一批页面；不在侧栏底部放唯一关键操作。
- 不覆盖 `⌘Q`、`⌘W`、`⌘,` 等系统约定；不依赖仅 hover 才能发现的核心操作。
- 不把 2025–2026 HIG 的 Liquid Glass 外观当作视觉 KPI；Lumi 优先遵循结构、行为、焦点和可读性原则。

### 2. Tauri 2 Window Customization

一手来源：[Window Customization](https://v2.tauri.app/learn/window-customization/)、[Configuration](https://v2.tauri.app/reference/config/)、[Window State](https://v2.tauri.app/plugin/window-state/)

**来源事实**

- Tauri 支持自定义标题栏、透明标题栏和窗口尺寸约束；官方明确提醒，macOS 自定义标题栏会失去部分系统窗口能力，并建议用透明标题栏配合自定义窗口背景保留原生功能。
- `data-tauri-drag-region` 只作用于直接标记的元素；这项限制用于避免按钮、输入框等交互元素被误当成拖拽区。
- Tauri 2 的窗口配置提供 `resizable`、`minWidth`、`minHeight` 和 `titleBarStyle`；`Overlay` 需要自定义拖拽区且不同 macOS 版本的标题栏高度可能不同。
- 官方 Window State 插件可以保存并恢复窗口尺寸和位置，但它是额外依赖。

**Lumi 采纳**

- 默认保留 `decorations: true`、`resizable: true`，优先评估 `titleBarStyle: "Transparent"`；应用背景延伸至标题栏，保留交通灯、移动、对齐、缩放和全屏能力。
- 在 Tauri 配置中设置经过压力测试的 `minWidth` / `minHeight`，同时让 CSS 在最小、默认、宽屏与全屏四种宽度下自然重排。
- 只有真实空白标题栏区域可拖拽；任何按钮、搜索框、链接或选择控件都不能成为拖拽区。
- 若后续验证用户确实需要恢复窗口位置，再单独评估 Window State 插件；它不是视觉重构的前置条件。

**拒绝 / 不照搬**

- 不设置 `decorations: false` 并在 React 中复刻交通灯。
- 不为透明效果启用整个透明窗口或 macOS private API；不使用 `Overlay` 规避正常布局。
- 不让标题栏遮住正文，也不把标题栏高度硬编码成跨版本不变值。

### 3. Linear UI Redesign

一手来源：[How we redesigned the Linear UI (part II)](https://linear.app/now/how-we-redesigned-the-linear-ui)

**来源事实**

- Linear 通过调整侧栏、标签、标题和面板来降噪、对齐并重建层级；他们把应用 chrome 视为一个倒 L 形框架。
- 方案在实现前针对运行环境、外观和层级做压力测试，并逐个验证列表、看板、分栏、全屏等视图与状态。
- 视觉系统以变量生成 surface、text、icon、control 等语义别名，用中性外观和更明确的文字/图标对比提高可读性。
- 上线被拆成压力测试、行为定义、chrome 刷新、私测和全面发布，并通过 feature flag 内部对照。

**Lumi 采纳**

- 先确定侧栏 + 顶部上下文栏的统一对齐轴，再让所有页面内容落在同一栅格；图标、标签、行高、页面标题和正文起点必须一致。
- 用语义 token 管理背景、面、边框、文字、图标、焦点、成功、错误和强调色；中性色承担大部分层级，强调色只服务选择、焦点和主操作。
- 对首页、范围选择、刷题、反馈、微教程、组末总结、学习记录、空/加载/离线/错误状态分别做最小窗口与宽屏压力测试。
- 先定义导航、焦点和状态行为，再替换 chrome；若改动范围较大，保留可撤销的小步提交或开关以便对照。

**拒绝 / 不照搬**

- 不复制 Linear 的高密度标签、属性侧栏和多面板工作流；Lumi 的核心任务更单一。
- 不为了换主题引入完整 LCH 生成器或主题市场；先保证浅色模式、系统深色模式和高对比可用。
- 不把“像 Linear”当作验收标准；验收标准是学习内容更突出、状态更清楚、窗口变化不破版。

### 4. Raycast

一手来源：[Raycast Manual](https://manual.raycast.com/)、[Search Bar](https://manual.raycast.com/search-bar)、[Action Panel](https://manual.raycast.com/action-panel)、[Keyboard Shortcuts](https://manual.raycast.com/keyboard-shortcuts)

**来源事实**

- Raycast 的搜索入口实时过滤结果；上下键移动、`Enter` 执行主动作、`⌘K` 打开所选对象的上下文 Action Panel、`Esc` 返回或关闭。
- Action Panel 把主动作置顶，把其他动作按逻辑分组，并在右侧展示快捷键，让用户逐步学习而不是先背快捷键。
- 紧凑模式会在空闲时缩小，开始输入或打开动作面板时展开；交互反馈短促且状态稳定。

**Lumi 采纳**

- `⌘K` 作为二级能力入口：快速开始某模块、搜索学习记录、跳转设置、恢复最近一组；结果按“开始 / 跳转 / 查看”分组。
- 命令面板中 `Enter` 只有一个明确主动作，`Esc` 逐层返回，快捷键提示靠右且不与标题竞争。
- 在选项旁显示 `A–D` 键提示，在“提交”“下一题”“展开解析”附近按需显示快捷键；鼠标路径与键盘路径等价。
- 状态反馈就地、短暂且不改变布局高度；失败时保留用户当前选择并给出可恢复动作。

**拒绝 / 不照搬**

- 命令面板不是刷题入口的唯一方式，也不是通用工具市场。
- 不把 Lumi 主框架做成启动器列表；不让用户必须记住快捷键才能完成一次练习。
- 不把 Agent 对话、微教程和内部策略暴露成几十个平级命令。

### 5. Things 3

一手来源：[Things](https://culturedcode.com/things/)、[Things features](https://culturedcode.com/things/features/)

**来源事实**

- Things 把 Today 作为日常行动中心；列表用标题分组形成清晰结构，而不是给每项套独立容器。
- Slim Mode 收起侧栏以减少干扰，并仍保留快速切换能力；Quick Find 支持即时键盘导航。
- macOS 版本允许多窗口和分屏，但界面仍围绕当前列表与当前行动。

**Lumi 采纳**

- 首页对应“Today”：一个明确的“开始一组”主动作、一句推荐理由、四模块快捷选择和最近一组极简摘要。
- 学习记录用大标题、分组标题、列表行、浅分割线和自然留白构成；状态信息作为行内辅助文本，不制造卡片墙。
- 进入刷题后收起侧栏，仍可通过窗口标题区、退出按钮或命令面板回到全局位置。

**拒绝 / 不照搬**

- 不采用任务管理器的勾选圆、拖拽排序和项目隐喻。
- 不引入 Progress Pies、夸张完成动画或其他会把学习变成待办打卡的元素。
- 不为 V1 增加多窗口题目；先把单窗口恢复与缩放行为做可靠。

### 6. Craft

一手来源：[Craft](https://www.craft.do/)、[Documents, Pages, and Blocks](https://support.craft.do/en/introduction/documents)、[Search and Quick Open](https://support.craft.do/en/organize-and-find/search)

**来源事实**

- Craft 将段落视为 block；block 可以保持当前页内容，也可以成为进入嵌套页面的入口。顶层 document 在侧栏，嵌套 page 不重复占据侧栏。
- Quick Open 是键盘优先的跨文档导航，搜索结果包含文档、页面、最近内容和正文块。

**Lumi 采纳**

- 学习记录与组末总结采用文档阅读模型：稳定的内容列宽、大标题、段落、列表、引用式关键结论和可折叠细节。
- “一次练习”是顶层记录；错题、错误模式和证据是记录内部的内容块或子视图，不全部升级为全局导航项。
- 完整解析、证据详情与历史尝试用渐进披露展开，默认视图保持短而可扫读。

**拒绝 / 不照搬**

- 不建设富文本编辑器、数据库、画廊或任意 block 系统。
- 不把每个内容块视觉化为大卡片；Craft 的 Card 是可选样式，不是文档排版的默认单位。
- 不允许学习记录自由编辑到破坏审计链；结构化事件仍是权威数据，文档只是呈现层。

## B. 学习体验与 Agent

### 7. Brilliant

一手来源：[Brilliant About](https://brilliant.org/about/)

**来源事实**

- Brilliant 强调交互、适应性和视觉化；单个课程聚焦一个概念，从最简单版本开始以降低认知负荷，并基于答案即时给出定制反馈。
- 其 Tutor “asks instead of tells”，目标是建立能力而非依赖；Tutor 能看到当前屏幕与卡点，介入应与当前题目绑定。
- 独立练习会撤去视觉辅助与提示，用于验证无脚手架作答；混合练习与间隔复习服务迁移和保持。
- Brilliant 也明确表示避免堆叠太多游戏激励，让注意力留在学习内容。

**Lumi 采纳**

- 一屏只处理一道题；材料、题干、选项按阅读顺序连续排布，默认不并列展示 Agent 或学习仪表盘。
- 先让用户尝试，再根据错误给一句关键纠偏；只有重复错误或用户主动请求时，才增加一步探查或微教程。
- 干预后安排无提示验证题；验证状态与证据写入结构化学习记录，不用“看过解析”代替掌握。
- 对资料分析中的图表和长材料，优先交互式放大、清晰标注和邻近说明，不用长篇文字替代可视信息。

**拒绝 / 不照搬**

- 不采用 XP、排行榜、连续打卡、炫耀式关卡和大面积庆祝反馈。
- 不在 V1 建设可任意生成交互课件的系统；题型边界与可靠评分优先。
- 不在答对后强制展示解析，也不让 Tutor 每题都出现。

### 8. Khanmigo

一手来源：[Khanmigo](https://www.khanmigo.ai/)

**来源事实**

- Khanmigo 面向学习者的定位是促进批判性思考与解题，不直接给答案，而是引导学习者自己发现答案。
- 其差异化来自与 Khan Academy 当前学习内容相连，而不是一个脱离上下文的通用聊天工具。

**Lumi 采纳**

- Agent 的输入必须带当前题目、用户作答、技能与诊断证据；输出只影响当前学习动作，不创建独立“聊天世界”。
- **Lumi 推断：** 每次默认只提出一个最有辨别力的问题或给一句最短纠偏，等待学习者行动后再决定是否继续。
- 用户主动点“帮我想一步”时进入短探查；点“展开完整解析”时直接提供结构化解析，不强迫多轮对话。

**拒绝 / 不照搬**

- 不设常驻聊天栏、Agent 头像流、大段历史对话或自由输入作为主入口。
- 不把教师工具目录、写作助手和泛用问答迁入学习主导航。
- 不通过换一种说法直接泄露答案；若必须给出正确答案，明确它是作答后的反馈，而非作答前代答。

### 9. UWorld

一手来源：[UWorld](https://www.uworld.com/)、[USMLE Product Tour](https://medical.uworld.com/usmle/features/)、[Tutor Mode guidance](https://nursing.uworld.com/blog/7-tips-for-using-the-uworld-nclex-qbank/)

**来源事实**

- UWorld 将练习界面设计为接近正式考试；Tutor Mode 在每题作答后立即显示正确答案与解释，Timed Mode 用于更接近考试的延迟反馈。
- 解释会说明核心问题以及各选项为何正确或错误，并配合插图、图表；历史测试支持暂停恢复、结果回看和按错误/标记题复习。
- 其产品也提供大量性能统计和同伴比较。

**Lumi 采纳**

- 题号、范围、进度、退出保持稳定；长材料和选项有足够行宽、行高与点击区域，滚动位置在提交反馈时不突然跳动。
- 默认相当于轻量 Tutor Mode：首次错误只显示正误、正确答案、一句关键纠偏、完整解析入口和下一题；完整选项辨析默认折叠。
- 保留错题、标记、会话恢复与历史尝试；学习记录能从一次练习回到具体题目及当时反馈。
- 若未来提供“模拟”模式，再延迟整组反馈；不把模式选择放进每次开始前的配置向导。

**拒绝 / 不照搬**

- 不复制传统题库的高密度工具条、同伴答题百分比和多图表仪表盘。
- 不默认展开冗长的每选项解析；不让统计压过下一道题。
- 不把计时作为所有练习的默认压力，也不把专业感等同于灰暗、拥挤和小字号。

## C. 开源组件与工程参考

### 10. Khan Academy Perseus

一手来源：[Khan/perseus](https://github.com/Khan/perseus)、[data schema](https://github.com/Khan/perseus/blob/main/packages/perseus-core/src/data-schema.ts)、[hint parser](https://github.com/Khan/perseus/blob/main/packages/perseus-core/src/parse-perseus-json/perseus-parsers/hint.ts)、[widget registry](https://github.com/Khan/perseus/blob/main/packages/perseus-core/src/widgets/core-widget-registry.ts)、[accessibility instructions](https://github.com/Khan/perseus/blob/main/accessibility-instructions.md)

**来源事实**

- Perseus 将题目表示为数据，renderer 负责呈现与交互，score 模块负责评分；其 schema 文件刻意隔离，并要求变更保持旧数据可渲染。
- 题型通过 widget registry 扩展；hint 是带内容、组件与图片映射的独立结构。组件在 Storybook 中单独开发和验证。
- 项目明确要求 WCAG 2.2 AA，并优先使用原生语义元素而非用 ARIA 修补无语义 `div`。

**Lumi 采纳**

- `QuestionRenderer` 接受版本化题目数据，不读 Agent prompt；选择状态、评分结果和教学反馈分别归属不同层。
- 题型按最小 registry 扩展：本轮只覆盖现有公务员考试题型、富文本、图片/图表与单选，不为未知题型预建庞大抽象。
- Hint/解析作为结构化数据块，记录来源和版本；题目 schema 变更必须有向后兼容或显式迁移测试。
- 交互优先原生 `button`、`input`、`fieldset`、`legend` 等语义；题型组件需要独立状态与键盘测试。

**拒绝 / 不照搬**

- 不整体安装 Perseus，不兼容其完整 JSON 协议，也不迁移其编辑器、数学键盘和全部 widgets。
- 不把评分、教学策略和 UI 状态塞进一个通用 renderer。
- 不因为 Perseus 功能全面就扩大 Lumi MVP；只复用边界思想，不复用品牌视觉。

### 11. OATutor

一手来源：[CAHLR/OATutor](https://github.com/CAHLR/OATutor)

**来源事实**

- OATutor 是 React 实现的自适应辅导系统，支持无后端部署；Firebase 仅用于可选日志，本地存储使用 localForage。
- README 明确区分：`Problem` 组织多个 `ProblemCard` 并在作答后更新知识组件，`ProblemCard` 负责单步输入与提交，`HintSystem` 是可展开提示面板。
- 内容源、题目/步骤、hint pathway、技能映射与 BKT 参数分别存放；选题启发式可配置，并按薄弱技能选择题目。

**Lumi 采纳**

- 组件职责对应为：`PracticeSession` 管会话与推进，`Question/OptionGroup` 管呈现与输入，`FeedbackPanel` 管最短反馈，`Intervention` 管提示路径；知识追踪由领域服务更新。
- 题目到技能的映射、作答事件、诊断假设和教学干预分别版本化；UI 只消费决策，不在组件内计算 mastery。
- 提示路径可表示为“纠偏 → 探查 → 微教程 → 解答”，但默认只打开满足策略的第一层。
- 本地事件日志是默认权威来源；云日志、Firebase 和登录不是依赖。

**拒绝 / 不照搬**

- 不复制 OATutor 的 Material UI 视觉和多卡片题目布局。
- 不在 React 组件中直接执行 BKT 更新或最弱技能选题；这会破坏 Lumi 的可审计服务边界。
- 不引入 Firebase、LTI 或 OATutor 内容库；内容授权与运行时依赖均保持隔离。

### 12. Radix Primitives

一手来源：[Radix Primitives](https://www.radix-ui.com/primitives)

**来源事实**

- Radix 提供无样式、可访问的 React 原语；Dialog、Dropdown Menu、Popover 等内建焦点管理、键盘导航、碰撞定位、模态/非模态行为和辅助技术语义。
- Accordion、Radio Group、Tabs 支持对应 WAI-ARIA 模式和方向键操作；Scroll Area 保留浏览器原生滚动行为。

**Lumi 采纳**

- 仅在交互复杂度真实存在时按组件引入：Dialog / AlertDialog、DropdownMenu、Popover、Tooltip、Accordion、RadioGroup、Tabs。
- 组件只提供行为层，全部视觉由 Lumi token 和原生 CSS 控制；封装成 Lumi 自己的薄组件并补齐中文标签、焦点回归和测试。
- ScrollArea 默认不引入；题目长材料优先原生滚动，只有跨平台滚动条样式成为可验证问题时再评估。

**拒绝 / 不照搬**

- 不引入 Radix Themes，不用默认外观替代 Lumi 设计系统。
- 不把普通信息块都改成 Popover/Dialog；能在当前上下文展开就不制造模态。
- 不假定库自动解决所有无障碍问题；业务标签、焦点目标、错误提示和阅读顺序仍需测试。

### 13. shadcn/ui

一手来源：[shadcn/ui Introduction](https://ui.shadcn.com/docs)、[Vite installation](https://ui.shadcn.com/docs/installation/vite)、[Command](https://ui.shadcn.com/docs/components/radix/command)

**来源事实**

- shadcn/ui 将自身定义为开放代码的组件分发方式，而非封闭 npm 组件库；价值在可读、可修改和组合一致的组件源码。
- 其 Vite 安装路径会配置 Tailwind CSS、导入别名与组件生成流程；Command 组件底层使用 cmdk。

**Lumi 采纳**

- 只参考组件解剖、状态清单、命名和组合方式：Trigger / Content / Header / Description / Action、loading / empty / disabled / error 等状态必须完整。
- 如果借用单个实现，先去除 Tailwind 与无关依赖，改用现有原生 CSS 和 Lumi token，并把源码纳入本仓库维护。

**拒绝 / 不照搬**

- 不运行 shadcn 初始化，不全面迁移 Tailwind，不复制其默认 New York / dashboard 视觉。
- 不因为示例丰富就引入 Card、Sheet、Toast 等并不存在的产品需求。
- 不把复制代码当作零维护成本；开放代码意味着 Lumi 对升级、测试和无障碍负责。

### 14. cmdk

一手来源：[dip/cmdk](https://github.com/dip/cmdk)

**来源事实**

- cmdk 是可组合的 React command menu，也可作为可访问 combobox；它内建过滤/排序、分组、空状态、键盘循环和 Dialog 组合，并使用 Radix Dialog。
- 组件支持由应用提供自定义过滤、关键词别名和嵌套页面，`Esc`/空搜索下的 Backspace 可用于返回上级。

**Lumi 采纳**

- 若本轮交付 `⌘K`，cmdk 可作为唯一命令面板行为依赖；命令注册表、权限、搜索词、路由与执行逻辑仍由 Lumi 数据层管理。
- 命令项必须有稳定 id、中文标题、可选关键词、所属分组、是否可用及唯一执行函数；禁用项说明原因。
- 初始列表只呈现高频安全动作，搜索时再暴露更多结果；破坏性动作不放在默认首项。

**拒绝 / 不照搬**

- 不把题目选项、教学反馈或完整学习记录塞进命令面板。
- 不用 cmdk 状态代替路由或会话状态；不实现无限嵌套命令层级。
- 如果 V1 没有真实的跨页面快速跳转需求，则延期而不是为了展示 `⌘K` 增加依赖。

## 依赖策略结论

当前 `client/package.json` 只有 React、Vite 与 Phosphor Icons，且界面采用原生 CSS。依赖策略如下：

| 对象 | 决策 | 原因 |
| --- | --- | --- |
| Tauri 透明标题栏 | **采用配置能力** | 保留系统窗口能力，不增加前端组件依赖。 |
| Tauri Window State | **延期 / 证据驱动** | 恢复窗口几何有价值，但不是本轮视觉重构前置条件。 |
| Radix Primitives | **按组件条件采用** | 只为复杂焦点、键盘与浮层行为付依赖成本；禁止全套或 Themes。 |
| cmdk | **`⌘K` 确认交付时采用** | 能减少 command menu 的无障碍与键盘维护成本；业务命令模型仍自有。 |
| shadcn/ui | **不初始化、不迁移 Tailwind** | 当前原生 CSS 已是明确约束，全面迁移的 churn 大于收益；仅借鉴结构。 |
| Perseus | **只作架构参考** | 完整协议和题型范围远超公务员考试 MVP。 |
| OATutor | **只作教学状态参考** | 不引入 Material UI、Firebase、LTI 或其内容；Lumi 已有自己的本地事件与 KT 边界。 |

引入任何新依赖前需回答三个问题：它是否消除了难以自行可靠实现的无障碍/焦点行为；是否能按单组件引入并由确定性测试覆盖；是否保持本地优先且不改变现有数据协议。任一答案为否，就继续使用 React + 语义 HTML + 原生 CSS。

## 可直接进入验收清单的条目

- [ ] 真实窗口在最小、默认、宽屏、全屏四档无假窗口边距、遮挡或横向滚动。
- [ ] 保留交通灯、拖拽、缩放、全屏和菜单命令；标题栏交互元素不误触拖拽。
- [ ] 首页仅一个主 CTA；侧栏只含三个一级入口；刷题时侧栏可收起。
- [ ] 题目、选项、提交、短反馈、解析、下一题形成唯一清晰阅读顺序。
- [ ] 正确后可立即下一题；首次错误不自动展开长解析或微教程。
- [ ] 所有核心流程可只用键盘完成；焦点始终可见，模态关闭后回到触发点。
- [ ] 学习记录是文档/列表流，不是卡片墙；结构化学习事件仍为权威来源。
- [ ] 新依赖逐个说明必要性，没有 Tailwind/shadcn 全量迁移、Perseus/OATutor 运行时或云日志依赖。
