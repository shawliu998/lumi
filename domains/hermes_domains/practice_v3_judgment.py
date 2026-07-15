from __future__ import annotations

from itertools import product
from typing import Any, Callable, Mapping, Sequence

from .practice_v3_common import (
    AuthoredChoice,
    PracticeBankValidationError,
    UnitSpec,
    build_question,
    schedule_pairs,
    validate_generated_module,
)


JUDGMENT_UNITS: tuple[UnitSpec, ...] = (
    UnitSpec(
        module_slug="judgment",
        unit_slug="graphic-properties",
        unit_label="图形属性：对称与笔画",
        signature_slug="structural-property-missed",
        signature_label="忽略目标结构属性",
        observable_rule="所选项符合某个表面特征，却不满足题目要求的对称类型、对称轴数量或奇点约束。",
        cause_slugs=("invariant-not-translated",),
        cause_labels=("可能没有先把题目要求翻译成可检验的结构属性",),
        principle="先明确本题检验的结构属性，再逐项验证；元素看起来相似不能代替结构判断。",
        worked_contrast="一笔画看奇度顶点，不看图中一共有多少个交点。",
        return_action="把目标写成“轴、中心、奇点”中的一个明确检查项。",
    ),
    UnitSpec(
        module_slug="judgment",
        unit_slug="graphic-relations",
        unit_label="功能标记与样式运算",
        signature_slug="relative-rule-ignored",
        signature_label="忽略标记或运算的相对规则",
        observable_rule="所选项只沿用绝对位置或局部颜色，没有应用题干给出的相对位置或逐格运算规则。",
        cause_slugs=("relation-not-normalized",),
        cause_labels=("可能没有把图形变化改写成相对关系或逐格规则",),
        principle="功能点看它标记了什么关系；黑白运算按同一格逐一计算。",
        worked_contrast="黑点始终靠最长边时，三角形旋转后仍应找最长边，而不是固定找左边。",
        return_action="先用一句规则描述关系，再处理旋转或每个格子。",
    ),
    UnitSpec(
        module_slug="judgment",
        unit_slug="spatial-cube",
        unit_label="正方体相对面",
        signature_slug="opposite-co-visible",
        signature_label="让相对面同时出现在一个顶点",
        observable_rule="所选三面中包含题干已确定的一对相对面，因此不可能同时相邻于同一顶点。",
        cause_slugs=("opposite-pair-not-eliminated",),
        cause_labels=("可能没有先用相对面排除不可能选项",),
        principle="正方体同一顶点的三个面中，每组相对面最多出现一个。",
        worked_contrast="若 A 与 D 相对，任何同时含 A、D 的三面组合都不可能共顶点。",
        return_action="先圈出三组相对面，再检查选项是否把一组同时放入。",
    ),
    UnitSpec(
        module_slug="judgment",
        unit_slug="definition-constraints",
        unit_label="定义判断：条件核对",
        signature_slug="required-condition-omitted",
        signature_label="遗漏定义中的必要条件",
        observable_rule="所选情形满足定义的大部分条件，但明确缺少其中一个必须同时成立的条件。",
        cause_slugs=("constraint-not-conjoined",),
        cause_labels=("可能把多个必要条件当成满足其一即可",),
        principle="把定义拆成条件清单，属于定义的选项必须同时满足全部必要条件。",
        worked_contrast="完成说明但没有确认接收，仍不满足包含确认步骤的交接定义。",
        return_action="逐项打勾，不用整体印象替代条件核对。",
    ),
    UnitSpec(
        module_slug="judgment",
        unit_slug="analogy-relations",
        unit_label="类比推理：关系与方向",
        signature_slug="direction-reversed",
        signature_label="关系相同但方向相反",
        observable_rule="所选词组包含相同类型的两个概念，但前后位置与题干的关系方向相反。",
        cause_slugs=("direction-not-checked",),
        cause_labels=("可能识别了关系类型但没有核对前后方向",),
        principle="类比不仅要同关系，还要同方向；先把题干改写成一句“A 是 B 的什么”。",
        worked_contrast="木料是书架的材料；“面包：面粉”把产品和材料的位置倒置了。",
        return_action="对题干和选项使用同一个造句模板。",
    ),
    UnitSpec(
        module_slug="judgment",
        unit_slug="argument-strengthen",
        unit_label="加强论证",
        signature_slug="topic-only",
        signature_label="只与话题有关但没有加强论证",
        observable_rule="所选项提到题干对象，却没有补足论据与结论的联系，也没有增加支持结论的证据。",
        cause_slugs=("relevance-treated-as-support",),
        cause_labels=("可能把“谈到同一对象”当成了“支持结论”",),
        principle="加强项必须让结论更可信；只出现相同名词不等于提供支持。",
        worked_contrast="成员喜欢卡片颜色与编号卡是否缩短检索时间无关。",
        return_action="选项代入后追问：结论为真的可能性是否真的上升？",
    ),
    UnitSpec(
        module_slug="judgment",
        unit_slug="argument-weaken",
        unit_label="削弱论证",
        signature_slug="side-effect-only",
        signature_label="只说明副作用而未削弱结论",
        observable_rule="所选项描述做法的成本或副作用，但没有否定题干所主张的效果或因果联系。",
        cause_slugs=("disadvantage-treated-as-refutation",),
        cause_labels=("可能把“有缺点”当成了“没有题干效果”",),
        principle="削弱要打击结论或论证链；存在成本不等于题干效果不存在。",
        worked_contrast="清单会多用一张纸，并不能说明清单没有减少遗漏。",
        return_action="先写出要否定的结论，再检查选项是否正面触及它。",
    ),
    UnitSpec(
        module_slug="judgment",
        unit_slug="formal-proposition",
        unit_label="条件命题与有效推理",
        signature_slug="invalid-converse",
        signature_label="肯后或否前后作确定推断",
        observable_rule="面对 P→Q，所选项由 Q 推出 P，或由非 P 推出非 Q。",
        cause_slugs=("implication-direction-confused",),
        cause_labels=("可能没有使用原命题或逆否命题的有效方向",),
        principle="P→Q 只能肯前推肯后、否后推否前；肯后和否前都不能确定。",
        worked_contrast="已获得编号不能反推一定完成登记，编号也可能来自其他流程。",
        return_action="先写成箭头，再只沿箭头正向或逆否方向推理。",
    ),
)


