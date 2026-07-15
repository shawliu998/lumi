from __future__ import annotations

from typing import Any, Callable, Mapping

from .practice_v3_common import (
    AuthoredChoice,
    PracticeBankValidationError,
    UnitSpec,
    build_question,
    schedule_pairs,
    validate_generated_module,
)


VERBAL_UNITS: tuple[UnitSpec, ...] = (
    UnitSpec(
        module_slug="verbal",
        unit_slug="main-idea-structure",
        unit_label="从篇章结构找中心",
        signature_slug="background-selected",
        signature_label="把背景信息当成中心观点",
        observable_rule="所选项只复述文段开头的背景或现象，没有覆盖作者最后提出的核心主张。",
        cause_slugs=("root-not-isolated", "scope-not-checked"),
        cause_labels=("可能尚未把背景与作者主张分开", "可能没有核对选项覆盖范围"),
        principle="先区分背景、问题和作者主张；中心项必须覆盖作者最终要表达的内容。",
        worked_contrast="“已有阅读空间”是背景，“应按借阅记录更新书目”才是作者主张。",
        return_action="作答前用一句话写出文段最后要推动的行动或结论。",
    ),
    UnitSpec(
        module_slug="verbal",
        unit_slug="turning-contrast",
        unit_label="转折后的表达重点",
        signature_slug="pre-turn-selected",
        signature_label="选择了转折前观点",
        observable_rule="题干明确修正前一种看法，所选项却仍复述转折前内容。",
        cause_slugs=("turn-not-applied",),
        cause_labels=("可能识别了转折词但没有更新表达重点",),
        principle="转折不是把两边平均相加，而是用后半句修正前半句。",
        worked_contrast="“工具很多，但缺少统一规则”强调规则，而不是工具数量。",
        return_action="看到“但、然而、其实”后，先单独复述后半句。",
    ),
    UnitSpec(
        module_slug="verbal",
        unit_slug="cause-condition",
        unit_label="因果与必要条件",
        signature_slug="condition-reversed",
        signature_label="把必要条件说成充分条件",
        observable_rule="题干只说明某条件不可缺少，所选项却断言具备该条件便必然实现目标。",
        cause_slugs=("necessary-sufficient-confused",),
        cause_labels=("可能尚未区分“没有不行”和“有了就一定行”",),
        principle="“只有 B 才 A”表示 A 离不开 B，不表示有 B 就一定能 A。",
        worked_contrast="有统一标记是档案一致的必要条件，但还需要实际执行，不能据此断言必然一致。",
        return_action="把条件句改写成“目标离不开什么”，再核对选项方向。",
    ),
    UnitSpec(
        module_slug="verbal",
        unit_slug="parallel-progressive",
        unit_label="并列概括与递进重点",
        signature_slug="single-branch",
        signature_label="只概括一个并列分支",
        observable_rule="文段列出多个共同服务于主题的方面，所选项只保留其中一项。",
        cause_slugs=("coverage-not-checked",),
        cause_labels=("可能没有逐项核对概括范围",),
        principle="并列内容先找共同主题，再检查选项是否覆盖全部必要分支。",
        worked_contrast="联络人、物资和路线共同构成应急准备，只写联络人属于片面概括。",
        return_action="用三个短词标出并列分支，排除只覆盖一个分支的选项。",
    ),
    UnitSpec(
        module_slug="verbal",
        unit_slug="counterfactual-temporal",
        unit_label="反面论证与时空变化",
        signature_slug="old-state-selected",
        signature_label="把旧状态当成当前观点",
        observable_rule="题干通过时间或阶段对比强调新状态，所选项却只描述已被更新的旧状态。",
        cause_slugs=("time-anchor-missed",),
        cause_labels=("可能没有锁定作者当前所处的时间或阶段",),
        principle="出现过去与现在的对照时，先确认问题问的是哪个时间锚点。",
        worked_contrast="过去只按数量整理，现在还按用途整理；当前观点应包含用途维度。",
        return_action="圈出时间词，并把旧状态与新状态分别压缩成一句话。",
    ),
    UnitSpec(
        module_slug="verbal",
        unit_slug="cloze-collocation",
        unit_label="逻辑填空：固定搭配",
        signature_slug="collocation-violation",
        signature_label="近义方向相近但搭配不成立",
        observable_rule="所选词大致接近语境方向，但与横线后的核心名词不构成稳定搭配。",
        cause_slugs=("object-not-checked",),
        cause_labels=("可能只比较词义，没有回看搭配对象",),
        principle="先找到横线的搭配对象，再比较近义词；方向相近不等于能够搭配。",
        worked_contrast="可以“提供依据”，不能“承担依据”。",
        return_action="把候选词逐个与横线后的名词连读一遍。",
    ),
    UnitSpec(
        module_slug="verbal",
        unit_slug="cloze-degree-polarity",
        unit_label="逻辑填空：程度与极性",
        signature_slug="degree-overstated",
        signature_label="所选词程度超过语境",
        observable_rule="题干含有限定程度的线索，所选词表达的强度明显高于这些线索。",
        cause_slugs=("degree-cue-missed",),
        cause_labels=("可能忽略了“略、仅、局部”等程度线索",),
        principle="程度词必须与语境强度一致；看到“略、仅、偶有”要警惕过重选项。",
        worked_contrast="只改标题、正文未动，影响是“有限”，不是“深远”。",
        return_action="先给语境标注轻、中、重，再选择同等级的词。",
    ),
    UnitSpec(
        module_slug="verbal",
        unit_slug="cloze-context-correspondence",
        unit_label="逻辑填空：全文对应",
        signature_slug="local-clue-only",
        signature_label="只追随局部词语而偏离全文",
        observable_rule="所选词与横线附近某个词表面呼应，但不能完成全文的中心语义。",
        cause_slugs=("global-meaning-not-checked",),
        cause_labels=("可能只看横线附近，没有用完整句意复核",),
        principle="局部搭配通过后，还要把词放回整句，检查它是否完成全文表达。",
        worked_contrast="工具“整理”记录只是手段，全文强调的是它“辅助”判断。",
        return_action="填入后把整句读完，并追问这句话最终在说明什么。",
    ),
)


