from __future__ import annotations

from fractions import Fraction
from typing import Any, Mapping, Sequence

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


MODULE_SLUG = "data-analysis"


UNITS: tuple[UnitSpec, ...] = (
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="direct-growth",
        unit_label="直接增长率",
        signature_slug="current-denominator",
        signature_label="用现期量作增长率分母",
        observable_rule="所选项等于现期与基期之差除以现期量",
        cause_slugs=("comparison-start",),
        cause_labels=("可能尚未把变化发生前的基期量固定为比较起点",),
        principle="增长率描述变化相对起点有多大，因此分母是基期量。",
        worked_contrast="某指标由400增至460，增长率是60÷400=15%，不是60÷460。",
        return_action="先圈出变化前的数，再把它放到分母。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="percentage-points",
        unit_label="百分点与增速方向",
        signature_slug="direction-reversed",
        signature_label="反推上期增速时加减方向写反",
        observable_rule="提高时继续加百分点，或回落时继续减百分点",
        cause_slugs=("temporal-direction",),
        cause_labels=("可能尚未从本期沿变化方向反推上期",),
        principle="本期比上期提高就用本期减提高值；本期比上期回落就用本期加回落值。",
        worked_contrast="本期18%，比上期提高5个百分点，则上期为18%-5%=13%。",
        return_action="在时间轴上画出“上期→本期”的增减箭头，再逆向计算。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="growth-amount",
        unit_label="增长量",
        signature_slug="current-times-rate",
        signature_label="直接用现期量乘增长率",
        observable_rule="所选项等于现期量乘增长率，未先还原基期量",
        cause_slugs=("rate-applies-to-base",),
        cause_labels=("可能尚未注意增长率作用在基期量而非现期量上",),
        principle="已知现期量和增长率时，增长量=现期量×增长率÷(1+增长率)。",
        worked_contrast="现期460、增长15%，基期为400，增长量是60而非460×15%=69。",
        return_action="看到“现期量+增长率求增长量”时先写分母1+r。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="growth-comparison",
        unit_label="增长率比较",
        signature_slug="amount-instead-of-rate",
        signature_label="用增长量大小代替增长率比较",
        observable_rule="所选类别的绝对增长量最大，但相对基期的增长率并非最大",
        cause_slugs=("absolute-relative",),
        cause_labels=("可能尚未区分绝对变化量与相对变化率",),
        principle="比较增长率要比较(现期-基期)÷基期，规模大不等于增速快。",
        worked_contrast="增加300但基数为1000的增速是30%；增加50但基数为100的增速是50%。",
        return_action="先为每个候选写出“变化量/基期量”，再比较。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="part-whole",
        unit_label="现期比重与贡献率",
        signature_slug="whole-over-part",
        signature_label="把总体除以部分",
        observable_rule="所选项等于总体量除以部分量，而问题要求部分占总体的比重",
        cause_slugs=("ratio-orientation",),
        cause_labels=("可能尚未从“谁占谁”确定分子和分母",),
        principle="部分占总体的比重=部分÷总体；增长贡献率则是部分增长量÷总体增长量。",
        worked_contrast="线上办理240件、总量800件，占比是240÷800=30%。",
        return_action="把“占”前对象写在分子，“占”后对象写在分母。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="base-share",
        unit_label="基期与两期比重",
        signature_slug="factor-reversed",
        signature_label="基期比重调整因子写反",
        observable_rule="所选项用(1+部分增速)/(1+总体增速)调整现期比重",
        cause_slugs=("base-adjustment",),
        cause_labels=("可能尚未分别还原部分量和总体量后再相除",),
        principle="基期比重=现期比重×(1+总体增速)÷(1+部分增速)。",
        worked_contrast="部分增长20%、总体增长10%时，基期比重要用现期比重乘1.10÷1.20。",
        return_action="分别写出部分÷(1+a)与总体÷(1+b)，再化简调整因子。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="average-relations",
        unit_label="平均数关系",
        signature_slug="roles-reversed",
        signature_label="平均数的分子与分母角色写反",
        observable_rule="现期平均数倒置，或基期/两期平均数公式中交换分子与分母增速",
        cause_slugs=("numerator-denominator",),
        cause_labels=("可能尚未先确定平均数由哪一总量除以哪一个数",),
        principle="先写平均数=总量÷个数；跨期时分子和分母分别按各自增速还原。",
        worked_contrast="总量增长50%、个数增长20%，平均数增速=(50%-20%)÷1.20=25%。",
        return_action="先给分子增速标a、分母增速标b，再代入对应位置。",
    ),
    UnitSpec(
        module_slug=MODULE_SLUG,
        unit_slug="multiple-ratio",
        unit_label="倍数与比值",
        signature_slug="minus-one-missing",
        signature_label="把“是几倍”当成“多几倍”",
        observable_rule="问题问A比B多几倍时，所选项等于A÷B，未减去原有的1倍",
        cause_slugs=("is-versus-more",),
        cause_labels=("可能尚未区分总倍数与超出部分的倍数",),
        principle="A是B的几倍用A÷B；A比B多几倍要在结果上减1。",
        worked_contrast="A为600、B为200，A是B的3倍，但A比B多2倍。",
        return_action="圈出题干中的“是”或“多”，看到“多”就检查是否减1。",
    ),
)