_SYMMETRY_CASES: tuple[dict[str, Any], ...] = (
    {
        "prompt": "下列图形中，既是轴对称图形又是中心对称图形的是：",
        "requirements": {"axis": True, "center": True, "axes": 4},
        "features": {
            "正方形": {"axis": True, "center": True, "axes": 4},
            "等边三角形": {"axis": True, "center": False, "axes": 3},
            "一般平行四边形": {"axis": False, "center": True, "axes": 0},
            "不等边三角形": {"axis": False, "center": False, "axes": 0},
        },
        "targeted": "等边三角形",
    },
    {
        "prompt": "下列图形中，是中心对称图形但不是轴对称图形的是：",
        "requirements": {"axis": False, "center": True},
        "features": {
            "一般平行四边形": {"axis": False, "center": True},
            "长方形": {"axis": True, "center": True},
            "一般等腰梯形": {"axis": True, "center": False},
            "不等边三角形": {"axis": False, "center": False},
        },
        "targeted": "长方形",
    },
    {
        "prompt": "下列图形中，恰有一条对称轴且不是中心对称图形的是：",
        "requirements": {"axis": True, "center": False, "axes": 1},
        "features": {
            "非等边的等腰三角形": {"axis": True, "center": False, "axes": 1},
            "等边三角形": {"axis": True, "center": False, "axes": 3},
            "圆": {"axis": True, "center": True, "axes": -1},
            "一般平行四边形": {"axis": False, "center": True, "axes": 0},
        },
        "targeted": "等边三角形",
    },
    {
        "prompt": "下列图形中，恰有两条对称轴并且是中心对称图形的是：",
        "requirements": {"axis": True, "center": True, "axes": 2},
        "features": {
            "非正方形的长方形": {"axis": True, "center": True, "axes": 2},
            "正方形": {"axis": True, "center": True, "axes": 4},
            "一般平行四边形": {"axis": False, "center": True, "axes": 0},
            "不等边三角形": {"axis": False, "center": False, "axes": 0},
        },
        "targeted": "正方形",
    },
    {
        "prompt": "下列图形中，恰有一条对称轴且没有中心对称性的是：",
        "requirements": {"axis": True, "center": False, "axes": 1},
        "features": {
            "一般等腰梯形": {"axis": True, "center": False, "axes": 1},
            "非正方形的长方形": {"axis": True, "center": True, "axes": 2},
            "一般平行四边形": {"axis": False, "center": True, "axes": 0},
            "不等边三角形": {"axis": False, "center": False, "axes": 0},
        },
        "targeted": "非正方形的长方形",
    },
)

_EULER_DEGREES = (
    (1, 1, 2, 2),
    (1, 1, 1, 1, 4),
    (1, 1, 1, 1, 1, 1, 6),
    (1, 1, 1, 1, 3, 3),
    (1, 1, 1, 1, 1, 1, 1, 1, 8),
)

_MARKER_ROWS = (
    ("前三个三角形中的黑点都靠近各自最长边。第四个三角形旋转了方向，黑点仍应位于：", "最长边旁", "图形左边", "最短边旁", "三角形外任意位置"),
    ("前三幅图的黑点都标记锐角。下一幅图整体翻转后，黑点仍应标记：", "锐角", "页面右上角", "钝角", "图形中心"),
    ("一组重叠图形中，白点始终位于两图形的相交区域。更换图形位置后，白点应放在：", "新的相交区域", "原页面坐标", "任一非相交区域", "图形外部"),
    ("每幅图有黑白两点，两点连线始终与图形最长边平行。图形旋转后，两点连线应：", "继续与最长边平行", "保持页面水平", "改为与最长边垂直", "缩成一个点"),
    ("前三幅图的小圆都标在线段交点上。下一幅图增加了一条线，小圆应标在：", "新的线段交点", "页面左下方", "任一线段中点", "图形外空白处"),
)

_DEFINITION_ROWS = (
    ("双向交接", "当前负责人", "任务尚未完成时", "说明现有进度和待办", "确认下一负责人已经接收"),
    ("限域共享", "资料持有人", "协作确有需要时", "只提供完成任务所需的信息", "说明信息的使用边界"),
    ("延迟复核", "原作答者", "与首次作答间隔一段时间后", "在没有原提示的情况下再次作答", "比较两次结果"),
    ("条件记录", "观察人员", "现象发生时", "同时记录现象和出现条件", "保留记录时间"),
    ("版本标注", "文件修改者", "保存新内容时", "写明本次主要变化", "保留可区分的版本编号"),
    ("分区协商", "共同使用空间的人", "需求发生冲突时", "讨论不同活动所需区域", "形成双方可执行的分区约定"),
    ("轮值确认", "本轮值班人", "轮值结束前", "列出已经完成和未完成的事项", "确认下一位值班人知晓"),
    ("路径提示", "场所管理者", "路线容易混淆时", "在关键转折处给出方向信息", "确保提示连续指向目的地"),
    ("证据复盘", "学习者", "发现作答错误后", "对照原选择与题目证据", "记录可以被后题验证的错误模式"),
    ("需求抽样", "活动组织者", "正式调整方案前", "从不同使用群体收集代表性意见", "记录样本来源"),
)

