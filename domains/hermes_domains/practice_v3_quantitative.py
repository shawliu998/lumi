from __future__ import annotations

from fractions import Fraction
from math import comb, factorial, gcd, lcm
from typing import Any, Mapping

from .practice_v3_common import (
    AuthoredChoice,
    MODULE_SCOPES,
    PracticeBankValidationError,
    UnitSpec,
    build_question,
    schedule_pairs,
    validate_generated_module,
    verify_common_question,
)


MODULE_SLUG = "quantitative"


UNITS: tuple[UnitSpec, ...] = (
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="work-rate",
        unit_label="工程效率",
        signature_slug="time-sum",
        signature_label="把单独完工时间直接相加",
        observable_rule="所选项等于目标工作比例乘以两人的单独完工时间之和",
        cause_slugs=("rate-time-relation",),
        cause_labels=("可能尚未把完工时间先转换为单位时间效率",),
        principle="合作完成同一任务时应相加效率，而不是相加各自的完工时间。",
        worked_contrast="甲单独6小时、乙单独12小时，合作效率是1/6+1/12=1/4，完成时间为4小时。",
        return_action="先把每个完工时间写成单位时间完成量，再合并效率。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="relative-travel",
        unit_label="相对行程",
        signature_slug="relative-speed-sign",
        signature_label="把相遇与追及的相对速度符号写反",
        observable_rule="相遇题所选项使用速度差，或追及题所选项使用速度和",
        cause_slugs=("direction-relation",),
        cause_labels=("可能尚未先判断两者共同缩短还是同向消除路程差",),
        principle="相向而行用速度和，同向追及用速度差。",
        worked_contrast="相距300千米、速度40和60时，相向相遇用300÷(40+60)=3小时。",
        return_action="列式前先写一句：两者是在共同接近，还是快者消除领先距离。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="profit-base",
        unit_label="经济利润",
        signature_slug="revenue-denominator",
        signature_label="用售价作利润率分母",
        observable_rule="所选项等于利润除以实际售价，而题目要求相对进价的利润率",
        cause_slugs=("reference-base",),
        cause_labels=("可能尚未固定数量关系中利润率的比较基准为进价",),
        principle="数量关系中的利润率以进价为分母：利润率=(售价-进价)÷进价。",
        worked_contrast="进价100元、售价120元，利润率是20÷100=20%，不是20÷120。",
        return_action="看到利润率先标出进价，再把它放在分母。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="dimension-scale",
        unit_label="几何尺度",
        signature_slug="linear-factor-only",
        signature_label="把线性倍数直接当作面积或体积倍数",
        observable_rule="所选项等于边长缩放倍数，未按面积平方或体积立方处理",
        cause_slugs=("dimension-power",),
        cause_labels=("可能尚未把几何量的维度对应到缩放因子的次数",),
        principle="同尺度缩放时，面积随边长倍数的平方变化，体积随其立方变化。",
        worked_contrast="边长变为1.5倍时，面积变为1.5²=2.25倍。",
        return_action="先判断所求是长度、面积还是体积，再写一次、平方或立方。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="restricted-counting",
        unit_label="排列组合与概率",
        signature_slug="constraint-ignored",
        signature_label="忽略题目对样本空间的限制",
        observable_rule="排列题按无相邻限制全排列，或不放回抽样按有放回模型计算",
        cause_slugs=("sample-space",),
        cause_labels=("可能尚未在计数前按题目限制重建样本空间",),
        principle="先确定哪些结果真正属于题目的样本空间，再进行排列、组合或概率计算。",
        worked_contrast="两人必须相邻时应先捆成一个整体；不放回抽取时每次的总数都会变化。",
        return_action="计算前写清对象是否有顺序、能否重复，以及限制条件如何改变总情况数。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="weighted-mixture",
        unit_label="混合配比",
        signature_slug="equal-halves",
        signature_label="把不同部分按等量混合",
        observable_rule="所选项恒为总量的一半，忽略目标均值对两部分数量比例的约束",
        cause_slugs=("weighted-average",),
        cause_labels=("可能尚未用各部分数量作为平均值或浓度的权重",),
        principle="混合后的浓度或平均值由数量加权；只有目标恰在两端中点时才会各占一半。",
        worked_contrast="10%与30%配成16%，高浓度部分占(16-10)÷(30-10)=30%。",
        return_action="先用目标值分别减两端值，再按交叉差确定数量比例。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="inclusion-exclusion",
        unit_label="集合容斥",
        signature_slug="triple-not-restored",
        signature_label="三集合容斥时漏加三者交集",
        observable_rule="所选项等于三集合数量之和减去三个两两交集，未加回三者交集",
        cause_slugs=("overlap-count",),
        cause_labels=("可能尚未追踪三者交集在两轮加减后的计数次数",),
        principle="三集合并集要减去两两交集，再加回一次三者交集。",
        worked_contrast="三者交集先被三集合相加计3次，又被三个两两交集减3次，因此还需加回1次。",
        return_action="把三者交集的计数次数单独写在式子旁核对。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="remainder-constraints",
        unit_label="整数与余数约束",
        signature_slug="single-congruence",
        signature_label="只检查一个余数条件",
        observable_rule="所选项是超过下界后第一个满足首个余数条件的数，但不满足第二个条件",
        cause_slugs=("constraint-intersection",),
        cause_labels=("可能尚未把多个同余条件视为必须同时满足的交集",),
        principle="余数题的候选数必须同时满足所有条件，逐条成立才可保留。",
        worked_contrast="一个数除以4余1且除以5余2，只满足其中一个条件不能作为答案。",
        return_action="找到候选数后按题目顺序把每个除法余数复核一遍。",
    ),
)