_CONTEXTS = (
    "青岚市公共阅读服务",
    "澄川清洁能源项目",
    "云岑城乡物流网络",
    "星浦农业设施计划",
    "松屿基层健康服务",
    "栖湾社区教育项目",
    "远汀生态巡护工程",
    "禾川数字政务平台",
    "望海公共交通系统",
    "清岳文化场馆计划",
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


def _targeted_choice(question: Mapping[str, Any]) -> str:
    mappings = question["scoring"]["error_option_mappings"]
    matches = [key for key, value in mappings.items() if value.get("signature_id")]
    if len(matches) != 1:
        raise PracticeBankValidationError("data-analysis item must expose one targeted distractor")
    return str(question["options"][matches[0]])


def _check_answer(question: Mapping[str, Any], correct: str, targeted: str) -> None:
    if question["scoring"]["canonical_answer"] != correct:
        raise PracticeBankValidationError("data-analysis answer does not match recomputation")
    if _targeted_choice(question) != targeted:
        raise PracticeBankValidationError("data-analysis distractor does not match recomputation")


def _require_payload(payload: Any, adapter: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != {"adapter", *fields}:
        raise PracticeBankValidationError(f"invalid {adapter} verification payload")
    if payload.get("adapter") != adapter:
        raise PracticeBankValidationError(f"unexpected data-analysis adapter: {payload.get('adapter')}")
    return payload


def _integer(payload: Mapping[str, Any], field: str) -> int:
    value = payload[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise PracticeBankValidationError(f"data-analysis {field} must be an integer")
    return value


def _direct_growth_choice(variant: int) -> AuthoredChoice:
    rows = (
        (400, 3, 20),
        (750, -1, 5),
        (960, 1, 4),
        (1500, -1, 10),
        (800, 1, 8),
        (1200, 2, 5),
        (1800, -3, 20),
        (640, 3, 8),
        (2500, -1, 4),
        (1600, 7, 20),
    )
    base, rate_n, rate_d = rows[variant]
    rate = Fraction(rate_n, rate_d)
    current = Fraction(base) * (1 + rate)
    if current.denominator != 1:
        raise AssertionError("direct-growth fixtures must produce integer current values")
    current_int = current.numerator
    correct = Fraction(current_int - base, base)
    targeted = Fraction(current_int - base, current_int)
    ratio_only = Fraction(current_int, base)
    reversed_direction = -correct
    direction = "增加" if current_int > base else "下降"
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}的一项年度指标由{base}单位{direction}到{current_int}单位，"
            "该指标的增长率是多少？"
        ),
        correct=_percent(correct),
        targeted_wrong=_percent(targeted),
        other_wrong=(_percent(ratio_only), _percent(reversed_direction)),
        explanation=(
            f"增长率=({current_int}-{base})÷{base}={_percent(correct)}，"
            f"分母是变化前的{base}。"
        ),
        verification={"adapter": "data.growth.direct.v1", "base": base, "current": current_int},
    )