_DEFINITION_SCENARIOS = (
    (
        "本轮巡检负责人小林在尚有两处未查时，向接班的小周说明已查范围和剩余事项，并收到小周的接收确认。",
        "本轮巡检负责人小林在尚有两处未查时，把已查范围和剩余事项发给小周后离开，未确认小周是否收到。",
        "路过的居民在巡检尚未结束时，把自己看到的进度告诉小周，并请小周回复收到。",
        "本轮巡检负责人在任务结束一周后，才向小周补发进度和待办，并请小周确认。",
    ),
    (
        "项目资料保管员在联合核验确有需要时，只发送本次核验涉及的字段，并注明资料仅限当日核验使用。",
        "项目资料保管员在联合核验确有需要时，只发送本次核验涉及的字段，但没有说明允许如何使用。",
        "临时访客在没有协作任务时，转发少量项目字段并注明不得外传。",
        "资料保管员在协作结束很久后，发送所需字段并补充使用范围。",
    ),
    (
        "原答题者隔一周关闭旧题解析，独立完成一道同技能新题，并把新结果与首次作答进行比较。",
        "原答题者隔一周关闭旧题解析，独立完成一道同技能新题，但没有比较前后两次结果。",
        "同组同学隔一周独立完成新题，并把自己的结果与原答题者首次作答进行比较。",
        "原答题者刚交卷便看着原提示重做同一道题，随后比较两次结果。",
    ),
    (
        "观察员在设备异响出现时，同时记下响声、环境温度和发生时刻，并保存这条记录。",
        "观察员在设备异响出现时，同时记下响声和环境温度，但没有保留发生时刻。",
        "无关访客在设备异响出现时，记下响声、环境温度和发生时刻。",
        "观察员在异响消失数日后凭记忆补写现象、条件和时间。",
    ),
    (
        "文档编辑者保存新内容时，在变更说明中概括本次调整，并将文件编号更新为可区分的新版本。",
        "文档编辑者保存新内容时，写了本次调整内容，却继续沿用无法区分的新旧编号。",
        "未参与修改的人在文件保存时，补写变更说明并编了一个新版本号。",
        "编辑者在内容发布很久后才补写变化并追加版本编号。",
    ),
    (
        "广场使用者因舞蹈和阅读需求冲突而共同讨论所需范围，最终约定了双方都能执行的分区时段。",
        "广场使用者因需求冲突讨论了各自所需范围，但没有形成双方可执行的分区约定。",
        "从不使用广场的人在需求冲突时替双方划定区域，并要求双方接受。",
        "双方活动全部结束后才讨论原有冲突，并形成下一次尚无法执行的笼统想法。",
    ),
    (
        "本轮值班员交班前列出已完成和待处理事项，并让接班员逐项确认已经知晓。",
        "本轮值班员交班前列出已完成和待处理事项，但没有确认接班员是否知晓。",
        "未参加本轮值班的人在交班前整理事项，并让接班员确认知晓。",
        "本轮值班员在交班数日后才补列事项，并请接班员确认。",
    ),
    (
        "场馆管理员发现岔路容易走错后，在每个关键转折处设置方向牌，使标识连续通向服务台。",
        "场馆管理员发现岔路容易走错后，只在入口放置一块方向牌，后续转折处没有连续提示。",
        "普通访客在岔路混淆时自行张贴连续指向服务台的方向纸条。",
        "管理员在场馆关闭很久后才补画关键转折和连续方向信息。",
    ),
    (
        "学习者发现错题后，对照自己原选项与题干证据，写下“忽略时间范围”的模式并安排新题验证。",
        "学习者发现错题后，对照原选项与题干证据，却没有记录可由后题检验的错误模式。",
        "同桌发现这道错题后，替学习者比较选项证据并记录可验证模式。",
        "学习者在考试结束很久后才凭印象回想选项，并记录一个无法由后题验证的感受。",
    ),
    (
        "活动组织者在修改方案前分别访问新老用户，按预定名额收集意见，并在记录中标明每位受访者所属群体。",
        "活动组织者在修改方案前从不同用户群收集了意见，却没有记录各条意见来自哪类样本。",
        "无关商户在方案调整前向不同群体征求意见，并记录受访群体。",
        "组织者在新方案实施数月后才向不同群体征求意见并记录来源。",
    ),
)

if len(_DEFINITION_SCENARIOS) != len(_DEFINITION_ROWS):
    raise AssertionError("definition scenarios must align with definition fixtures")

_ANALOGY_ROWS = (
    ("木料：书架", "棉线：布料", "面包：面粉", "轮胎：车辆", "剪刀：裁剪", "material-product"),
    ("剪刀：裁剪", "尺子：测量", "书写：钢笔", "木料：桌子", "教师：学校", "tool-function"),
    ("麻雀：鸟类", "玫瑰：花卉", "水果：苹果", "车轮：车辆", "火焰：温热", "member-category"),
    ("轮胎：车辆", "键盘：电脑", "房屋：门窗", "棉线：布料", "医生：医院", "part-whole"),
    ("教师：学校", "医生：医院", "工厂：工人", "种子：发芽", "信封：信纸", "worker-place"),
    ("按下开关：指示灯亮", "拉动门闩：门锁开启", "房间变亮：打开窗帘", "尺子：测量", "麻雀：鸟类", "cause-result"),
    ("火焰：温热", "冰块：低温", "明亮：灯光", "轮胎：车辆", "木料：书架", "object-property"),
    ("种子：发芽", "鸟卵：孵化", "收获：播种", "医生：医院", "剪刀：裁剪", "source-development"),
    ("信封：信纸", "笔袋：铅笔", "图书：书架", "麻雀：鸟类", "按下开关：指示灯亮", "container-content"),
    ("蜜蜂：蜂蜜", "蚕：蚕丝", "牛奶：奶牛", "键盘：电脑", "冰块：低温", "producer-product"),
)