_MAIN_ROWS = (
    ("社区图书角让居民可以就近阅读", "部分书目长期无人借阅，新需求也得不到满足", "管理者应依据借阅记录定期调整书目", "社区图书角方便居民就近阅读", "无人借阅的书都没有保留价值", "所有公共阅读空间都应每天更换书目"),
    ("学校开辟了供学生照料的小花园", "只分配土地而不记录养护过程，学生很难比较方法", "课程应加入简短的观察记录", "学校为学生提供了种植空间", "观察记录可以代替全部种植实践", "每门课程都必须建设大型花园"),
    ("社区设置了旧物交换架", "物品分类含糊时，居民常常找不到合适区域", "交换架需要使用清晰且统一的分类标签", "旧物交换可以减少闲置", "分类越多就一定越方便", "所有闲置物品都应进入交换架"),
    ("阅览室延长了开放时间", "闭馆前的归还高峰仍会造成排队", "阅览室可增加自助归还点来分散高峰", "延长开放时间方便了读者", "排队完全由读者习惯造成", "任何阅览室都不再需要人工服务"),
    ("工作组积累了大量会议记录", "文件命名方式不一致使后续检索变慢", "团队应先统一文件命名规则", "会议记录数量不断增加", "文件越长越难检索", "统一名称可以解决协作中的一切问题"),
    ("公园增设了饮水点", "位置说明不清使初次到访者难以找到", "入口地图应明确标出饮水点位置", "公园为游客提供饮水设施", "初次到访者不应独自游园", "所有公园设施都必须集中在入口"),
    ("校内开放了共享工具柜", "借还记录缺失时，损坏责任难以追溯", "工具柜应采用简明的借还登记", "共享工具能够提高使用率", "登记可以保证工具永不损坏", "所有个人工具都应改为共享"),
    ("社区组织居民学习垃圾分类", "只讲分类名称而缺少实物示例，容易在投放时混淆", "讲解应结合常见物品进行演示", "垃圾分类包含多个名称", "实物演示能够替代长期管理", "每次投放都必须由专人监督"),
    ("资料室完成了纸质文件数字化", "扫描件没有关键词时仍然难以检索", "数字化后还应补充规范的关键词", "纸质文件可以转成扫描件", "关键词越多检索就越准确", "纸质文件应立即全部销毁"),
    ("小区新增了公共晾晒区", "使用时段没有约定会造成集中占用", "居民可共同制定简明的时段规则", "公共晾晒区增加了可用空间", "集中使用一定属于故意占用", "所有公共空间都应按分钟预约"),
)