def _percentage_points_choice(variant: int) -> AuthoredChoice:
    rows = (
        (18, 5),
        (12, -4),
        (25, 7),
        (9, -3),
        (36, 8),
        (15, -5),
        (28, 6),
        (7, -2),
        (42, 10),
        (21, -6),
    )
    current_percent, change_pp = rows[variant]
    current = Fraction(current_percent, 100)
    change = Fraction(change_pp, 100)
    correct = current - change
    targeted = current + change
    relative_percent = current * (1 - change)
    delta_only = abs(change)
    word = "提高" if change_pp > 0 else "回落"
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}本期某项指标增速为{current_percent}%，比上期{word}"
            f"{abs(change_pp)}个百分点。上期增速是多少？"
        ),
        correct=_percent(correct),
        targeted_wrong=_percent(targeted),
        other_wrong=(_percent(relative_percent), _percent(delta_only)),
        explanation=(
            f"本期相对上期{word}{abs(change_pp)}个百分点，反推上期应为"
            f"{current_percent}%{'-' if change_pp > 0 else '+'}{abs(change_pp)}%="
            f"{_percent(correct)}。"
        ),
        verification={
            "adapter": "data.percentage-points.v1",
            "current_percent": current_percent,
            "change_pp": change_pp,
        },
    )


def _growth_amount_choice(variant: int) -> AuthoredChoice:
    rows = (
        (400, 3, 20),
        (600, 1, 5),
        (960, 1, 4),
        (1200, 1, 10),
        (800, 1, 8),
        (1500, 2, 5),
        (1800, 3, 20),
        (640, 3, 8),
        (2400, 1, 4),
        (1600, 7, 20),
    )
    base, rate_n, rate_d = rows[variant]
    rate = Fraction(rate_n, rate_d)
    current = Fraction(base) * (1 + rate)
    if current.denominator != 1:
        raise AssertionError("growth-amount fixtures must produce integer current values")
    current_int = current.numerator
    correct = Fraction(current_int) * rate / (1 + rate)
    targeted = Fraction(current_int) * rate
    recovered_base = Fraction(current_int) / (1 + rate)
    linear_subtraction = Fraction(current_int) * (1 - rate)
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}本期某项服务量为{current_int}单位，同比增长"
            f"{_percent(rate)}。与上期相比增长了多少单位？"
        ),
        correct=_number(correct, "单位"),
        targeted_wrong=_number(targeted, "单位"),
        other_wrong=(_number(recovered_base, "单位"), _number(linear_subtraction, "单位")),
        explanation=(
            f"增长量=现期量×r÷(1+r)={current_int}×{_percent(rate)}÷"
            f"(1+{_percent(rate)})={_scalar(correct)}单位。"
        ),
        verification={
            "adapter": "data.growth.amount.v1",
            "current": current_int,
            "rate_n": rate_n,
            "rate_d": rate_d,
        },
    )


def _growth_comparison_choice(variant: int) -> AuthoredChoice:
    scale = variant + 1
    role_rows = (
        (100 * scale, 150 * scale),
        (1000 * scale, 1300 * scale),
        (1500 * scale, 1650 * scale),
        (2000 * scale, 1400 * scale),
    )
    labels = ("甲类项目", "乙类项目", "丙类项目", "丁类项目")
    shift = variant % 4
    rows: list[dict[str, Any]] = []
    for role_index, (base, current) in enumerate(role_rows):
        label = labels[(role_index + shift) % 4]
        rows.append({"label": label, "base": base, "current": current})
    correct_row = max(rows, key=lambda item: Fraction(item["current"] - item["base"], item["base"]))
    targeted_row = max(rows, key=lambda item: item["current"] - item["base"])
    current_row = max(rows, key=lambda item: item["current"])
    base_row = max(rows, key=lambda item: item["base"])
    table = "；".join(
        f"{item['label']}为{item['base']}→{item['current']}" for item in rows
    )
    return AuthoredChoice(
        prompt=f"{_CONTEXTS[variant]}公布四类指标的上期值→本期值：{table}。哪一类增长率最大？",
        correct=str(correct_row["label"]),
        targeted_wrong=str(targeted_row["label"]),
        other_wrong=(str(current_row["label"]), str(base_row["label"])),
        explanation=(
            "分别比较(本期-上期)÷上期：甲、乙、丙、丁四个角色数据的增速依次为"
            "50%、30%、10%和-30%，所以应选择50%对应的类别。"
        ),
        verification={"adapter": "data.growth.compare.v1", "rows": rows},
    )