_STRENGTHEN_ROWS = (
    ("一次模拟检索中，使用编号卡的小组完成得更快", "编号卡能减少检索时间", "两组任务量和成员经验相同，唯一差异是是否使用编号卡", "多数成员喜欢蓝色编号卡", "编号卡上印有连续数字", "使用编号卡的小组事先练习过同一批材料"),
    ("在模拟场地中，设置连续路标后迷路次数下降", "连续路标有助于减少迷路", "两轮测试路线和参与者构成相同，只在第二轮增加连续路标", "路标采用了绿色边框", "场地一共有六个路口", "第二轮参与者提前看过完整路线"),
    ("使用检查清单的值班组遗漏事项更少", "检查清单能够减少值班遗漏", "两组承担相同事项，且清单组的减少集中在清单列出的步骤", "清单打印在白纸上", "值班事项共有八项", "清单组成员的平均经验明显更丰富"),
    ("采用间隔提醒的学习组次日记住的步骤更多", "间隔提醒有助于保持步骤记忆", "两组初始水平相当，学习内容相同，仅提醒安排不同", "学习者喜欢日历样式", "提醒一共出现三次", "间隔组比另一组多学习了一倍时间"),
    ("工具放入透明分格柜后，归还错误减少", "透明分格有助于正确归还工具", "遮住分格标签后，原本的改善随之消失", "透明柜看起来更整洁", "柜子共有十二个格子", "更换柜子时同时安排了专人检查"),
    ("统一文件名称后，团队查找文件更快", "统一命名能提高文件检索效率", "同一批文件在统一命名前后分别测试，检索入口和人员均未改变", "成员觉得新名称更简短", "文件名称包含日期", "测试后删除了一半文件"),
    ("讲解规则时加入一个对比例，学习者在新题上正确率提高", "对比例有助于理解规则边界", "提高主要出现在需要区分规则边界的新题，而非原示例复述题", "示例使用了圆形图标", "讲解总共持续十分钟", "加入示例后练习题也变得更简单"),
    ("设置安静阅读区后，完成整篇阅读的人数增加", "安静分区有助于完成阅读", "分区前后材料和阅读时间相同，噪声水平是主要变化", "安静区的座椅是灰色", "阅读区共有二十个座位", "分区后参与者可以选择更短的文章"),
    ("在出口设置归还提示后，工具漏还次数下降", "出口提示能够减少工具漏还", "撤去提示时漏还回升，恢复提示后再次下降", "提示牌使用大号字体", "出口旁有一张桌子", "设置提示的同时取消了工具外借"),
    ("使用对照表后，学习者更快发现两方案差异", "对照表有助于识别差异", "优势只出现在需要跨栏比较的任务，单栏读取速度没有变化", "对照表采用浅色线框", "两个方案各有五项", "对照表组事先知道正确答案"),
)

_WEAKEN_ROWS = (
    ("使用编号卡的小组检索更快", "编号卡能减少检索时间", "该组成员此前已经熟悉全部材料，另一组是首次接触", "制作编号卡会消耗纸张", "另一轮同条件测试仍出现相同差异", "编号卡使用了蓝色字体"),
    ("增加路标后模拟场地中的迷路次数下降", "路标减少了迷路", "第二轮参与者在开始前已看过完整路线，第一轮没有", "路标需要定期擦拭", "撤去路标后迷路次数再次上升", "路标安装在路口附近"),
    ("使用清单的值班组遗漏更少", "清单减少了遗漏", "清单组只负责四项任务，另一组负责十二项", "打印清单需要一张纸", "遗漏减少的项目都列在清单中", "清单采用了表格排版"),
    ("间隔提醒组次日记住的步骤更多", "间隔提醒改善了记忆", "间隔组实际复习总时长是另一组的三倍", "设置提醒会占用通知栏", "控制学习时长后仍得到相同结果", "提醒图标是圆形"),
    ("改用透明分格柜后归还错误减少", "透明分格改善了工具归还", "更换柜子时同时安排了专人逐件核对", "透明柜更容易显出灰尘", "取消专人后仍保持同样改善", "柜门可以上锁"),
    ("统一文件名称后检索更快", "统一命名提高了检索效率", "命名调整时同时删除了大量无用文件", "修改文件名需要一次性投入时间", "在文件数量不变的测试中仍有改善", "新名称包含日期"),
    ("加入对比例后新题正确率提高", "对比例帮助理解规则边界", "新题直接复用了对比例中的数字和顺序", "制作对比例需要更多版面", "更换数字后优势仍然存在", "对比例放在页面中部"),
    ("划出安静区后完成阅读的人数增加", "安静分区帮助完成阅读", "分区后统一换成了篇幅更短的材料", "安静区需要额外标牌", "使用同样材料时仍观察到改善", "区域内座椅为灰色"),
    ("出口增加提示后漏还工具减少", "出口提示减少了漏还", "同时开始由管理员在出口逐人核对工具", "提示牌占用了一小块墙面", "无人核对时提示仍然有效", "提示文字共有两行"),
    ("使用对照表后发现差异更快", "对照表提高了比较效率", "对照表组看到的方案条目比另一组少一半", "绘制表格需要少量时间", "条目数量一致时仍观察到速度优势", "表格使用浅色线框"),
)