_TURN_ROWS = (
    ("线上表格越复杂，记录就越专业", "字段过多会增加遗漏，表格应只保留真正用于判断的信息"),
    ("活动场地越大，参与体验就越好", "清晰的动线和分区往往比单纯扩大面积更重要"),
    ("提示越频繁，使用者越不容易出错", "过多提示会遮住关键信息，提示应集中在高风险步骤"),
    ("资料保存得越多，团队记忆就越完整", "没有分类和版本标识的堆积反而会妨碍复用"),
    ("阅读速度快就代表理解充分", "能否准确复述论证关系才更能反映理解程度"),
    ("设备功能越多越适合所有人", "常用任务能否被简洁完成比功能数量更值得关注"),
    ("会议时间越长，讨论就越深入", "明确问题和结论比延长会议更能提高讨论质量"),
    ("规则写得越细，执行分歧就越少", "缺少示例和边界说明时，细密条文仍可能产生歧义"),
    ("学习材料越难，训练效果就越好", "难度只有与当前能力匹配时才能形成有效练习"),
    ("公共空间保持安静就不能开展交流", "合理划分安静区和交流区可以同时满足两种需要"),
)


_CONDITION_ROWS = (
    ("多人共同维护档案时", "建立统一标记规则", "让记录保持一致"),
    ("居民轮流照看公共花圃时", "明确每次交接的事项", "避免养护任务遗漏"),
    ("团队复用旧方案时", "保留方案适用条件", "判断方案能否迁移"),
    ("学习者复盘错题时", "记录当时选择的选项", "还原可观察的错误路径"),
    ("图书角调整书目时", "统计一段时间的借阅情况", "识别真实阅读需求"),
    ("社区发布应急指引时", "给出清晰的行动顺序", "让居民在紧急时快速执行"),
    ("工作组比较两个版本时", "固定比较的指标", "得出可解释的差异"),
    ("志愿者交接服务对象时", "取得必要的授权并限定信息范围", "保护个人信息"),
    ("课程安排迁移练习时", "更换材料而保留目标技能", "检验知识是否真正迁移"),
    ("维护人员排查设备故障时", "先记录故障出现的条件", "稳定复现问题"),
)


_PARALLEL_ROWS = (
    ("社区应急准备", "明确联络人", "定期检查物资", "让居民熟悉疏散路线"),
    ("维护共享工具柜", "登记借还情况", "及时补充耗材", "标记故障工具"),
    ("提高资料可检索性", "统一文件名称", "补充主题关键词", "保留版本日期"),
    ("组织一次有效讨论", "提前说明问题", "控制发言顺序", "记录明确结论"),
    ("设计清晰的办事指引", "拆分办理步骤", "标出所需材料", "说明异常处理方式"),
    ("开展校园观察活动", "提出可验证问题", "连续记录现象", "比较不同时间结果"),
    ("管理公共阅读空间", "保持书目更新", "划分安静区域", "提供归还提示"),
    ("完善志愿服务交接", "说明未完成事项", "确认下一位负责人", "限制敏感信息传播"),
    ("进行错题复盘", "保存原始作答", "识别选项模式", "安排未提示的新题"),
    ("改善小区步行体验", "清理通道障碍", "补充夜间照明", "设置连续方向标识"),
)