def _part_whole_choice(variant: int) -> AuthoredChoice:
    rows = (
        (240, 800),
        (180, 900),
        (350, 1000),
        (420, 1200),
        (270, 1500),
        (560, 1600),
        (375, 1250),
        (630, 1800),
        (480, 2000),
        (825, 2500),
    )
    part, whole = rows[variant]
    correct = Fraction(part, whole)
    targeted = Fraction(whole, part)
    complement = Fraction(whole - part, whole)
    part_over_remainder = Fraction(part, whole - part)
    if variant % 2 == 0:
        prompt = (
            f"{_CONTEXTS[variant]}本期共完成{whole}项服务，其中线上完成{part}项。"
            "线上服务占全部服务的比重是多少？"
        )
        explanation_subject = "现期比重"
    else:
        prompt = (
            f"{_CONTEXTS[variant]}本期总服务量比上期增加{whole}单位，其中重点项目增加"
            f"{part}单位。重点项目对总增长的贡献率是多少？"
        )
        explanation_subject = "增长贡献率"
    return AuthoredChoice(
        prompt=prompt,
        correct=_percent(correct),
        targeted_wrong=_percent(targeted),
        other_wrong=(_percent(complement), _percent(part_over_remainder)),
        explanation=f"{explanation_subject}=部分÷总体={part}÷{whole}={_percent(correct)}。",
        verification={
            "adapter": "data.ratio.part-whole.v1",
            "part": part,
            "whole": whole,
        },
    )


def _base_share_choice(variant: int) -> AuthoredChoice:
    rows = (
        (200, 1000, 20, 10),
        (300, 1200, -10, 20),
        (450, 1500, 10, -10),
        (320, 1600, 25, 10),
        (600, 2400, -20, -10),
        (500, 2000, 30, 20),
        (280, 1400, 50, 25),
        (720, 3000, -25, 10),
        (800, 4000, 15, -5),
        (360, 1800, 40, 20),
    )
    base_part, base_total, part_rate_percent, total_rate_percent = rows[variant]
    part_rate = Fraction(part_rate_percent, 100)
    total_rate = Fraction(total_rate_percent, 100)
    current_part = Fraction(base_part) * (1 + part_rate)
    current_total = Fraction(base_total) * (1 + total_rate)
    if current_part.denominator != 1 or current_total.denominator != 1:
        raise AssertionError("base-share fixtures must produce integer current values")
    current_part_int, current_total_int = current_part.numerator, current_total.numerator
    current_share = Fraction(current_part_int, current_total_int)
    correct = current_share * (1 + total_rate) / (1 + part_rate)
    targeted = current_share * (1 + part_rate) / (1 + total_rate)
    approximate_factor = current_share * (1 + total_rate - part_rate)
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}本期重点项目量为{current_part_int}，同比"
            f"{'增长' if part_rate_percent >= 0 else '下降'}{abs(part_rate_percent)}%；"
            f"总量为{current_total_int}，同比{'增长' if total_rate_percent >= 0 else '下降'}"
            f"{abs(total_rate_percent)}%。上期重点项目占总量的比重是多少？"
        ),
        correct=_percent(correct),
        targeted_wrong=_percent(targeted),
        other_wrong=(_percent(current_share), _percent(approximate_factor)),
        explanation=(
            f"基期比重=({current_part_int}/{current_total_int})×"
            f"(1+{total_rate_percent}%)÷(1+{part_rate_percent}%)={_percent(correct)}。"
        ),
        verification={
            "adapter": "data.share.base.v1",
            "current_part": current_part_int,
            "current_total": current_total_int,
            "part_rate_percent": part_rate_percent,
            "total_rate_percent": total_rate_percent,
        },
    )