_FORMAL_ROWS = (
    ("完成登记", "获得借用编号", "扫描归还码", "系统生成归还记录"),
    ("阅读操作指引", "完成模拟练习", "提交回执", "系统保存提交时间"),
    ("标记文件版本", "文件可以追溯", "输入有效关键词", "系统显示目标文件"),
    ("确认轮值安排", "收到值班提醒", "扫描签到码", "系统记录到场信息"),
    ("完成工具检查", "获得维护标签", "提交故障单", "维修组收到通知"),
    ("阅读疏散图", "熟悉全部路线", "按下测试按钮", "指示灯点亮"),
    ("填写借阅申请", "获得借阅资格", "归还图书", "系统解除借阅占用"),
    ("参加讲解活动", "掌握分类规则", "扫描物品标签", "终端显示分类信息"),
    ("保存观察笔记", "形成完整结论", "上传记录文件", "平台生成文件编号"),
    ("查看会议材料", "理解全部议题", "提交参会确认", "系统记录参会状态"),
)


def _tagged_choice(
    prompt: str,
    correct: str,
    targeted: str,
    other_one: str,
    other_two: str,
    explanation: str,
    required_tag: str,
    targeted_tag: str,
) -> AuthoredChoice:
    return AuthoredChoice(
        prompt=prompt,
        correct=correct,
        targeted_wrong=targeted,
        other_wrong=(other_one, other_two),
        explanation=explanation,
        verification={
            "adapter": "judgment_constraint_tags_v1",
            "required_tag": required_tag,
            "targeted_tag": targeted_tag,
            "candidate_tags": {
                correct: [required_tag],
                targeted: [targeted_tag],
                other_one: ["other-error-1"],
                other_two: ["other-error-2"],
            },
        },
    )


def _numeric_other_values(correct: int, targeted: int) -> tuple[int, int]:
    candidates = [value for value in range(1, 10) if value not in {correct, targeted}]
    return candidates[0], candidates[1]