_TEMPORAL_ROWS = (
    ("过去整理藏书只按书本大小摆放", "现在还会按照主题和使用频率分类", "藏书整理开始关注内容与使用需要"),
    ("以前设备报修只记录故障名称", "现在还记录出现时间和使用条件", "报修记录开始支持故障复现"),
    ("过去活动结束后只统计到场人数", "现在还收集完成情况和后续需求", "活动评价从人数扩展到实际效果"),
    ("以前会议纪要只抄录发言", "现在重点记录决定、负责人和期限", "会议记录更重视可执行结论"),
    ("过去图书推荐主要依靠管理员经验", "现在还参考匿名借阅趋势", "书目推荐开始结合实际使用信息"),
    ("以前课程只在课后给出总分", "现在还标记不同技能的表现", "学习反馈开始呈现具体技能差异"),
    ("过去公园地图只画主要道路", "现在还标出饮水点和无障碍入口", "公园地图开始覆盖具体使用需求"),
    ("以前工具柜只在缺件时补充", "现在还定期检查磨损和归还情况", "工具维护从被动补缺转向持续检查"),
    ("过去社区通知只张贴在公告栏", "现在还提供可搜索的电子版本", "社区信息开始兼顾线下触达与后续检索"),
    ("以前错题本只保存正确答案", "现在还记录错误选项和再次验证结果", "错题记录开始关注错误证据与迁移表现"),
)


_COLLOCATION_ROWS = (
    ("持续记录能够____后续改进的依据。", "提供", "承担", "躲避", "观赏", "“提供依据”是稳定搭配。"),
    ("吸音材料可以有效____室内噪声。", "降低", "缩短", "播种", "编写", "噪声强弱用“降低”，不用“缩短”。"),
    ("合理轮值有助于____照看压力。", "缓解", "缩小", "打印", "收藏", "“缓解压力”搭配自然。"),
    ("固定的复盘时间有助于____学习习惯。", "形成", "制造", "搬运", "围观", "习惯可以“形成”，不能“制造”。"),
    ("简明索引能够充分____检索作用。", "发挥", "表演", "栽培", "折叠", "“发挥作用”是固定搭配。"),
    ("柔和照明可以____安静的阅读氛围。", "营造", "生产", "测量", "搬迁", "氛围通常与“营造”搭配。"),
    ("值班人员需要共同____现场秩序。", "维护", "保养", "朗读", "裁剪", "秩序使用“维护”，设备才常用“保养”。"),
    ("线上入口能够进一步____意见收集渠道。", "拓宽", "放宽", "搅拌", "冻结", "渠道可以“拓宽”，条件才常用“放宽”。"),
    ("定期检查可以及时____安全隐患。", "消除", "擦除", "背诵", "漂洗", "隐患通常使用“消除”。"),
    ("统一模板能够有效____协作效率。", "提升", "抬升", "修剪", "围绕", "效率通常使用“提升”。"),
)