def _average_choice(variant: int) -> AuthoredChoice:
    if variant in {0, 3, 6, 9}:
        rows = {
            0: (1200, 30),
            3: (2340, 36),
            6: (3150, 45),
            9: (4480, 56),
        }
        total, count = rows[variant]
        correct = Fraction(total, count)
        targeted = Fraction(count, total)
        per_month = Fraction(total, count * 12)
        annualized = Fraction(total * 12, count)
        return AuthoredChoice(
            prompt=(
                f"{_CONTEXTS[variant]}本期{count}个服务点合计完成{total}人次服务，"
                "平均每个服务点完成多少人次？"
            ),
            correct=_number(correct, "人次"),
            targeted_wrong=_number(targeted, "人次"),
            other_wrong=(_number(per_month, "人次"), _number(annualized, "人次")),
            explanation=f"平均数=总量÷个数={total}÷{count}={_scalar(correct)}人次。",
            verification={
                "adapter": "data.average.relations.v1",
                "mode": "current",
                "total": total,
                "count": count,
                "unit": "人次",
            },
        )
    if variant in {1, 4, 7}:
        rows = {
            1: (1000, 20, 20, 10),
            4: (1800, 30, -10, 20),
            7: (2400, 40, 25, -10),
        }
        base_total, base_count, total_rate_percent, count_rate_percent = rows[variant]
        total_rate = Fraction(total_rate_percent, 100)
        count_rate = Fraction(count_rate_percent, 100)
        current_total = Fraction(base_total) * (1 + total_rate)
        current_count = Fraction(base_count) * (1 + count_rate)
        if current_total.denominator != 1 or current_count.denominator != 1:
            raise AssertionError("base-average fixtures must produce integers")
        current_total_int, current_count_int = current_total.numerator, current_count.numerator
        current_average = Fraction(current_total_int, current_count_int)
        correct = current_average * (1 + count_rate) / (1 + total_rate)
        targeted = current_average * (1 + total_rate) / (1 + count_rate)
        linear_factor = current_average * (1 + count_rate - total_rate)
        return AuthoredChoice(
            prompt=(
                f"{_CONTEXTS[variant]}本期服务总量为{current_total_int}，同比"
                f"{'增长' if total_rate_percent >= 0 else '下降'}{abs(total_rate_percent)}%；"
                f"服务点数量为{current_count_int}，同比"
                f"{'增长' if count_rate_percent >= 0 else '下降'}{abs(count_rate_percent)}%。"
                "上期平均每个服务点的服务量是多少？"
            ),
            correct=_number(correct, "单位"),
            targeted_wrong=_number(targeted, "单位"),
            other_wrong=(_number(current_average, "单位"), _number(linear_factor, "单位")),
            explanation=(
                f"基期平均数=({current_total_int}/{current_count_int})×"
                f"(1+{count_rate_percent}%)÷(1+{total_rate_percent}%)={_scalar(correct)}单位。"
            ),
            verification={
                "adapter": "data.average.relations.v1",
                "mode": "base",
                "current_total": current_total_int,
                "current_count": current_count_int,
                "total_rate_percent": total_rate_percent,
                "count_rate_percent": count_rate_percent,
                "unit": "单位",
            },
        )
    growth_rows = {
        2: (50, 20),
        5: (25, -20),
        8: (0, 25),
    }
    total_rate_percent, count_rate_percent = growth_rows[variant]
    total_rate = Fraction(total_rate_percent, 100)
    count_rate = Fraction(count_rate_percent, 100)
    correct = (total_rate - count_rate) / (1 + count_rate)
    targeted = (count_rate - total_rate) / (1 + total_rate)
    direct_difference = total_rate - count_rate
    return AuthoredChoice(
        prompt=(
            f"{_CONTEXTS[variant]}本期服务总量同比"
            f"{'增长' if total_rate_percent >= 0 else '下降'}{abs(total_rate_percent)}%，"
            f"服务点数量同比{'增长' if count_rate_percent >= 0 else '下降'}"
            f"{abs(count_rate_percent)}%。平均每个服务点的服务量同比变化多少？"
        ),
        correct=_percent(correct),
        targeted_wrong=_percent(targeted),
        other_wrong=(_percent(direct_difference), _percent(total_rate)),
        explanation=(
            f"平均数增速=({total_rate_percent}%-{count_rate_percent}%)÷"
            f"(1+{count_rate_percent}%)={_percent(correct)}。"
        ),
        verification={
            "adapter": "data.average.relations.v1",
            "mode": "growth",
            "total_rate_percent": total_rate_percent,
            "count_rate_percent": count_rate_percent,
        },
    )