_CONTEXTS = (
    "青岚智造车间",
    "澄川公共维护站",
    "云岑印务中心",
    "星浦水务班组",
    "松屿数据处理组",
    "栖湾农业服务队",
    "远汀交通保障组",
    "禾川社区工坊",
    "望海设备检修组",
    "清岳低碳园区",
)


def _scalar(value: Fraction) -> str:
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    denominator = value.denominator
    reduced = denominator
    while reduced % 2 == 0:
        reduced //= 2
    while reduced % 5 == 0:
        reduced //= 5
    if reduced == 1:
        scale = 1
        places = 0
        while scale % denominator:
            scale *= 10
            places += 1
        scaled = value.numerator * (scale // denominator)
        sign = "-" if scaled < 0 else ""
        absolute = abs(scaled)
        whole, decimal = divmod(absolute, scale)
        fraction = f"{decimal:0{places}d}".rstrip("0")
        return f"{sign}{whole}.{fraction}" if fraction else f"{sign}{whole}"
    return f"{value.numerator}/{value.denominator}"


def _number(value: Fraction, unit: str) -> str:
    return f"{_scalar(value)}{unit}"


def _rounded_decimal(value: Fraction, places: int) -> str:
    value = Fraction(value)
    scale = 10**places
    numerator = abs(value.numerator) * scale
    quotient, remainder = divmod(numerator, value.denominator)
    if remainder * 2 >= value.denominator:
        quotient += 1
    whole, decimal = divmod(quotient, scale)
    sign = "-" if value < 0 else ""
    return f"{sign}{whole}.{decimal:0{places}d}"


def _percent(value: Fraction) -> str:
    percent = Fraction(value) * 100
    denominator = percent.denominator
    reduced = denominator
    while reduced % 2 == 0:
        reduced //= 2
    while reduced % 5 == 0:
        reduced //= 5
    rendered = _scalar(percent) if reduced == 1 else _rounded_decimal(percent, 1)
    return f"{rendered}%"


def _fraction_text(value: Fraction) -> str:
    value = Fraction(value)
    return _scalar(value) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _targeted_choice(question: Mapping[str, Any]) -> str:
    mappings = question["scoring"]["error_option_mappings"]
    matches = [key for key, value in mappings.items() if value.get("signature_id")]
    if len(matches) != 1:
        raise PracticeBankValidationError("quantitative item must expose one targeted distractor")
    return str(question["options"][matches[0]])


def _check_answer(question: Mapping[str, Any], correct: str, targeted: str) -> None:
    if question["scoring"]["canonical_answer"] != correct:
        raise PracticeBankValidationError("quantitative answer does not match recomputation")
    if _targeted_choice(question) != targeted:
        raise PracticeBankValidationError("quantitative diagnostic distractor does not match recomputation")


def _require_payload(payload: Any, adapter: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != {"adapter", *fields}:
        raise PracticeBankValidationError(f"invalid {adapter} verification payload")
    if payload.get("adapter") != adapter:
        raise PracticeBankValidationError(f"unexpected quantitative adapter: {payload.get('adapter')}")
    return payload


def _integer(payload: Mapping[str, Any], field: str) -> int:
    value = payload[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise PracticeBankValidationError(f"quantitative {field} must be an integer")
    return value


def _work_choice(variant: int) -> AuthoredChoice:
    rows = (
        (6, 12, 1, 1),
        (8, 24, 1, 2),
        (10, 15, 1, 1),
        (12, 18, 2, 3),
        (9, 18, 3, 4),
        (14, 21, 1, 2),
        (16, 24, 3, 4),
        (18, 30, 2, 3),
        (20, 30, 1, 1),
        (15, 25, 4, 5),
    )
    solo_a, solo_b, fraction_n, fraction_d = rows[variant]
    target = Fraction(fraction_n, fraction_d)
    rate_a, rate_b = Fraction(1, solo_a), Fraction(1, solo_b)
    correct = target / (rate_a + rate_b)
    targeted = target * (solo_a + solo_b)
    faster_alone = target * min(solo_a, solo_b)
    subtract_rates = target / abs(rate_a - rate_b)
    scope = "全部任务" if target == 1 else f"任务的{_fraction_text(target)}"
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}有一项协作任务，甲单独完成需{solo_a}小时，"
            f"乙单独完成需{solo_b}小时。两人同时工作，完成{scope}需要多长时间？"
        ),
        correct=_number(correct, "小时"),
        targeted_wrong=_number(targeted, "小时"),
        other_wrong=(_number(faster_alone, "小时"), _number(subtract_rates, "小时")),
        explanation=(
            f"甲、乙效率分别为1/{solo_a}和1/{solo_b}，目标工作量为"
            f"{_fraction_text(target)}，所需时间为{_fraction_text(target)}÷"
            f"(1/{solo_a}+1/{solo_b})={_scalar(correct)}小时。"
        ),
        verification={
            "adapter": "qty.work.parallel.v1",
            "solo_a": solo_a,
            "solo_b": solo_b,
            "fraction_n": fraction_n,
            "fraction_d": fraction_d,
        },
    )