_DEGREE_ROWS = (
    ("这次修改只调整了标题，正文几乎未变，整体影响十分____。", "有限", "深远", "甜美", "笔直", "“只、几乎未变”限定为较轻程度。"),
    ("水面只有几圈细小波纹，变化十分____。", "轻微", "剧烈", "整齐", "漫长", "细小波纹对应轻微变化。"),
    ("试运行中偶尔出现短暂等待，问题总体较为____。", "局部", "全面", "芳香", "坚硬", "“偶尔、短暂”不能推出全面问题。"),
    ("新标签让查找时间略有下降，改进效果尚属____。", "有限", "显著", "遥远", "锋利", "“略有”限定了效果强度。"),
    ("只有少数页面出现间距偏差，影响相对____。", "较小", "巨大", "透明", "喧闹", "少数页面对应较小影响。"),
    ("这次讨论仅澄清了一个术语，成果比较____。", "有限", "空前", "潮湿", "圆润", "“仅一个术语”不支持空前成果。"),
    ("设备启动时偶有轻响，但运行保持正常，异常程度很____。", "轻", "严重", "宽阔", "迅速", "偶有轻响且运行正常，程度应轻。"),
    ("两组记录只有个别标点不同，差异十分____。", "细微", "悬殊", "温暖", "曲折", "个别标点差异属于细微。"),
    ("入口位置向左移动了一小段，布局变化相当____。", "有限", "彻底", "清脆", "浓厚", "一小段位移不构成彻底变化。"),
    ("本轮练习只增加了一道示例，内容调整较为____。", "轻微", "根本", "明亮", "繁忙", "只增加一道示例说明调整轻微。"),
)


_CONTEXT_ROWS = (
    ("这种工具并不替人作决定，而是把散落记录整理成可检查的线索，因此它的价值在于____判断，而非取代判断。", "辅助", "整理", "拒绝", "隐藏", "整理记录是手段，辅助判断才是全文落点。"),
    ("地图不只是画出道路，更要帮助初次到访者找到目的地，因此清晰标识能够____行动。", "引导", "绘制", "阻断", "遗忘", "绘制只是制作动作，全文强调引导行动。"),
    ("复盘不是重复抄写答案，而是比较原选择与新证据，从而____错误模式。", "识别", "抄写", "掩盖", "装饰", "抄写出现在对比项中，识别错误模式才是目的。"),
    ("共享空间的规则不是为了增加限制，而是让不同需要能够相互____。", "协调", "增加", "逃离", "复制", "增加限制被否定，全文强调协调需要。"),
    ("延迟练习更换了题面，却保留同一技能，目的是____学习是否能够迁移。", "检验", "更换", "取消", "想象", "更换题面是方法，检验迁移是目的。"),
    ("索引把分散文件连接到统一入口，使资料不再彼此孤立，从而形成可____的整体。", "检索", "连接", "燃烧", "漂浮", "连接是过程，最终要求整体能够被检索。"),
    ("轮值表明确谁在何时负责什么事项，它不是简单列出姓名，而是在____责任边界。", "界定", "列出", "模糊", "搬运", "列出姓名只是表面动作，全文强调界定责任。"),
    ("简短示例把抽象规则放进具体场景，作用是帮助使用者____规则。", "理解", "放置", "拒斥", "裁剪", "放进场景是比喻表达，落点是理解规则。"),
    ("版本记录保留每次修改的时间和内容，使团队能够____变化过程。", "追溯", "保留", "中断", "折叠", "保留记录是手段，追溯过程是用途。"),
    ("迁移题不提供旧题提示，是为了观察学习者能否____调用方法。", "独立", "观察", "被动", "偶然", "观察是测试动作，全文要检验独立调用。"),
)


def _tagged_choice(
    *,
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
            "adapter": "verbal_constraint_tags_v1",
            "required_tags": [required_tag],
            "forbidden_tags": ["invalid"],
            "targeted_tag": targeted_tag,
            "candidate_tags": {
                correct: [required_tag],
                targeted: [targeted_tag, "invalid"],
                other_one: ["other-error-1", "invalid"],
                other_two: ["other-error-2", "invalid"],
            },
        },
    )


def _author_main(variant: int) -> AuthoredChoice:
    background, issue, action, background_option, detail_option, broad_option = _MAIN_ROWS[variant]
    return _tagged_choice(
        prompt=f"{background}。{issue}。因此，{action}。这段文字意在说明：",
        correct=action,
        targeted=background_option,
        other_one=detail_option,
        other_two=broad_option,
        explanation=f"前两句交代背景和问题，结尾用“因此”提出主张，中心是“{action}”。",
        required_tag="central-claim",
        targeted_tag="background-only",
    )


