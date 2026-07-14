from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


_CLAUSE_BOUNDARY = re.compile(r"[。！？!?；;,，\n]|(?:但是|然而|不过|而是|却)")
_NEGATION = re.compile(
    r"(?:不存在|并不存在|没有|并没有|未曾|尚未|未|没|无|勿|别|不要|不应|不该|不能|不得|"
    r"不认可|并不|不(?!仅|但|只|单)|反对|拒绝|否认|并非|不是|不予|禁止)"
)
_ACTION_REJECTION = re.compile(
    r"(?:取消|撤销|废除|放弃|舍弃|停止|终止|中止|避免|规避|删除|去除|排除)"
)
_ACTION_SCOPE_BREAK = re.compile(r"(?:并且|同时|随后|然后|另外|但是|然而|不过|而是|却|并|且|后再|之后)")
_NON_NEGATING_PREFIX = re.compile(
    r"(?:不能不|不得不|并非不|不是不|未尝不|不仅|不但|不只|不单|"
    r"(?:不能|不应|不该|不得|不要|禁止|反对|拒绝|避免|停止)"
    r"(?:忽视|忽略|否认|取消|撤销|废除|放弃|舍弃|删除|去除|排除|停止|终止|中止|避免|规避))$"
)
_REJECTING_SUFFIX = re.compile(
    r"^(?:是|属于|这个(?:做法|说法|公式)?是)?"
    r"(?:错误|错的|不对|不可取|不应该|不应|不该|不要|不能|"
    r"应当取消|应该取消|必须取消|须取消|应当避免|应该避免|必须避免|"
    r"应当放弃|应该放弃|必须放弃|应当停止|应该停止|必须停止|应当废除|必须废除)"
)
_GLOBAL_REJECTION = re.compile(
    r"(?:以上|上述|这些|下列).{0,6}(?:都|均|一律|全部)?"
    r"(?:(?:不应|不要|不能|不得|不可|反对|拒绝)"
    r"(?:做|采用|实施|成立|计分|作为|写入|选择|保留|提出)|"
    r"(?:取消|撤销|废除|放弃|舍弃|停止|终止|中止|避免|规避|删除|去除|排除))"
)


def normalise_authored_text(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())


def has_affirmed_alias(text: str, aliases: Iterable[str]) -> bool:
    normalized = normalise_authored_text(text)
    return any(_alias_has_polarity(normalized, alias, affirmed=True) for alias in aliases)


def has_negated_alias(text: str, aliases: Iterable[str]) -> bool:
    normalized = normalise_authored_text(text)
    return any(_alias_has_polarity(normalized, alias, affirmed=False) for alias in aliases)


def statement_is_rejected(text: str) -> bool:
    """Return true when a short probe statement explicitly rejects its own claim."""

    normalized = normalise_authored_text(text)
    return bool(
        re.search(
            r"(?:不能|不应|不要|不该|反对|拒绝|取消|撤销|废除|放弃|舍弃|"
            r"停止|终止|中止|避免|规避).{0,20}(?:公式|做法|说法|分母|除以|/)",
            normalized,
        )
        or re.search(
            r"(?:公式|做法|说法|分母|除以|/).{0,12}"
            r"(?:错误|错的|不对|不可取|不成立|应当取消|必须取消|应当放弃|"
            r"必须放弃|应当停止|必须停止|应当避免|必须避免)",
            normalized,
        )
    )


def _alias_has_polarity(text: str, alias: str, *, affirmed: bool) -> bool:
    needle = normalise_authored_text(alias)
    if not needle:
        return False
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return False
        negated = _occurrence_is_negated(text, index, index + len(needle))
        if negated is not affirmed:
            return True
        start = index + max(1, len(needle))


def _occurrence_is_negated(text: str, start: int, end: int) -> bool:
    before = text[:start]
    boundary = 0
    for match in _CLAUSE_BOUNDARY.finditer(before):
        boundary = match.end()
    prefix = before[boundary:]
    if _NON_NEGATING_PREFIX.search(prefix):
        direct_negation = False
    else:
        direct_negation = bool(_NEGATION.search(prefix) or _has_local_action_rejection(prefix))

    after = text[end:]
    suffix_boundary = _CLAUSE_BOUNDARY.search(after)
    suffix = after[: suffix_boundary.start() if suffix_boundary else 18]
    trailing_rejection = bool(_REJECTING_SUFFIX.search(suffix))

    sentence_start = max(
        text.rfind("。", 0, start),
        text.rfind("！", 0, start),
        text.rfind("？", 0, start),
        text.rfind(";", 0, start),
        text.rfind("；", 0, start),
    ) + 1
    sentence_end_candidates = [
        position for mark in ("。", "！", "？", ";", "；")
        if (position := text.find(mark, end)) >= 0
    ]
    sentence_end = min(sentence_end_candidates, default=len(text))
    sentence = text[sentence_start:sentence_end]
    global_match = _GLOBAL_REJECTION.search(sentence)
    global_rejection = bool(global_match and (
        sentence_start + global_match.start() <= start
        or sentence_start + global_match.start() >= end
    ))
    return direct_negation or trailing_rejection or global_rejection


def _has_local_action_rejection(prefix: str) -> bool:
    """Conservatively extend a rejection verb across one short authored phrase.

    This catches nested aliases such as ``通知`` inside
    ``必须取消消防演练通知``. A coordination marker ends the action's scope so
    ``避免遗漏并保留人工窗口`` still affirms the latter clause.
    """

    matches = list(_ACTION_REJECTION.finditer(prefix))
    if not matches:
        return False
    tail = prefix[matches[-1].end():]
    return len(tail) <= 20 and _ACTION_SCOPE_BREAK.search(tail) is None