def _travel_choice(variant: int) -> AuthoredChoice:
    rows = (
        ("meet", 40, 60, 3),
        ("chase", 72, 48, 4),
        ("meet", 55, 75, 2),
        ("chase", 80, 50, 3),
        ("meet", 45, 70, 4),
        ("chase", 68, 44, 5),
        ("meet", 52, 78, 3),
        ("chase", 90, 54, 2),
        ("meet", 48, 66, 5),
        ("chase", 84, 60, 6),
    )
    mode, speed_a, speed_b, expected_time = rows[variant]
    if mode == "meet":
        distance = (speed_a + speed_b) * expected_time
        correct = Fraction(distance, speed_a + speed_b)
        targeted = Fraction(distance, abs(speed_a - speed_b))
        prompt = (
            f"{_CONTEXTS[variant]}安排两辆巡检车从相距{distance}千米的两地同时相向出发，"
            f"速度分别为{speed_a}千米/小时和{speed_b}千米/小时。几小时后相遇？"
        )
        relation = "相向行驶应使用速度和"
    else:
        fast, slow = max(speed_a, speed_b), min(speed_a, speed_b)
        speed_a, speed_b = fast, slow
        distance = (speed_a - speed_b) * expected_time
        correct = Fraction(distance, speed_a - speed_b)
        targeted = Fraction(distance, speed_a + speed_b)
        prompt = (
            f"{_CONTEXTS[variant]}的一辆快车以{speed_a}千米/小时追赶同向慢车，"
            f"慢车速度为{speed_b}千米/小时且已领先{distance}千米。几小时后追上？"
        )
        relation = "同向追及应使用速度差"
    one_a = Fraction(distance, speed_a)
    one_b = Fraction(distance, speed_b)
    return AuthoredChoice(
        prompt=prompt,
        correct=_number(correct, "小时"),
        targeted_wrong=_number(targeted, "小时"),
        other_wrong=(_number(one_a, "小时"), _number(one_b, "小时")),
        explanation=(
            f"{relation}，因此时间={distance}÷"
            f"{speed_a + speed_b if mode == 'meet' else speed_a - speed_b}="
            f"{_scalar(correct)}小时。"
        ),
        verification={
            "adapter": "qty.travel.relative.v1",
            "mode": mode,
            "speed_a": speed_a,
            "speed_b": speed_b,
            "distance": distance,
        },
    )