def _author_turn(variant: int) -> AuthoredChoice:
    before, after = _TURN_ROWS[variant]
    return _tagged_choice(
        prompt=f"有人认为{before}，但{after}。这段话强调：",
        correct=after,
        targeted=before,
        other_one="前后两种看法同样适用于所有情形",
        other_two="这个问题没有必要继续讨论",
        explanation=f"“但”之后修正了前一种看法，表达重点是“{after}”。",
        required_tag="post-turn-focus",
        targeted_tag="pre-turn-focus",
    )


def _author_condition(variant: int) -> AuthoredChoice:
    context, prerequisite, goal = _CONDITION_ROWS[variant]
    return _tagged_choice(
        prompt=f"{context}，只有{prerequisite}，才能{goal}。由此可以推出：",
        correct=f"{prerequisite}是{goal}的必要条件",
        targeted=f"一旦{prerequisite}，{goal}就必然完成",
        other_one=f"{goal}无需任何前提",
        other_two=f"{prerequisite}与{goal}没有关系",
        explanation="“只有……才……”只保证后项是前项目标的必要条件，不能反推充分性。",
        required_tag="necessary-condition",
        targeted_tag="necessary-treated-as-sufficient",
    )


def _author_parallel(variant: int) -> AuthoredChoice:
    topic, first, second, third = _PARALLEL_ROWS[variant]
    return _tagged_choice(
        prompt=f"{topic}既要{first}，也要{second}，更要{third}。这句话主要说明：",
        correct=f"{topic}需要同时兼顾{first}、{second}和{third}",
        targeted=f"做好{topic}只需要{first}",
        other_one=f"{first}与{second}彼此冲突",
        other_two=f"任何场景都应原样照搬这三项做法",
        explanation="三个分支共同服务于同一主题，正确概括必须同时覆盖，不能只取第一项。",
        required_tag="covers-all-branches",
        targeted_tag="single-branch-only",
    )


def _author_temporal(variant: int) -> AuthoredChoice:
    old, current, conclusion = _TEMPORAL_ROWS[variant]
    return _tagged_choice(
        prompt=f"{old}；{current}。由此可见：",
        correct=conclusion,
        targeted=old,
        other_one="前后两个阶段的做法完全相同",
        other_two="这一变化适用于所有组织和所有任务",
        explanation=f"分号前后构成阶段对比，当前变化可概括为“{conclusion}”。",
        required_tag="current-state-conclusion",
        targeted_tag="old-state-only",
    )


def _author_collocation(variant: int) -> AuthoredChoice:
    prompt, correct, targeted, other_one, other_two, explanation = _COLLOCATION_ROWS[variant]
    return _tagged_choice(
        prompt=prompt,
        correct=correct,
        targeted=targeted,
        other_one=other_one,
        other_two=other_two,
        explanation=explanation,
        required_tag="valid-collocation",
        targeted_tag="semantic-near-collocation-invalid",
    )


def _author_degree(variant: int) -> AuthoredChoice:
    prompt, correct, targeted, other_one, other_two, explanation = _DEGREE_ROWS[variant]
    return _tagged_choice(
        prompt=prompt,
        correct=correct,
        targeted=targeted,
        other_one=other_one,
        other_two=other_two,
        explanation=explanation,
        required_tag="degree-matched",
        targeted_tag="degree-overstated",
    )


def _author_context(variant: int) -> AuthoredChoice:
    prompt, correct, targeted, other_one, other_two, explanation = _CONTEXT_ROWS[variant]
    return _tagged_choice(
        prompt=prompt,
        correct=correct,
        targeted=targeted,
        other_one=other_one,
        other_two=other_two,
        explanation=explanation,
        required_tag="global-meaning-complete",
        targeted_tag="local-clue-only",
    )