def _multiple_choice(variant: int) -> AuthoredChoice:
    if variant % 2 == 0:
        rows = {
            0: (600, 200),
            2: (840, 280),
            4: (900, 360),
            6: (1120, 320),
            8: (1350, 450),
        }
        value_a, value_b = rows[variant]
        ratio = Fraction(value_a, value_b)
        correct = ratio - 1
        targeted = ratio
        part_of_a = Fraction(value_a - value_b, value_a)
        inverse = Fraction(value_b, value_a)
        prompt = (
            f"{_CONTEXTS[variant]}本期甲类指标为{value_a}，乙类指标为{value_b}。"
            "甲类比乙类多几倍？"
        )
        verification = {
            "adapter": "data.multiple.more.v1",
            "mode": "current",
            "value_a": value_a,
            "value_b": value_b,
        }
        explanation = f"甲是乙的{_scalar(ratio)}倍，因此甲比乙多{_scalar(correct)}倍。"
    else:
        rows = {
            1: (600, 200, 20, 50),
            3: (800, 320, 25, 0),
            5: (1050, 350, -20, 20),
            7: (1260, 420, 10, -10),
            9: (1500, 500, 30, 20),
        }
        base_a, base_b, rate_a_percent, rate_b_percent = rows[variant]
        current_a = Fraction(base_a) * (1 + Fraction(rate_a_percent, 100))
        current_b = Fraction(base_b) * (1 + Fraction(rate_b_percent, 100))
        if current_a.denominator != 1 or current_b.denominator != 1:
            raise AssertionError("base-multiple fixtures must produce integer values")
        value_a, value_b = current_a.numerator, current_b.numerator
        base_ratio = Fraction(value_a, value_b) * Fraction(100 + rate_b_percent, 100 + rate_a_percent)
        correct = base_ratio - 1
        targeted = base_ratio
        current_more = Fraction(value_a, value_b) - 1
        inverse = 1 / base_ratio
        prompt = (
            f"{_CONTEXTS[variant]}本期甲类指标为{value_a}、同比"
            f"{'增长' if rate_a_percent >= 0 else '下降'}{abs(rate_a_percent)}%；"
            f"乙类指标为{value_b}、同比{'增长' if rate_b_percent >= 0 else '下降'}"
            f"{abs(rate_b_percent)}%。上期甲类比乙类多几倍？"
        )
        verification = {
            "adapter": "data.multiple.more.v1",
            "mode": "base",
            "value_a": value_a,
            "value_b": value_b,
            "rate_a_percent": rate_a_percent,
            "rate_b_percent": rate_b_percent,
        }
        explanation = (
            f"上期倍数=({value_a}/{value_b})×(1+{rate_b_percent}%)÷"
            f"(1+{rate_a_percent}%)={_scalar(base_ratio)}；问多几倍还要减1，"
            f"得到{_scalar(correct)}倍。"
        )
    return AuthoredChoice(
        prompt=prompt,
        correct=_number(correct, "倍"),
        targeted_wrong=_number(targeted, "倍"),
        other_wrong=(_number(current_more if variant % 2 else part_of_a, "倍"), _number(inverse, "倍")),
        explanation=explanation,
        verification=verification,
    )


_AUTHORS = (
    _direct_growth_choice,
    _percentage_points_choice,
    _growth_amount_choice,
    _growth_comparison_choice,
    _part_whole_choice,
    _base_share_choice,
    _average_choice,
    _multiple_choice,
)