def _profit_choice(variant: int) -> AuthoredChoice:
    rows = (
        (800, 50, 80),
        (1200, 25, 90),
        (1000, 40, 75),
        (1600, 30, 85),
        (2000, 20, 90),
        (2400, 50, 70),
        (1500, 60, 80),
        (1800, 25, 75),
        (3200, 40, 80),
        (2500, 30, 95),
    )
    cost, markup_percent, discount_percent = rows[variant]
    list_price = Fraction(cost * (100 + markup_percent), 100)
    sale_price = list_price * Fraction(discount_percent, 100)
    profit = sale_price - cost
    correct = profit / cost
    targeted = profit / sale_price
    ratio_only = sale_price / cost
    reversed_sign = -correct
    discount_text = _scalar(Fraction(discount_percent, 10))
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}购入一件设备的进价为{cost}元，按进价上浮"
            f"{markup_percent}%标价，最终按标价的{discount_text}折售出。"
            "相对进价计算，实际利润率是多少？"
        ),
        correct=_percent(correct),
        targeted_wrong=_percent(targeted),
        other_wrong=(_percent(ratio_only), _percent(reversed_sign)),
        explanation=(
            f"标价为{_scalar(list_price)}元，实际售价为{_scalar(sale_price)}元；"
            f"利润率=({_scalar(sale_price)}-{cost})÷{cost}={_percent(correct)}。"
        ),
        verification={
            "adapter": "qty.profit.discount.v1",
            "cost": cost,
            "markup_percent": markup_percent,
            "discount_percent": discount_percent,
        },
    )


def _geometry_choice(variant: int) -> AuthoredChoice:
    rows = (
        (2, 3, 2),
        (3, 3, 2),
        (2, 5, 2),
        (3, 5, 2),
        (2, 4, 3),
        (3, 4, 3),
        (2, 5, 3),
        (3, 5, 3),
        (2, 7, 4),
        (3, 7, 4),
    )
    power, scale_n, scale_d = rows[variant]
    scale = Fraction(scale_n, scale_d)
    correct = scale**power
    targeted = scale
    if power == 2:
        other_one, other_two = scale**3, 2 * scale
        object_name, measure = "正方形展板", "面积"
    else:
        other_one, other_two = scale**2, 3 * scale
        object_name, measure = "立方体储物箱", "体积"
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}按原设计的{_scalar(scale)}倍等比例放大一件"
            f"{object_name}的全部线性尺寸。放大后的{measure}是原来的多少倍？"
        ),
        correct=_number(correct, "倍"),
        targeted_wrong=_number(targeted, "倍"),
        other_wrong=(_number(other_one, "倍"), _number(other_two, "倍")),
        explanation=(
            f"所求是{measure}，缩放因子应取{power}次方："
            f"({_scalar(scale)})^{power}={_scalar(correct)}倍。"
        ),
        verification={
            "adapter": "qty.geometry.scale.v1",
            "power": power,
            "scale_n": scale_n,
            "scale_d": scale_d,
        },
    )