_AUTHORS: tuple[Callable[[int], AuthoredChoice], ...] = (
    _author_main,
    _author_turn,
    _author_condition,
    _author_parallel,
    _author_temporal,
    _author_collocation,
    _author_degree,
    _author_context,
)
_UNIT_BY_ID = {spec.diagnostic_unit_id: spec for spec in VERBAL_UNITS}


def _as_string_set(value: Any, context: str) -> set[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise PracticeBankValidationError(f"{context} must be a non-empty string list")
    result = set(value)
    if len(result) != len(value):
        raise PracticeBankValidationError(f"{context} cannot contain duplicates")
    return result


def verify_verbal_question(question: Mapping[str, Any]) -> None:
    """Recompute the authored semantic oracle without trusting the answer letter."""

    spec = _UNIT_BY_ID.get(str(question.get("diagnostic_unit_id")))
    if spec is None:
        raise PracticeBankValidationError("verbal question references an unknown unit")
    verification = question.get("verification")
    if not isinstance(verification, Mapping) or verification.get("adapter") != "verbal_constraint_tags_v1":
        raise PracticeBankValidationError("unsupported verbal verification adapter")
    required = _as_string_set(verification.get("required_tags"), "required_tags")
    forbidden = _as_string_set(verification.get("forbidden_tags"), "forbidden_tags")
    targeted_tag = verification.get("targeted_tag")
    if not isinstance(targeted_tag, str) or not targeted_tag:
        raise PracticeBankValidationError("verbal verification needs a targeted tag")
    options = question.get("options")
    candidates = verification.get("candidate_tags")
    if not isinstance(options, Mapping) or not isinstance(candidates, Mapping):
        raise PracticeBankValidationError("verbal options and candidate tags must be mappings")
    option_texts = {str(value) for value in options.values()}
    if set(candidates) != option_texts:
        raise PracticeBankValidationError("verbal oracle must describe every option text exactly once")

    satisfying: list[str] = []
    targeted: list[str] = []
    for text, raw_tags in candidates.items():
        tags = _as_string_set(raw_tags, f"candidate_tags[{text}]")
        if required.issubset(tags) and tags.isdisjoint(forbidden):
            satisfying.append(str(text))
        if targeted_tag in tags:
            targeted.append(str(text))
    if len(satisfying) != 1 or len(targeted) != 1 or satisfying[0] == targeted[0]:
        raise PracticeBankValidationError("verbal semantic oracle is not uniquely solvable")

    scoring = question["scoring"]
    if scoring["canonical_answer"] != satisfying[0]:
        raise PracticeBankValidationError("verbal answer disagrees with semantic oracle")
    diagnostic_options = [
        option_id
        for option_id, mapping in scoring["error_option_mappings"].items()
        if mapping["signature_id"] == spec.signature_id
    ]
    if len(diagnostic_options) != 1 or options[diagnostic_options[0]] != targeted[0]:
        raise PracticeBankValidationError("verbal targeted distractor lost its error signature")


def generate_verbal_bank() -> tuple[list[UnitSpec], list[dict[str, Any]]]:
    questions: list[dict[str, Any]] = []
    for local_index, (unit_index, variant) in enumerate(schedule_pairs()):
        authored = _AUTHORS[unit_index](variant)
        questions.append(
            build_question(
                VERBAL_UNITS[unit_index],
                local_index=local_index,
                variant=variant,
                authored=authored,
            )
        )
    validate_generated_module("verbal", VERBAL_UNITS, questions, verify_verbal_question)
    if len({question["prompt"] for question in questions}) != len(questions):
        raise PracticeBankValidationError("verbal prompts must be unique")
    return list(VERBAL_UNITS), questions


if __name__ == "__main__":
    generated_units, generated_questions = generate_verbal_bank()
    print(f"verbal self-check passed: {len(generated_units)} units / {len(generated_questions)} questions")