def _comparison_answers(rows: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    if len(rows) != 4:
        raise PracticeBankValidationError("growth comparison requires four rows")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {"label", "base", "current"}:
            raise PracticeBankValidationError("growth comparison row is malformed")
        if (
            not isinstance(row["base"], int)
            or isinstance(row["base"], bool)
            or not isinstance(row["current"], int)
            or isinstance(row["current"], bool)
        ):
            raise PracticeBankValidationError("growth comparison values must be integers")
        base, current = row["base"], row["current"]
        if base <= 0 or current < 0:
            raise PracticeBankValidationError("growth comparison values must be non-negative with positive bases")
        normalized.append({"label": str(row["label"]), "base": base, "current": current})
    labels = [item["label"] for item in normalized]
    if any(not label.strip() for label in labels) or len(labels) != len(set(labels)):
        raise PracticeBankValidationError("growth comparison labels must be unique")
    rates = [Fraction(item["current"] - item["base"], item["base"]) for item in normalized]
    amounts = [item["current"] - item["base"] for item in normalized]
    if rates.count(max(rates)) != 1 or amounts.count(max(amounts)) != 1:
        raise PracticeBankValidationError("growth comparison winners must be unique")
    rate_winner = normalized[rates.index(max(rates))]
    amount_winner = normalized[amounts.index(max(amounts))]
    if rate_winner["label"] == amount_winner["label"]:
        raise PracticeBankValidationError(
            "growth comparison needs a distinct amount-based diagnostic distractor"
        )
    return str(rate_winner["label"]), str(amount_winner["label"])


def verify_data_analysis_question(question: Mapping[str, Any]) -> None:
    verify_common_question(question)
    if question["module_id"] != MODULE_SCOPES[MODULE_SLUG]:
        raise PracticeBankValidationError("data-analysis verifier received another module")
    payload = question["verification"]
    adapter = payload.get("adapter") if isinstance(payload, Mapping) else None

    if adapter == "data.growth.direct.v1":
        item = _require_payload(payload, adapter, {"base", "current"})
        base, current = _integer(item, "base"), _integer(item, "current")
        if base <= 0 or current <= 0 or base == current:
            raise PracticeBankValidationError("direct-growth values must be positive and distinct")
        correct = _percent(Fraction(current - base, base))
        targeted = _percent(Fraction(current - base, current))
    elif adapter == "data.percentage-points.v1":
        item = _require_payload(payload, adapter, {"current_percent", "change_pp"})
        current_percent = _integer(item, "current_percent")
        change_pp = _integer(item, "change_pp")
        if change_pp == 0:
            raise PracticeBankValidationError("percentage-point change must be non-zero")
        current = Fraction(current_percent, 100)
        change = Fraction(change_pp, 100)
        correct, targeted = _percent(current - change), _percent(current + change)
    elif adapter == "data.growth.amount.v1":
        item = _require_payload(payload, adapter, {"current", "rate_n", "rate_d"})
        current = _integer(item, "current")
        rate_n, rate_d = _integer(item, "rate_n"), _integer(item, "rate_d")
        if current <= 0 or rate_n <= 0 or rate_d <= 0:
            raise PracticeBankValidationError("growth-amount values must be positive")
        rate = Fraction(rate_n, rate_d)
        correct = _number(Fraction(current) * rate / (1 + rate), "单位")
        targeted = _number(Fraction(current) * rate, "单位")
    elif adapter == "data.growth.compare.v1":
        item = _require_payload(payload, adapter, {"rows"})
        correct, targeted = _comparison_answers(item["rows"])
    elif adapter == "data.ratio.part-whole.v1":
        item = _require_payload(payload, adapter, {"part", "whole"})
        part, whole = _integer(item, "part"), _integer(item, "whole")
        if not 0 < part < whole:
            raise PracticeBankValidationError("part-whole values must satisfy 0 < part < whole")
        correct, targeted = _percent(Fraction(part, whole)), _percent(Fraction(whole, part))
    elif adapter == "data.share.base.v1":
        fields = {"current_part", "current_total", "part_rate_percent", "total_rate_percent"}
        item = _require_payload(payload, adapter, fields)
        current_part = _integer(item, "current_part")
        current_total = _integer(item, "current_total")
        part_rate_percent = _integer(item, "part_rate_percent")
        total_rate_percent = _integer(item, "total_rate_percent")
        if (
            not 0 < current_part < current_total
            or part_rate_percent <= -100
            or total_rate_percent <= -100
        ):
            raise PracticeBankValidationError("base-share values are outside supported bounds")
        current_share = Fraction(current_part, current_total)
        part_rate = Fraction(part_rate_percent, 100)
        total_rate = Fraction(total_rate_percent, 100)
        correct = _percent(current_share * (1 + total_rate) / (1 + part_rate))
        targeted = _percent(current_share * (1 + part_rate) / (1 + total_rate))
    elif adapter == "data.average.relations.v1":
        if not isinstance(payload, Mapping) or payload.get("mode") not in {"current", "base", "growth"}:
            raise PracticeBankValidationError("invalid average relation mode")
        if payload["mode"] == "current":
            item = _require_payload(payload, adapter, {"mode", "total", "count", "unit"})
            total, count = _integer(item, "total"), _integer(item, "count")
            if total <= 0 or count <= 0 or not isinstance(item["unit"], str) or not item["unit"].strip():
                raise PracticeBankValidationError("current-average values are invalid")
            correct = _number(Fraction(total, count), item["unit"])
            targeted = _number(Fraction(count, total), item["unit"])
        elif payload["mode"] == "base":
            fields = {
                "mode", "current_total", "current_count", "total_rate_percent",
                "count_rate_percent", "unit",
            }
            item = _require_payload(payload, adapter, fields)
            current_total = _integer(item, "current_total")
            current_count = _integer(item, "current_count")
            total_rate_percent = _integer(item, "total_rate_percent")
            count_rate_percent = _integer(item, "count_rate_percent")
            if (
                current_total <= 0
                or current_count <= 0
                or total_rate_percent <= -100
                or count_rate_percent <= -100
                or not isinstance(item["unit"], str)
                or not item["unit"].strip()
            ):
                raise PracticeBankValidationError("base-average values are outside supported bounds")
            current_average = Fraction(current_total, current_count)
            total_rate = Fraction(total_rate_percent, 100)
            count_rate = Fraction(count_rate_percent, 100)
            correct = _number(current_average * (1 + count_rate) / (1 + total_rate), item["unit"])
            targeted = _number(current_average * (1 + total_rate) / (1 + count_rate), item["unit"])
        else:
            item = _require_payload(payload, adapter, {"mode", "total_rate_percent", "count_rate_percent"})
            total_rate_percent = _integer(item, "total_rate_percent")
            count_rate_percent = _integer(item, "count_rate_percent")
            if count_rate_percent <= -100 or total_rate_percent <= -100:
                raise PracticeBankValidationError("average rates must be greater than -100%")
            total_rate = Fraction(total_rate_percent, 100)
            count_rate = Fraction(count_rate_percent, 100)
            correct = _percent((total_rate - count_rate) / (1 + count_rate))
            targeted = _percent((count_rate - total_rate) / (1 + total_rate))
    elif adapter == "data.multiple.more.v1":
        if not isinstance(payload, Mapping) or payload.get("mode") not in {"current", "base"}:
            raise PracticeBankValidationError("invalid multiple relation mode")
        if payload["mode"] == "current":
            item = _require_payload(payload, adapter, {"mode", "value_a", "value_b"})
            value_a, value_b = _integer(item, "value_a"), _integer(item, "value_b")
            if value_a <= value_b or value_b <= 0:
                raise PracticeBankValidationError("current multiple requires value_a > value_b > 0")
            ratio = Fraction(value_a, value_b)
        else:
            fields = {"mode", "value_a", "value_b", "rate_a_percent", "rate_b_percent"}
            item = _require_payload(payload, adapter, fields)
            value_a, value_b = _integer(item, "value_a"), _integer(item, "value_b")
            rate_a_percent = _integer(item, "rate_a_percent")
            rate_b_percent = _integer(item, "rate_b_percent")
            if value_a <= 0 or value_b <= 0 or rate_a_percent <= -100 or rate_b_percent <= -100:
                raise PracticeBankValidationError("base multiple values are outside supported bounds")
            ratio = Fraction(value_a, value_b)
            ratio *= Fraction(100 + rate_b_percent, 100 + rate_a_percent)
            if ratio <= 1:
                raise PracticeBankValidationError("base multiple must keep A greater than B")
        correct, targeted = _number(ratio - 1, "倍"), _number(ratio, "倍")
    else:
        raise PracticeBankValidationError(f"unknown data-analysis verification adapter: {adapter}")
    _check_answer(question, correct, targeted)


def generate_data_analysis_bank() -> tuple[tuple[UnitSpec, ...], tuple[dict[str, Any], ...]]:
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
    validate_generated_module(MODULE_SLUG, UNITS, questions, verify_data_analysis_question)
    return UNITS, tuple(questions)


__all__ = ["UNITS", "generate_data_analysis_bank", "verify_data_analysis_question"]