def _author_graphic_properties(variant: int) -> AuthoredChoice:
    if variant < 5:
        case = _SYMMETRY_CASES[variant]
        features = case["features"]
        requirements = case["requirements"]
        satisfying = [
            text
            for text, values in features.items()
            if all(values.get(key) == expected for key, expected in requirements.items())
        ]
        if len(satisfying) != 1:
            raise PracticeBankValidationError("symmetry case is ambiguous")
        correct = satisfying[0]
        targeted = case["targeted"]
        others = [text for text in features if text not in {correct, targeted}]
        return AuthoredChoice(
            prompt=case["prompt"],
            correct=correct,
            targeted_wrong=targeted,
            other_wrong=(others[0], others[1]),
            explanation="逐项核对轴对称、中心对称及对称轴数量，只有一个选项满足全部条件。",
            verification={
                "adapter": "judgment_graph_features_v1",
                "requirements": requirements,
                "candidate_features": features,
                "targeted_text": targeted,
            },
        )

    degrees = list(_EULER_DEGREES[variant - 5])
    odd_count = sum(value % 2 for value in degrees)
    correct_value = max(1, odd_count // 2)
    targeted_value = odd_count
    other_one, other_two = _numeric_other_values(correct_value, targeted_value)
    suffix = lambda value: f"{value}笔"
    return AuthoredChoice(
        prompt=f"一个连通图各顶点的度数依次为{degrees}。不重复线条，最少需要几笔画完？",
        correct=suffix(correct_value),
        targeted_wrong=suffix(targeted_value),
        other_wrong=(suffix(other_one), suffix(other_two)),
        explanation=f"奇度顶点共有{odd_count}个，连通图最少笔画数为奇点数除以2，即{correct_value}笔。",
        verification={
            "adapter": "judgment_euler_trail_v1",
            "degrees": degrees,
            "connected": True,
            "candidate_values": {
                suffix(correct_value): correct_value,
                suffix(targeted_value): targeted_value,
                suffix(other_one): other_one,
                suffix(other_two): other_two,
            },
            "targeted_value": targeted_value,
        },
    )


def _grid(value: int) -> str:
    bits = f"{value:04b}"
    cells = ["■" if bit == "1" else "□" for bit in bits]
    return f"{cells[0]}{cells[1]}/{cells[2]}{cells[3]}"


def _binary_pairs() -> tuple[tuple[int, int], ...]:
    result: list[tuple[int, int]] = []
    for left in range(1, 15):
        for right in range(left + 1, 15):
            values = {left ^ right, left & right, left | right, (~(left ^ right)) & 0b1111}
            if len(values) == 4:
                result.append((left, right))
                if len(result) == 5:
                    return tuple(result)
    raise AssertionError("not enough distinct binary-grid cases")


_GRID_PAIRS = _binary_pairs()


def _author_graphic_relations(variant: int) -> AuthoredChoice:
    if variant < 5:
        prompt, correct, targeted, other_one, other_two = _MARKER_ROWS[variant]
        return _tagged_choice(
            prompt,
            correct,
            targeted,
            other_one,
            other_two,
            "功能标记跟随图形内部关系，不跟随页面上的固定坐标。",
            "relative-rule-preserved",
            "absolute-position-substituted",
        )
    left, right = _GRID_PAIRS[variant - 5]
    xor_value = left ^ right
    and_value = left & right
    or_value = left | right
    xnor_value = (~xor_value) & 0b1111
    values = (xor_value, and_value, or_value, xnor_value)
    if len(set(values)) != 4:
        raise AssertionError("binary grid answers must be distinct")
    return AuthoredChoice(
        prompt=(
            "两个2×2方格按“同色为白、异色为黑”逐格运算。"
            f"左图为{_grid(left)}，右图为{_grid(right)}，结果是："
        ),
        correct=_grid(xor_value),
        targeted_wrong=_grid(and_value),
        other_wrong=(_grid(or_value), _grid(xnor_value)),
        explanation="规则等价于逐格异或：两格不同时为黑，相同时为白。",
        verification={
            "adapter": "judgment_binary_grid_v1",
            "left": left,
            "right": right,
            "operation": "xor",
            "candidate_values": {
                _grid(xor_value): xor_value,
                _grid(and_value): and_value,
                _grid(or_value): or_value,
                _grid(xnor_value): xnor_value,
            },
            "targeted_value": and_value,
        },
    )


def _perfect_matchings(labels: tuple[str, ...]) -> list[tuple[tuple[str, str], ...]]:
    if not labels:
        return [tuple()]
    first = labels[0]
    result: list[tuple[tuple[str, str], ...]] = []
    for index in range(1, len(labels)):
        second = labels[index]
        remaining = labels[1:index] + labels[index + 1 :]
        for rest in _perfect_matchings(remaining):
            result.append(((first, second), *rest))
    return result


_CUBE_MATCHINGS = tuple(_perfect_matchings(tuple("ABCDEF"))[:10])


def _triple_text(values: Sequence[str]) -> str:
    return "、".join(values)


def _author_cube(variant: int) -> AuthoredChoice:
    pairs = _CUBE_MATCHINGS[variant]
    (a, d), (b, e), (c, f) = pairs
    correct = (a, b, c)
    targeted = (a, d, b)
    other_one = (b, e, c)
    other_two = (c, f, a)
    candidates = (correct, targeted, other_one, other_two)
    return AuthoredChoice(
        prompt=(
            "某正方体的三组相对面分别是"
            + "、".join(f"{left}-{right}" for left, right in pairs)
            + "。下列哪组三面可能在同一顶点相见？"
        ),
        correct=_triple_text(correct),
        targeted_wrong=_triple_text(targeted),
        other_wrong=(_triple_text(other_one), _triple_text(other_two)),
        explanation="共顶点的三面不能含任何一对相对面，只有正确项从三组相对面中各取一个。",
        verification={
            "adapter": "judgment_cube_opposites_v1",
            "opposite_pairs": [list(pair) for pair in pairs],
            "candidate_triples": {
                _triple_text(candidate): list(candidate) for candidate in candidates
            },
            "targeted_text": _triple_text(targeted),
        },
    )


def _author_definition(variant: int) -> AuthoredChoice:
    term, actor, timing, action, confirmation = _DEFINITION_ROWS[variant]
    correct, targeted, other_one, other_two = _DEFINITION_SCENARIOS[variant]
    requirements = ("actor", "timing", "action", "confirmation")
    return AuthoredChoice(
        prompt=f"本题把“{term}”定义为：{actor}在{timing}，{action}，并{confirmation}。下列属于“{term}”的是：",
        correct=correct,
        targeted_wrong=targeted,
        other_wrong=(other_one, other_two),
        explanation="定义中的主体、时点、动作和确认步骤必须同时满足；缺少任何一项都不符合。",
        verification={
            "adapter": "judgment_definition_constraints_v1",
            "required_constraints": list(requirements),
            "candidate_constraints": {
                correct: {key: True for key in requirements},
                targeted: {**{key: True for key in requirements}, "confirmation": False},
                other_one: {**{key: True for key in requirements}, "actor": False},
                other_two: {**{key: True for key in requirements}, "timing": False},
            },
            "targeted_text": targeted,
        },
    )


def _author_analogy(variant: int) -> AuthoredChoice:
    stem, correct, targeted, other_one, other_two, relation = _ANALOGY_ROWS[variant]
    return AuthoredChoice(
        prompt=f"下列哪组词与“{stem}”的关系最接近？",
        correct=correct,
        targeted_wrong=targeted,
        other_wrong=(other_one, other_two),
        explanation="先确定题干关系，再核对前后方向；正确项保持同一关系和同一方向。",
        verification={
            "adapter": "judgment_relation_vector_v1",
            "required_vector": [relation, "forward"],
            "candidate_vectors": {
                correct: [relation, "forward"],
                targeted: [relation, "reverse"],
                other_one: ["other-relation-1", "forward"],
                other_two: ["other-relation-2", "forward"],
            },
            "targeted_text": targeted,
        },
    )


def _author_strengthen(variant: int) -> AuthoredChoice:
    premise, conclusion, correct, targeted, other_one, other_two = _STRENGTHEN_ROWS[variant]
    return AuthoredChoice(
        prompt=f"{premise}。据此，研究小组认为：{conclusion}。以下哪项如果为真，最能加强这一结论？",
        correct=correct,
        targeted_wrong=targeted,
        other_wrong=(other_one, other_two),
        explanation="正确项排除关键混杂、补足机制或提供重复证据，使题干结论更可信。",
        verification={
            "adapter": "judgment_argument_strength_v1",
            "objective": "maximize",
            "candidate_scores": {correct: 4, targeted: 0, other_one: 1, other_two: -3},
            "targeted_text": targeted,
        },
    )


def _author_weaken(variant: int) -> AuthoredChoice:
    premise, conclusion, correct, targeted, other_one, other_two = _WEAKEN_ROWS[variant]
    return AuthoredChoice(
        prompt=f"{premise}。据此，研究小组认为：{conclusion}。以下哪项如果为真，最能削弱这一结论？",
        correct=correct,
        targeted_wrong=targeted,
        other_wrong=(other_one, other_two),
        explanation="正确项提供足以解释观察差异的混杂因素；副作用和表面信息不否定题干效果。",
        verification={
            "adapter": "judgment_argument_strength_v1",
            "objective": "minimize",
            "candidate_scores": {correct: -4, targeted: -1, other_one: 3, other_two: 0},
            "targeted_text": targeted,
        },
    )


Formula = Any


def _author_formal(variant: int) -> AuthoredChoice:
    p_text, q_text, r_text, s_text = _FORMAL_ROWS[variant]
    p, q, r, s = "P", "Q", "R", "S"
    common_premises: list[Formula] = [["implies", r, s], r]
    if variant % 2 == 0:
        premises = [["implies", p, q], q, *common_premises]
        targeted = p_text
        other_one = f"没有{p_text}"
        inference_note = f"已知{q_text}不能反推{p_text}"
    else:
        premises = [["implies", p, q], ["not", p], *common_premises]
        targeted = f"没有{q_text}"
        other_one = q_text
        inference_note = f"没有{p_text}不能推出没有{q_text}"
    correct = s_text
    other_two = f"没有{s_text}"
    candidate_formulas: dict[str, Formula] = {
        correct: s,
        targeted: p if variant % 2 == 0 else ["not", q],
        other_one: ["not", p] if variant % 2 == 0 else q,
        other_two: ["not", s],
    }
    premise_text = (
        f"如果{p_text}，那么{q_text}。"
        + (f"现已知{q_text}。" if variant % 2 == 0 else f"现已知没有{p_text}。")
        + f"另外，如果{r_text}，那么{s_text}；现已知{r_text}。"
    )
    return AuthoredChoice(
        prompt=premise_text + "以下哪项一定为真？",
        correct=correct,
        targeted_wrong=targeted,
        other_wrong=(other_one, other_two),
        explanation=f"由{r_text}可沿有效方向推出{s_text}；{inference_note}。",
        verification={
            "adapter": "judgment_truth_table_v1",
            "atoms": [p, q, r, s],
            "premises": premises,
            "candidate_formulas": candidate_formulas,
            "targeted_text": targeted,
        },
    )


_AUTHORS: tuple[Callable[[int], AuthoredChoice], ...] = (
    _author_graphic_properties,
    _author_graphic_relations,
    _author_cube,
    _author_definition,
    _author_analogy,
    _author_strengthen,
    _author_weaken,
    _author_formal,
)
_UNIT_BY_ID = {spec.diagnostic_unit_id: spec for spec in JUDGMENT_UNITS}


def _option_texts(question: Mapping[str, Any], verification: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    options = question.get("options")
    candidates = verification.get(field)
    if not isinstance(options, Mapping) or not isinstance(candidates, Mapping):
        raise PracticeBankValidationError(f"judgment {field} must map every option text")
    if set(candidates) != {str(value) for value in options.values()}:
        raise PracticeBankValidationError(f"judgment {field} does not match option texts")
    return candidates


def _verify_answer_and_target(
    question: Mapping[str, Any], spec: UnitSpec, correct_text: str, targeted_text: str
) -> None:
    scoring = question["scoring"]
    options = question["options"]
    if scoring["canonical_answer"] != correct_text or correct_text == targeted_text:
        raise PracticeBankValidationError("judgment answer disagrees with deterministic oracle")
    diagnostic_options = [
        option_id
        for option_id, mapping in scoring["error_option_mappings"].items()
        if mapping["signature_id"] == spec.signature_id
    ]
    if len(diagnostic_options) != 1 or options[diagnostic_options[0]] != targeted_text:
        raise PracticeBankValidationError("judgment targeted distractor lost its signature")


def _eval_formula(formula: Formula, values: Mapping[str, bool], atoms: set[str]) -> bool:
    if isinstance(formula, str):
        if formula not in atoms:
            raise PracticeBankValidationError(f"unknown propositional atom: {formula}")
        return values[formula]
    if not isinstance(formula, list) or not formula or not isinstance(formula[0], str):
        raise PracticeBankValidationError("invalid propositional formula")
    operator = formula[0]
    if operator == "not" and len(formula) == 2:
        return not _eval_formula(formula[1], values, atoms)
    if operator in {"and", "or", "implies"} and len(formula) == 3:
        left = _eval_formula(formula[1], values, atoms)
        right = _eval_formula(formula[2], values, atoms)
        if operator == "and":
            return left and right
        if operator == "or":
            return left or right
        return (not left) or right
    raise PracticeBankValidationError(f"unsupported propositional operator: {operator}")


def verify_judgment_question(question: Mapping[str, Any]) -> None:
    """Recompute the structural oracle for every judgment adapter."""

    spec = _UNIT_BY_ID.get(str(question.get("diagnostic_unit_id")))
    if spec is None:
        raise PracticeBankValidationError("judgment question references an unknown unit")
    verification = question.get("verification")
    if not isinstance(verification, Mapping):
        raise PracticeBankValidationError("judgment verification must be an object")
    adapter = verification.get("adapter")

    if adapter == "judgment_constraint_tags_v1":
        candidates = _option_texts(question, verification, "candidate_tags")
        required = verification.get("required_tag")
        targeted_tag = verification.get("targeted_tag")
        if not isinstance(required, str) or not isinstance(targeted_tag, str):
            raise PracticeBankValidationError("judgment tags must be strings")
        correct = [text for text, tags in candidates.items() if required in tags]
        targeted = [text for text, tags in candidates.items() if targeted_tag in tags]
    elif adapter == "judgment_graph_features_v1":
        candidates = _option_texts(question, verification, "candidate_features")
        requirements = verification.get("requirements")
        if not isinstance(requirements, Mapping) or not requirements:
            raise PracticeBankValidationError("graph feature requirements are missing")
        correct = [
            text
            for text, values in candidates.items()
            if isinstance(values, Mapping)
            and all(values.get(key) == expected for key, expected in requirements.items())
        ]
        targeted = [verification.get("targeted_text")]
    elif adapter == "judgment_euler_trail_v1":
        candidates = _option_texts(question, verification, "candidate_values")
        degrees = verification.get("degrees")
        if (
            not isinstance(degrees, list)
            or not degrees
            or any(not isinstance(value, int) or value <= 0 for value in degrees)
            or sum(degrees) % 2
            or verification.get("connected") is not True
        ):
            raise PracticeBankValidationError("invalid connected graph degree sequence")
        odd_count = sum(value % 2 for value in degrees)
        expected = max(1, odd_count // 2)
        correct = [text for text, value in candidates.items() if value == expected]
        targeted = [text for text, value in candidates.items() if value == verification.get("targeted_value")]
    elif adapter == "judgment_binary_grid_v1":
        candidates = _option_texts(question, verification, "candidate_values")
        left, right = verification.get("left"), verification.get("right")
        if not isinstance(left, int) or not isinstance(right, int) or verification.get("operation") != "xor":
            raise PracticeBankValidationError("invalid binary-grid oracle")
        expected = left ^ right
        correct = [text for text, value in candidates.items() if value == expected]
        targeted = [text for text, value in candidates.items() if value == verification.get("targeted_value")]
    elif adapter == "judgment_cube_opposites_v1":
        candidates = _option_texts(question, verification, "candidate_triples")
        raw_pairs = verification.get("opposite_pairs")
        if not isinstance(raw_pairs, list) or len(raw_pairs) != 3:
            raise PracticeBankValidationError("cube needs three opposite pairs")
        pairs = [set(pair) for pair in raw_pairs]
        if any(len(pair) != 2 for pair in pairs) or len(set().union(*pairs)) != 6:
            raise PracticeBankValidationError("cube opposite pairs must partition six faces")
        correct = [
            text
            for text, triple in candidates.items()
            if isinstance(triple, list)
            and len(set(triple)) == 3
            and all(not pair.issubset(set(triple)) for pair in pairs)
        ]
        targeted = [verification.get("targeted_text")]
    elif adapter == "judgment_definition_constraints_v1":
        candidates = _option_texts(question, verification, "candidate_constraints")
        required = verification.get("required_constraints")
        if not isinstance(required, list) or not required:
            raise PracticeBankValidationError("definition constraints are missing")
        correct = [
            text
            for text, values in candidates.items()
            if isinstance(values, Mapping) and all(values.get(key) is True for key in required)
        ]
        targeted = [verification.get("targeted_text")]
    elif adapter == "judgment_relation_vector_v1":
        candidates = _option_texts(question, verification, "candidate_vectors")
        required = verification.get("required_vector")
        if not isinstance(required, list) or len(required) != 2:
            raise PracticeBankValidationError("relation vector is missing")
        correct = [text for text, vector in candidates.items() if vector == required]
        targeted = [verification.get("targeted_text")]
    elif adapter == "judgment_argument_strength_v1":
        candidates = _option_texts(question, verification, "candidate_scores")
        if any(not isinstance(value, int) for value in candidates.values()):
            raise PracticeBankValidationError("argument scores must be integers")
        objective = verification.get("objective")
        if objective == "maximize":
            best = max(candidates.values())
        elif objective == "minimize":
            best = min(candidates.values())
        else:
            raise PracticeBankValidationError("argument objective is invalid")
        correct = [text for text, score in candidates.items() if score == best]
        targeted = [verification.get("targeted_text")]
    elif adapter == "judgment_truth_table_v1":
        candidates = _option_texts(question, verification, "candidate_formulas")
        raw_atoms = verification.get("atoms")
        premises = verification.get("premises")
        if not isinstance(raw_atoms, list) or not isinstance(premises, list) or len(set(raw_atoms)) != len(raw_atoms):
            raise PracticeBankValidationError("truth-table atoms or premises are invalid")
        atoms = set(raw_atoms)
        models: list[dict[str, bool]] = []
        for bits in product((False, True), repeat=len(raw_atoms)):
            values = dict(zip(raw_atoms, bits, strict=True))
            if all(_eval_formula(premise, values, atoms) for premise in premises):
                models.append(values)
        if not models:
            raise PracticeBankValidationError("truth-table premises are inconsistent")
        correct = [
            text
            for text, formula in candidates.items()
            if all(_eval_formula(formula, values, atoms) for values in models)
        ]
        targeted = [verification.get("targeted_text")]
    else:
        raise PracticeBankValidationError(f"unsupported judgment verification adapter: {adapter}")

    if len(correct) != 1 or len(targeted) != 1 or not isinstance(targeted[0], str):
        raise PracticeBankValidationError("judgment oracle is not uniquely solvable")
    if targeted[0] not in question["options"].values():
        raise PracticeBankValidationError("judgment target is not an answer choice")
    if adapter == "judgment_definition_constraints_v1" and str(correct[0]) in str(question["prompt"]):
        raise PracticeBankValidationError("definition item leaks its full correct option in the stem")
    _verify_answer_and_target(question, spec, str(correct[0]), targeted[0])


def generate_judgment_bank() -> tuple[list[UnitSpec], list[dict[str, Any]]]:
    questions: list[dict[str, Any]] = []
    for local_index, (unit_index, variant) in enumerate(schedule_pairs()):
        questions.append(
            build_question(
                JUDGMENT_UNITS[unit_index],
                local_index=local_index,
                variant=variant,
                authored=_AUTHORS[unit_index](variant),
            )
        )
    validate_generated_module("judgment", JUDGMENT_UNITS, questions, verify_judgment_question)
    if len({question["prompt"] for question in questions}) != len(questions):
        raise PracticeBankValidationError("judgment prompts must be unique")
    return list(JUDGMENT_UNITS), questions


if __name__ == "__main__":
    generated_units, generated_questions = generate_judgment_bank()
    print(f"judgment self-check passed: {len(generated_units)} units / {len(generated_questions)} questions")