def _counting_choice(variant: int) -> AuthoredChoice:
    if variant % 2 == 0:
        n = 5 + variant // 2
        correct = 2 * factorial(n - 1)
        targeted = factorial(n)
        no_internal_order = factorial(n - 1)
        pinned_block = 2 * factorial(n - 2)
        return AuthoredChoice(
            prompt=(
                f"{_CONTEXTS[variant]}安排{n}名不同的志愿者排成一列拍照，其中甲、乙必须相邻。"
                "共有多少种不同排法？"
            ),
            correct=str(correct),
            targeted_wrong=str(targeted),
            other_wrong=(str(no_internal_order), str(pinned_block)),
            explanation=(
                f"先把甲、乙捆成一个整体，共有{n - 1}个对象；整体内部有2种顺序，"
                f"所以共有2×({n - 1})!={correct}种。"
            ),
            verification={"adapter": "qty.counting.restricted.v1", "mode": "adjacent", "n": n},
        )
    probability_rows = (
        (10, 4, 2),
        (12, 5, 3),
        (14, 6, 2),
        (15, 5, 3),
        (16, 7, 2),
    )
    n, good, draws = probability_rows[variant // 2]
    bad = n - good
    denominator = comb(n, draws)
    correct = Fraction(denominator - comb(bad, draws), denominator)
    targeted = 1 - Fraction(bad, n) ** draws
    all_good = Fraction(comb(good, draws), denominator)
    exactly_one = Fraction(good * comb(bad, draws - 1), denominator)
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}的抽检箱内有{n}个样本，其中{good}个带有复核标记。"
            f"随机不放回抽取{draws}个，至少抽到1个带标记样本的概率是多少？"
        ),
        correct=_fraction_text(correct),
        targeted_wrong=_fraction_text(targeted),
        other_wrong=(_fraction_text(all_good), _fraction_text(exactly_one)),
        explanation=(
            f"用补集计算：1-C({bad},{draws})/C({n},{draws})={_fraction_text(correct)}。"
            "不放回抽样不能把每次概率视为不变。"
        ),
        verification={
            "adapter": "qty.counting.restricted.v1",
            "mode": "without-replacement",
            "n": n,
            "good": good,
            "draws": draws,
        },
    )


def _mixture_choice(variant: int) -> AuthoredChoice:
    rows = (
        ("solution", 10, 30, 16, 100),
        ("group", 60, 90, 72, 40),
        ("solution", 5, 25, 11, 80),
        ("group", 50, 80, 62, 60),
        ("solution", 12, 32, 20, 75),
        ("group", 55, 85, 67, 50),
        ("solution", 8, 28, 13, 120),
        ("group", 45, 75, 57, 70),
        ("solution", 15, 35, 29, 100),
        ("group", 65, 95, 83, 50),
    )
    mode, low, high, target, total = rows[variant]
    correct = Fraction(total * (target - low), high - low)
    targeted = Fraction(total, 2)
    reversed_parts = total - correct
    wrong_weight = Fraction(total * target, low + high)
    if mode == "solution":
        prompt = (
            f"{_CONTEXTS[variant]}要把浓度{low}%和{high}%的两种溶液配成"
            f"{target}%的溶液{total}克，需要高浓度溶液多少克？"
        )
        unit = "克"
    else:
        prompt = (
            f"{_CONTEXTS[variant]}有成绩均值分别为{low}分和{high}分的两组人员，"
            f"合计{total}人、总平均分为{target}分。高分组有多少人？"
        )
        unit = "人"
    return AuthoredChoice(
        prompt=prompt,
        correct=_number(correct, unit),
        targeted_wrong=_number(targeted, unit),
        other_wrong=(_number(reversed_parts, unit), _number(wrong_weight, unit)),
        explanation=(
            f"高值部分占比=({target}-{low})÷({high}-{low})，"
            f"数量={total}×({target}-{low})÷({high}-{low})={_scalar(correct)}{unit}。"
        ),
        verification={
            "adapter": "qty.mixture.weighted.v1",
            "mode": mode,
            "low": low,
            "high": high,
            "target": target,
            "total": total,
            "unit": unit,
        },
    )


