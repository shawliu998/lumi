from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ASSISTANCE_POLICY_VERSION = "assistance-evidence-policy.v1"
ASSISTANCE_CALIBRATION_STATUS = "engineering_policy_unvalidated"


@dataclass(frozen=True, slots=True)
class AssistancePolicyLevel:
    ordinal: int
    action: str
    diagnostic_evidence_weight: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "action": self.action,
            "diagnostic_evidence_weight": self.diagnostic_evidence_weight,
            "calibration_status": ASSISTANCE_CALIBRATION_STATUS,
        }


ASSISTANCE_LEVELS = (
    AssistancePolicyLevel(1, "retry", 1.00),
    AssistancePolicyLevel(2, "locate_evidence", 0.80),
    AssistancePolicyLevel(3, "rule_hint", 0.65),
    AssistancePolicyLevel(4, "analogous_example", 0.50),
    AssistancePolicyLevel(5, "worked_step", 0.30),
    AssistancePolicyLevel(6, "full_explanation", 0.00),
)


def assistance_policy_manifest() -> dict[str, Any]:
    return {
        "policy_version": ASSISTANCE_POLICY_VERSION,
        "calibration_status": ASSISTANCE_CALIBRATION_STATUS,
        "note": "Engineering evidence policy; not calibrated from learner populations.",
        "levels": [level.to_dict() for level in ASSISTANCE_LEVELS],
        "assisted_verification_mastery_credit": 0.0,
    }


def assistance_level(action: str) -> AssistancePolicyLevel:
    for level in ASSISTANCE_LEVELS:
        if level.action == action:
            return level
    raise KeyError(action)


def next_assistance_level(delivered_count: int) -> AssistancePolicyLevel:
    if delivered_count < 0:
        raise ValueError("delivered_count cannot be negative")
    try:
        return ASSISTANCE_LEVELS[delivered_count]
    except IndexError:
        raise LookupError("assistance ladder is exhausted") from None