def _inclusion_choice(variant: int) -> AuthoredChoice:
    atoms = {
        "only_a": 7 + variant,
        "only_b": 9 + (2 * variant) % 7,
        "only_c": 6 + (3 * variant) % 8,
        "ab_only": 2 + variant % 4,
        "ac_only": 3 + (variant + 1) % 4,
        "bc_only": 2 + (variant + 2) % 5,
        "abc": 1 + variant % 3,
    }
    a = atoms["only_a"] + atoms["ab_only"] + atoms["ac_only"] + atoms["abc"]
    b = atoms["only_b"] + atoms["ab_only"] + atoms["bc_only"] + atoms["abc"]
    c = atoms["only_c"] + atoms["ac_only"] + atoms["bc_only"] + atoms["abc"]
    ab = atoms["ab_only"] + atoms["abc"]
    ac = atoms["ac_only"] + atoms["abc"]
    bc = atoms["bc_only"] + atoms["abc"]
    abc = atoms["abc"]
    correct = a + b + c - ab - ac - bc + abc
    targeted = a + b + c - ab - ac - bc
    simple_sum = a + b + c
    subtract_triple = targeted - abc
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}统计参加甲、乙、丙三类公益活动的人数，分别为{a}、{b}、{c}人；"
            f"同时参加甲乙、甲丙、乙丙的分别为{ab}、{ac}、{bc}人，三类都参加的有{abc}人。"
            "至少参加一类活动的共有多少人？"
        ),
        correct=f"{correct}人",
        targeted_wrong=f"{targeted}人",
        other_wrong=(f"{simple_sum}人", f"{subtract_triple}人"),
        explanation=(
            f"三集合并集={a}+{b}+{c}-{ab}-{ac}-{bc}+{abc}={correct}人。"
        ),
        verification={"adapter": "qty.set.inclusion.v1", **atoms},
    )


def _next_matching(lower: int, moduli: tuple[int, ...], residues: tuple[int, ...]) -> int:
    if (
        len(moduli) != len(residues)
        or not moduli
        or any(modulus <= 1 or modulus > 10_000 for modulus in moduli)
        or any(not 0 <= residue < modulus for modulus, residue in zip(moduli, residues, strict=True))
    ):
        raise PracticeBankValidationError("remainder constraints are outside supported bounds")
    for left in range(len(moduli)):
        for right in range(left + 1, len(moduli)):
            if (residues[left] - residues[right]) % gcd(moduli[left], moduli[right]):
                raise PracticeBankValidationError(
                    "remainder constraints have no simultaneous solution"
                )
    cycle = lcm(*moduli)
    if cycle > 1_000_000:
        raise PracticeBankValidationError("remainder constraint cycle is too large to verify")
    for candidate in range(lower + 1, lower + cycle + 1):
        if all(
            candidate % modulus == residue
            for modulus, residue in zip(moduli, residues, strict=True)
        ):
            return candidate
    raise PracticeBankValidationError("remainder constraints have no simultaneous solution")


def _remainder_choice(variant: int) -> AuthoredChoice:
    rows = (
        (4, 5, 83),
        (5, 7, 121),
        (7, 8, 174),
        (8, 9, 205),
        (5, 11, 247),
        (7, 9, 286),
        (8, 11, 315),
        (9, 11, 352),
        (7, 10, 403),
        (11, 12, 455),
    )
    modulus_a, modulus_b, lower = rows[variant]
    residue_a, residue_b = lower % modulus_a, lower % modulus_b
    correct = _next_matching(lower, (modulus_a, modulus_b), (residue_a, residue_b))
    targeted = _next_matching(lower, (modulus_a,), (residue_a,))
    second_only = _next_matching(lower, (modulus_b,), (residue_b,))
    skipped_cycle = correct + modulus_a * modulus_b
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}有一批编号物资，数量大于{lower}；"
            f"按每组{modulus_a}件分余{residue_a}件，按每组{modulus_b}件分余{residue_b}件。"
            "这批物资最少有多少件？"
        ),
        correct=f"{correct}件",
        targeted_wrong=f"{targeted}件",
        other_wrong=(f"{second_only}件", f"{skipped_cycle}件"),
        explanation=(
            f"从{lower + 1}起同时检验两个余数条件，第一个同时满足的数是{correct}。"
        ),
        verification={
            "adapter": "qty.remainder.constraints.v1",
            "lower": lower,
            "modulus_a": modulus_a,
            "residue_a": residue_a,
            "modulus_b": modulus_b,
            "residue_b": residue_b,
        },
    )


_AUTHORS = (
    _work_choice,
    _travel_choice,
    _profit_choice,
    _geometry_choice,
    _counting_choice,
    _mixture_choice,
    _inclusion_choice,
    _remainder_choice,
)


def verify_quantitative_question(question: Mapping[str, Any]) -> None:
    verify_common_question(question)
    if question["module_id"] != MODULE_SCOPES[MODULE_SLUG]:
        raise PracticeBankValidationError("quantitative verifier received another module")
    payload = question["verification"]
    adapter = payload.get("adapter") if isinstance(payload, Mapping) else None

    if adapter == "qty.work.parallel.v1":
        item = _require_payload(payload, adapter, {"solo_a", "solo_b", "fraction_n", "fraction_d"})
        solo_a, solo_b = _integer(item, "solo_a"), _integer(item, "solo_b")
        fraction_n, fraction_d = _integer(item, "fraction_n"), _integer(item, "fraction_d")
        if solo_a <= 0 or solo_b <= 0 or not 0 < fraction_n <= fraction_d:
            raise PracticeBankValidationError("parallel-work values must be positive and bounded")
        fraction = Fraction(fraction_n, fraction_d)
        rate_a = Fraction(1, solo_a)
        rate_b = Fraction(1, solo_b)
        correct = _number(fraction / (rate_a + rate_b), "小时")
        targeted = _number(fraction * (solo_a + solo_b), "小时")
    elif adapter == "qty.travel.relative.v1":
        item = _require_payload(payload, adapter, {"mode", "speed_a", "speed_b", "distance"})
        speed_a, speed_b, distance = (
            _integer(item, "speed_a"),
            _integer(item, "speed_b"),
            _integer(item, "distance"),
        )
        if speed_a <= 0 or speed_b <= 0 or distance <= 0:
            raise PracticeBankValidationError("relative-travel values must be positive")
        if item["mode"] == "meet":
            if speed_a == speed_b:
                raise PracticeBankValidationError("meeting diagnostic requires distinct speeds")
            correct = _number(Fraction(distance, speed_a + speed_b), "小时")
            targeted = _number(Fraction(distance, abs(speed_a - speed_b)), "小时")
        elif item["mode"] == "chase":
            if speed_a <= speed_b:
                raise PracticeBankValidationError("chasing requires the first speed to be greater")
            correct = _number(Fraction(distance, speed_a - speed_b), "小时")
            targeted = _number(Fraction(distance, speed_a + speed_b), "小时")
        else:
            raise PracticeBankValidationError("unknown relative-travel mode")
    elif adapter == "qty.profit.discount.v1":
        item = _require_payload(payload, adapter, {"cost", "markup_percent", "discount_percent"})
        cost = _integer(item, "cost")
        markup_percent = _integer(item, "markup_percent")
        discount_percent = _integer(item, "discount_percent")
        if cost <= 0 or markup_percent <= -100 or not 0 < discount_percent <= 100:
            raise PracticeBankValidationError("profit fixture values are outside supported bounds")
        sale = Fraction(cost * (100 + markup_percent) * discount_percent, 10_000)
        profit = sale - cost
        correct, targeted = _percent(profit / cost), _percent(profit / sale)
    elif adapter == "qty.geometry.scale.v1":
        item = _require_payload(payload, adapter, {"power", "scale_n", "scale_d"})
        power = _integer(item, "power")
        scale_n, scale_d = _integer(item, "scale_n"), _integer(item, "scale_d")
        if power not in {2, 3} or scale_n <= 0 or scale_d <= 0:
            raise PracticeBankValidationError("geometry scale values are invalid")
        scale = Fraction(scale_n, scale_d)
        correct = _number(scale ** power, "倍")
        targeted = _number(scale, "倍")
    elif adapter == "qty.counting.restricted.v1":
        if not isinstance(payload, Mapping) or payload.get("mode") not in {"adjacent", "without-replacement"}:
            raise PracticeBankValidationError("invalid restricted-counting mode")
        if payload["mode"] == "adjacent":
            item = _require_payload(payload, adapter, {"mode", "n"})
            n = _integer(item, "n")
            if n < 2 or n > 100:
                raise PracticeBankValidationError("adjacent-counting n is outside supported bounds")
            correct, targeted = str(2 * factorial(n - 1)), str(factorial(n))
        else:
            item = _require_payload(payload, adapter, {"mode", "n", "good", "draws"})
            n, good, draws = (
                _integer(item, "n"),
                _integer(item, "good"),
                _integer(item, "draws"),
            )
            if not 0 < good < n <= 10_000 or not 1 <= draws <= n:
                raise PracticeBankValidationError("sampling values are outside supported bounds")
            bad, denominator = n - good, comb(n, draws)
            correct = _fraction_text(Fraction(denominator - comb(bad, draws), denominator))
            targeted = _fraction_text(1 - Fraction(bad, n) ** draws)
    elif adapter == "qty.mixture.weighted.v1":
        item = _require_payload(payload, adapter, {"mode", "low", "high", "target", "total", "unit"})
        low, high, target, total = (
            _integer(item, key) for key in ("low", "high", "target", "total")
        )
        if item["mode"] not in {"solution", "group"} or not low < target < high or total <= 0:
            raise PracticeBankValidationError("weighted-mixture values are invalid")
        if not isinstance(item["unit"], str) or not item["unit"].strip():
            raise PracticeBankValidationError("weighted-mixture unit is invalid")
        correct = _number(Fraction(total * (target - low), high - low), str(item["unit"]))
        targeted = _number(Fraction(total, 2), str(item["unit"]))
    elif adapter == "qty.set.inclusion.v1":
        atom_fields = {"only_a", "only_b", "only_c", "ab_only", "ac_only", "bc_only", "abc"}
        item = _require_payload(payload, adapter, atom_fields)
        values = {key: _integer(item, key) for key in atom_fields}
        if any(value < 0 for value in values.values()) or values["abc"] <= 0:
            raise PracticeBankValidationError("set atoms must be non-negative with a triple overlap")
        a = values["only_a"] + values["ab_only"] + values["ac_only"] + values["abc"]
        b = values["only_b"] + values["ab_only"] + values["bc_only"] + values["abc"]
        c = values["only_c"] + values["ac_only"] + values["bc_only"] + values["abc"]
        ab, ac, bc = (
            values["ab_only"] + values["abc"],
            values["ac_only"] + values["abc"],
            values["bc_only"] + values["abc"],
        )
        correct = f"{a + b + c - ab - ac - bc + values['abc']}人"
        targeted = f"{a + b + c - ab - ac - bc}人"
    elif adapter == "qty.remainder.constraints.v1":
        fields = {"lower", "modulus_a", "residue_a", "modulus_b", "residue_b"}
        item = _require_payload(payload, adapter, fields)
        lower = _integer(item, "lower")
        moduli = (_integer(item, "modulus_a"), _integer(item, "modulus_b"))
        residues = (_integer(item, "residue_a"), _integer(item, "residue_b"))
        if lower < 0:
            raise PracticeBankValidationError("remainder lower bound cannot be negative")
        correct = f"{_next_matching(lower, moduli, residues)}件"
        targeted = f"{_next_matching(lower, (moduli[0],), (residues[0],))}件"
    else:
        raise PracticeBankValidationError(f"unknown quantitative verification adapter: {adapter}")
    _check_answer(question, correct, targeted)


def generate_quantitative_bank() -> tuple[tuple[UnitSpec, ...], tuple[dict[str, Any], ...]]:
    questions: list[dict[str, Any]] = []
    for local_index, (unit_index, variant) in enumerate(schedule_pairs(len(UNITS))):
        authored = _AUTHORS[unit_index](variant)
        questions.append(
            build_question(
                UNITS[unit_index],
                local_index=local_index,
                variant=variant,
                authored=authored,
            )
        )
    validate_generated_module(MODULE_SLUG, UNITS, questions, verify_quantitative_question)
    return UNITS, tuple(questions)


__all__ = ["UNITS", "generate_quantitative_bank", "verify_quantitative_question"]
