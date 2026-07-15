from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence


BANK_ID = "lumi.xingce.core-320.practice-v3"
BANK_VERSION = "1.0.1"
GENERATOR_VERSION = "lumi.practice-generator.v3.0.1"
QUESTION_SCHEMA_VERSION = "hermes.question-version.v3"
PUBLIC_QUESTION_SCHEMA_VERSION = "hermes.question-public.v2"
MODULE_CONTENT_SOURCE_IDS = {
    "verbal": "src.lumi.core320.wen-structure",
    "judgment": "src.lumi.core320.wen-structure",
    "quantitative": "src.lumi.core320.li-structure",
    "data-analysis": "src.lumi.core320.li-structure",
}

MODULE_SCOPES = {
    "verbal": "xingce.verbal.core",
    "judgment": "xingce.judgment.core",
    "quantitative": "xingce.quantitative.core",
    "data-analysis": "xingce.data-analysis.core",
}
MIXED_SCOPE_ID = "xingce.mixed.core"
MODULE_LABELS = {
    "verbal": "言语理解",
    "judgment": "判断推理",
    "quantitative": "数量关系",
    "data-analysis": "资料分析",
}
MODULE_ORDER = tuple(MODULE_SCOPES)
QUESTIONS_PER_MODULE = 80
QUESTIONS_PER_UNIT = 10
REGULAR_VARIANTS_PER_UNIT = 8

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class PracticeBankValidationError(ValueError):
    """The generated practice bank is inconsistent or unsafe to serve."""


@dataclass(frozen=True)
class UnitSpec:
    module_slug: str
    unit_slug: str
    unit_label: str
    signature_slug: str
    signature_label: str
    observable_rule: str
    cause_slugs: tuple[str, ...]
    cause_labels: tuple[str, ...]
    principle: str
    worked_contrast: str
    return_action: str

    def __post_init__(self) -> None:
        if self.module_slug not in MODULE_SCOPES:
            raise PracticeBankValidationError(f"unsupported module: {self.module_slug}")
        for value in (self.unit_slug, self.signature_slug, *self.cause_slugs):
            if not _IDENTIFIER.fullmatch(value):
                raise PracticeBankValidationError(f"invalid stable slug: {value}")
        if not self.cause_slugs or len(self.cause_slugs) != len(self.cause_labels):
            raise PracticeBankValidationError("each unit needs aligned cause slugs and labels")

    @property
    def diagnostic_unit_id(self) -> str:
        return f"xingce.{self.module_slug}.{self.unit_slug}"

    @property
    def signature_id(self) -> str:
        return f"{self.module_slug}.{self.unit_slug}.{self.signature_slug}"

    @property
    def cause_ids(self) -> tuple[str, ...]:
        return tuple(
            f"cause.{self.module_slug}.{self.unit_slug}.{slug}" for slug in self.cause_slugs
        )


@dataclass(frozen=True)
class AuthoredChoice:
    prompt: str
    correct: str
    targeted_wrong: str
    other_wrong: tuple[str, str]
    explanation: str
    verification: Mapping[str, Any]

    def __post_init__(self) -> None:
        values = (self.correct, self.targeted_wrong, *self.other_wrong)
        if not self.prompt.strip() or not self.explanation.strip():
            raise PracticeBankValidationError("question prompt and explanation cannot be blank")
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise PracticeBankValidationError("all four answer choices must be non-empty strings")
        if len(set(values)) != 4:
            raise PracticeBankValidationError("all four answer choices must be distinct")
        if not isinstance(self.verification, Mapping) or not self.verification.get("adapter"):
            raise PracticeBankValidationError("every generated item needs a verification adapter")


def global_sequence(module_slug: str, local_index: int) -> int:
    """Interleave modules so mixed practice rotates instead of sorting by module."""

    if module_slug not in MODULE_ORDER or not 0 <= local_index < QUESTIONS_PER_MODULE:
        raise PracticeBankValidationError("invalid module/local sequence")
    return local_index * len(MODULE_ORDER) + MODULE_ORDER.index(module_slug) + 1


def schedule_pairs(unit_count: int = 8) -> tuple[tuple[int, int], ...]:
    """Return 80 local slots as four units x two variants per eight-item block."""

    if unit_count != 8:
        raise PracticeBankValidationError("core-320 currently requires eight units per module")
    result: list[tuple[int, int]] = []
    variant_by_unit = [0] * unit_count
    for block in range(10):
        start = 0 if block % 2 == 0 else 4
        for unit_index in range(start, start + 4):
            for _ in range(2):
                variant = variant_by_unit[unit_index]
                result.append((unit_index, variant))
                variant_by_unit[unit_index] += 1
    if len(result) != QUESTIONS_PER_MODULE or set(variant_by_unit) != {QUESTIONS_PER_UNIT}:
        raise AssertionError("invalid core-320 scheduling matrix")
    return tuple(result)


def evidence_family_number(variant: int) -> int:
    families = (0, 1, 2, 3, 4, 0, 1, 2, 5, 6)
    if not 0 <= variant < len(families):
        raise PracticeBankValidationError("variant is outside the ten-version unit matrix")
    return families[variant]


def _choice_order(values: Sequence[str], sequence: int) -> tuple[str, ...]:
    if len(values) != 4:
        raise PracticeBankValidationError("exactly four choices are required")
    # Use a deterministic Latin schedule in four-local-item blocks.  Each
    # module still receives exactly 20 A/B/C/D keys, and every mixed row uses
    # all four keys once, but the answer is no longer the visible
    # ``local_index % 4`` pattern recoverable from the question ID.
    local_index = (sequence - 1) // len(MODULE_ORDER)
    module_index = (sequence - 1) % len(MODULE_ORDER)
    block, row = divmod(local_index, 4)

    def stable_permutation(label: str) -> tuple[int, ...]:
        return tuple(
            sorted(
                range(4),
                key=lambda value: hashlib.sha256(
                    f"{GENERATOR_VERSION}:{block}:{label}:{value}".encode("utf-8")
                ).digest(),
            )
        )

    row_order = stable_permutation("row")
    module_order = stable_permutation("module")
    key_order = stable_permutation("key")
    correct_position = key_order[(row_order[row] + module_order[module_index]) % 4]
    placement_seed = hashlib.sha256(
        f"{GENERATOR_VERSION}:{sequence}:distractors".encode("utf-8")
    ).digest()
    targeted_offset = 1 + placement_seed[0] % 3
    targeted_position = (correct_position + targeted_offset) % 4
    remaining_positions = [
        index for index in range(4) if index not in {correct_position, targeted_position}
    ]
    ordered: list[str | None] = [None, None, None, None]
    ordered[correct_position] = values[0]
    ordered[targeted_position] = values[1]
    if placement_seed[1] % 2:
        remaining_positions.reverse()
    ordered[remaining_positions[0]] = values[2]
    ordered[remaining_positions[1]] = values[3]
    return tuple(str(value) for value in ordered)


def build_question(
    spec: UnitSpec,
    *,
    local_index: int,
    variant: int,
    authored: AuthoredChoice,
) -> dict[str, Any]:
    sequence = global_sequence(spec.module_slug, local_index)
    ordered = _choice_order(
        (authored.correct, authored.targeted_wrong, *authored.other_wrong),
        sequence,
    )
    options = dict(zip("ABCD", ordered, strict=True))
    correct_option = next(key for key, value in options.items() if value == authored.correct)
    targeted_option = next(key for key, value in options.items() if value == authored.targeted_wrong)
    mappings: dict[str, dict[str, Any]] = {}
    for option_id, text in options.items():
        if option_id == correct_option:
            continue
        targeted = option_id == targeted_option
        mappings[option_id] = {
            "signature_id": spec.signature_id if targeted else None,
            "cause_candidate_ids": list(spec.cause_ids) if targeted else [],
            "observation": (
                f"所选项符合可观察错误模式：{spec.signature_label}"
                if targeted
                else f"所选项“{text}”与本题约束不一致，暂不归入稳定错误模式"
            ),
        }
    family = evidence_family_number(variant)
    delayed = variant >= REGULAR_VARIANTS_PER_UNIT
    return {
        "schema_version": QUESTION_SCHEMA_VERSION,
        "question_id": (
            f"xingce.v3.q{sequence:03d}.{spec.module_slug}.{spec.unit_slug}.v{variant + 1:02d}"
        ),
        "version": BANK_VERSION,
        "status": "published_internal",
        "domain": "xingce",
        "module_id": MODULE_SCOPES[spec.module_slug],
        "user_facing_type": MODULE_LABELS[spec.module_slug],
        "diagnostic_unit_id": spec.diagnostic_unit_id,
        "template_id": f"tpl.xingce.{spec.module_slug}.{spec.unit_slug}.v1",
        "content_source_id": MODULE_CONTENT_SOURCE_IDS[spec.module_slug],
        # Every generated item has an independent stimulus.  Evidence-family
        # buckets may intentionally recur across ordinary variants, but a
        # material group must never alias two unrelated prompts.
        "material_group_id": f"mg.v3.{spec.module_slug}.{spec.unit_slug}.m{variant + 1:02d}",
        "evidence_family_id": f"ef.v3.{spec.module_slug}.{spec.unit_slug}.f{family}",
        "prompt": authored.prompt.strip(),
        "response_mode": "single_choice",
        "options": options,
        "scoring": {
            "adapter": "xingce_mcq_v3",
            "max_score": 1,
            "correct_option": correct_option,
            "canonical_answer": authored.correct,
            "error_option_mappings": mappings,
        },
        "role_eligibility": {
            "regular_practice": not delayed,
            "near_transfer": not delayed,
            "delayed_validation": delayed,
            "reserved_unexposed": delayed,
            "filler": False,
            "evidence_eligible": True,
        },
        "feedback": {
            "first_error_principle": spec.principle,
            "full_explanation": authored.explanation.strip(),
        },
        "verification": copy.deepcopy(dict(authored.verification)),
        "generation": {
            "generator_version": GENERATOR_VERSION,
            "local_index": local_index,
            "variant": variant,
        },
    }


def signature_record(spec: UnitSpec) -> dict[str, Any]:
    return {
        "signature_id": spec.signature_id,
        "label": spec.signature_label,
        "observable_rule": spec.observable_rule,
        "semantics": "observed_option_pattern_not_mental_cause",
    }


def cause_records(spec: UnitSpec) -> list[dict[str, Any]]:
    return [
        {
            "cause_id": cause_id,
            "label": label,
            "semantics": "actionable_withdrawable_hypothesis_not_ground_truth",
        }
        for cause_id, label in zip(spec.cause_ids, spec.cause_labels, strict=True)
    ]


def intervention_records(spec: UnitSpec) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tutorial = {
        "schema_version": "hermes.intervention-asset.v3",
        "asset_id": f"asset.v3.{spec.module_slug}.{spec.unit_slug}.tutorial",
        "version": BANK_VERSION,
        "kind": "microtutorial",
        "target_signature_ids": [spec.signature_id],
        "target_cause_id": spec.cause_ids[0],
        "title": spec.unit_label,
        "estimated_seconds": 45,
        "principle": spec.principle,
        "worked_contrast": spec.worked_contrast,
        "return_action": spec.return_action,
        "authorization_status": "internal_mvp_only",
        "review_status": "human_review_required",
    }
    probes: list[dict[str, Any]] = []
    if len(spec.cause_ids) > 1:
        option_keys = tuple(chr(ord("A") + index) for index in range(len(spec.cause_ids)))
        options = {
            key: label for key, label in zip(option_keys, spec.cause_labels, strict=True)
        }
        probes.append(
            {
                "schema_version": "hermes.intervention-asset.v3",
                "asset_id": f"asset.v3.{spec.module_slug}.{spec.unit_slug}.probe",
                "version": BANK_VERSION,
                "kind": "structured_probe",
                "trigger_signature_ids": [spec.signature_id],
                "candidate_cause_ids": list(spec.cause_ids),
                "title": "快速核对解题步骤",
                "prompt": "刚才作答时，下面哪一步最接近你的实际判断？",
                "response_mode": "single_choice",
                "options": options,
                "option_results": {
                    key: cause_id for key, cause_id in zip(option_keys, spec.cause_ids, strict=True)
                },
                "optional": True,
                "authorization_status": "internal_mvp_only",
                "review_status": "human_review_required",
            }
        )
    return tutorial, probes


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_common_question(question: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "question_id", "version", "status", "domain", "module_id",
        "user_facing_type", "diagnostic_unit_id", "template_id", "content_source_id",
        "material_group_id", "evidence_family_id", "prompt", "response_mode", "options",
        "scoring", "role_eligibility", "feedback", "verification", "generation",
    }
    if set(question) != required:
        raise PracticeBankValidationError(
            f"question fields mismatch: missing={sorted(required - set(question))}, "
            f"unknown={sorted(set(question) - required)}"
        )
    if question["schema_version"] != QUESTION_SCHEMA_VERSION:
        raise PracticeBankValidationError("unsupported question schema")
    if not _IDENTIFIER.fullmatch(str(question["question_id"])):
        raise PracticeBankValidationError("invalid question ID")
    if not _SEMVER.fullmatch(str(question["version"])) or question["version"] != BANK_VERSION:
        raise PracticeBankValidationError("invalid question version")
    if question["status"] != "published_internal" or question["domain"] != "xingce":
        raise PracticeBankValidationError("only internal Xingce questions may load")
    if question["module_id"] not in MODULE_SCOPES.values():
        raise PracticeBankValidationError("question module scope is unknown")
    module_slug = next(
        slug for slug, scope_id in MODULE_SCOPES.items() if scope_id == question["module_id"]
    )
    if question["user_facing_type"] != MODULE_LABELS[module_slug]:
        raise PracticeBankValidationError("question module label is inconsistent")
    for field in (
        "diagnostic_unit_id",
        "template_id",
        "content_source_id",
        "material_group_id",
        "evidence_family_id",
    ):
        if not isinstance(question[field], str) or not _IDENTIFIER.fullmatch(question[field]):
            raise PracticeBankValidationError(f"invalid question identifier: {field}")
    if not isinstance(question["prompt"], str) or not question["prompt"].strip():
        raise PracticeBankValidationError("question prompt cannot be blank")
    if question["response_mode"] != "single_choice":
        raise PracticeBankValidationError("core-320 questions must be single choice")
    options = question["options"]
    if not isinstance(options, Mapping) or set(options) != set("ABCD"):
        raise PracticeBankValidationError("questions require exactly A-D choices")
    if any(not isinstance(value, str) or not value.strip() for value in options.values()):
        raise PracticeBankValidationError("question choices must be non-empty strings")
    if len({value.strip().casefold() for value in options.values()}) != 4:
        raise PracticeBankValidationError("question choices must be unique")
    scoring = question["scoring"]
    if not isinstance(scoring, Mapping) or set(scoring) != {
        "adapter",
        "max_score",
        "correct_option",
        "canonical_answer",
        "error_option_mappings",
    }:
        raise PracticeBankValidationError("question scoring fields are invalid")
    correct = scoring.get("correct_option") if isinstance(scoring, Mapping) else None
    if (
        scoring.get("adapter") != "xingce_mcq_v3"
        or scoring.get("max_score") != 1
        or isinstance(scoring.get("max_score"), bool)
        or correct not in options
    ):
        raise PracticeBankValidationError("question scoring is invalid")
    if scoring.get("canonical_answer") != options[correct]:
        raise PracticeBankValidationError("canonical answer must match the correct option")
    mappings = scoring.get("error_option_mappings")
    if not isinstance(mappings, Mapping) or set(mappings) != set(options) - {correct}:
        raise PracticeBankValidationError("every wrong option needs an evidence mapping")
    for mapping in mappings.values():
        if not isinstance(mapping, Mapping) or set(mapping) != {
            "signature_id",
            "cause_candidate_ids",
            "observation",
        }:
            raise PracticeBankValidationError("error-option evidence mapping is malformed")
        signature_id = mapping["signature_id"]
        causes = mapping["cause_candidate_ids"]
        if signature_id is not None and (
            not isinstance(signature_id, str) or not _IDENTIFIER.fullmatch(signature_id)
        ):
            raise PracticeBankValidationError("error signature ID is invalid")
        if (
            not isinstance(causes, list)
            or any(not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) for value in causes)
            or len(causes) != len(set(causes))
        ):
            raise PracticeBankValidationError("cause candidate IDs are invalid")
        if not isinstance(mapping["observation"], str) or not mapping["observation"].strip():
            raise PracticeBankValidationError("error-option observation cannot be blank")
        if (signature_id is None) != (causes == []):
            raise PracticeBankValidationError("only diagnostic distractors may name causes")
    target_mappings = [item for item in mappings.values() if item["signature_id"]]
    if len(target_mappings) != 1 or not target_mappings[0].get("cause_candidate_ids"):
        raise PracticeBankValidationError("each item needs exactly one diagnostic distractor")
    roles = question["role_eligibility"]
    if not isinstance(roles, Mapping) or set(roles) != {
        "regular_practice", "near_transfer", "delayed_validation", "reserved_unexposed",
        "filler", "evidence_eligible",
    }:
        raise PracticeBankValidationError("question role contract is incomplete")
    if any(not isinstance(value, bool) for value in roles.values()):
        raise PracticeBankValidationError("question roles must be booleans")
    if roles["delayed_validation"] != roles["reserved_unexposed"]:
        raise PracticeBankValidationError("delayed items must remain reserved from ordinary practice")
    if roles["regular_practice"] == roles["delayed_validation"]:
        raise PracticeBankValidationError("ordinary and delayed roles must be disjoint")
    if roles["near_transfer"] != roles["regular_practice"]:
        raise PracticeBankValidationError("ordinary variants must retain their near-transfer role")
    if roles["filler"] or not roles["evidence_eligible"]:
        raise PracticeBankValidationError("core-320 questions must be evidence eligible")
    feedback = question["feedback"]
    if not isinstance(feedback, Mapping) or set(feedback) != {
        "first_error_principle",
        "full_explanation",
    }:
        raise PracticeBankValidationError("question feedback fields are invalid")
    if any(not isinstance(value, str) or not value.strip() for value in feedback.values()):
        raise PracticeBankValidationError("question feedback cannot be blank")
    verification = question["verification"]
    if (
        not isinstance(verification, Mapping)
        or not isinstance(verification.get("adapter"), str)
        or not verification["adapter"].strip()
    ):
        raise PracticeBankValidationError("question verification adapter is invalid")
    generation = question["generation"]
    if not isinstance(generation, Mapping) or set(generation) != {
        "generator_version",
        "local_index",
        "variant",
    }:
        raise PracticeBankValidationError("question generation fields are invalid")
    local_index, variant = generation["local_index"], generation["variant"]
    if (
        generation["generator_version"] != GENERATOR_VERSION
        or not isinstance(local_index, int)
        or isinstance(local_index, bool)
        or not 0 <= local_index < QUESTIONS_PER_MODULE
        or not isinstance(variant, int)
        or isinstance(variant, bool)
        or not 0 <= variant < QUESTIONS_PER_UNIT
    ):
        raise PracticeBankValidationError("question generation slot is invalid")


def _verify_generated_slot(
    question: Mapping[str, Any],
    spec: UnitSpec,
    *,
    local_index: int,
    variant: int,
) -> None:
    sequence = global_sequence(spec.module_slug, local_index)
    expected_question_id = (
        f"xingce.v3.q{sequence:03d}.{spec.module_slug}.{spec.unit_slug}.v{variant + 1:02d}"
    )
    family = evidence_family_number(variant)
    expected_delayed = variant >= REGULAR_VARIANTS_PER_UNIT
    expected = {
        "question_id": expected_question_id,
        "module_id": MODULE_SCOPES[spec.module_slug],
        "user_facing_type": MODULE_LABELS[spec.module_slug],
        "diagnostic_unit_id": spec.diagnostic_unit_id,
        "template_id": f"tpl.xingce.{spec.module_slug}.{spec.unit_slug}.v1",
        "content_source_id": MODULE_CONTENT_SOURCE_IDS[spec.module_slug],
        "material_group_id": f"mg.v3.{spec.module_slug}.{spec.unit_slug}.m{variant + 1:02d}",
        "evidence_family_id": f"ef.v3.{spec.module_slug}.{spec.unit_slug}.f{family}",
    }
    for field, value in expected.items():
        if question[field] != value:
            raise PracticeBankValidationError(f"generated slot has inconsistent {field}")
    if question["generation"] != {
        "generator_version": GENERATOR_VERSION,
        "local_index": local_index,
        "variant": variant,
    }:
        raise PracticeBankValidationError("generated slot metadata is inconsistent")
    roles = question["role_eligibility"]
    if roles != {
        "regular_practice": not expected_delayed,
        "near_transfer": not expected_delayed,
        "delayed_validation": expected_delayed,
        "reserved_unexposed": expected_delayed,
        "filler": False,
        "evidence_eligible": True,
    }:
        raise PracticeBankValidationError("generated slot has inconsistent role eligibility")
    target_mappings = [
        mapping
        for mapping in question["scoring"]["error_option_mappings"].values()
        if mapping["signature_id"] is not None
    ]
    if len(target_mappings) != 1 or target_mappings[0]["signature_id"] != spec.signature_id:
        raise PracticeBankValidationError("generated slot has the wrong error signature")
    if target_mappings[0]["cause_candidate_ids"] != list(spec.cause_ids):
        raise PracticeBankValidationError("generated slot has the wrong cause candidates")


def validate_generated_module(
    module_slug: str,
    units: Sequence[UnitSpec],
    questions: Sequence[Mapping[str, Any]],
    verifier: Callable[[Mapping[str, Any]], None],
) -> None:
    if len(units) != 8 or len(questions) != QUESTIONS_PER_MODULE:
        raise PracticeBankValidationError(f"{module_slug} must generate 8 units and 80 questions")
    if module_slug not in MODULE_SCOPES or any(spec.module_slug != module_slug for spec in units):
        raise PracticeBankValidationError("module unit specifications are inconsistent")
    unit_ids = {spec.diagnostic_unit_id for spec in units}
    counts = {unit_id: 0 for unit_id in unit_ids}
    by_local_index: dict[int, Mapping[str, Any]] = {}
    for question in questions:
        verify_common_question(question)
        if question["module_id"] != MODULE_SCOPES[module_slug]:
            raise PracticeBankValidationError("question escaped its module scope")
        unit_id = question["diagnostic_unit_id"]
        if unit_id not in counts:
            raise PracticeBankValidationError("question references an undeclared diagnostic unit")
        counts[unit_id] += 1
        local_index = question["generation"]["local_index"]
        if local_index in by_local_index:
            raise PracticeBankValidationError("module contains a duplicate local generation slot")
        by_local_index[local_index] = question
    expected_pairs = schedule_pairs(len(units))
    if set(by_local_index) != set(range(QUESTIONS_PER_MODULE)):
        raise PracticeBankValidationError("module generation slots must cover local indices 0-79")
    variants_by_unit: dict[str, set[int]] = {unit_id: set() for unit_id in unit_ids}
    for local_index, (unit_index, variant) in enumerate(expected_pairs):
        question = by_local_index[local_index]
        spec = units[unit_index]
        _verify_generated_slot(question, spec, local_index=local_index, variant=variant)
        variants_by_unit[spec.diagnostic_unit_id].add(variant)
        verifier(question)
    if set(counts.values()) != {QUESTIONS_PER_UNIT}:
        raise PracticeBankValidationError("each diagnostic unit must have ten question versions")
    if any(variants != set(range(QUESTIONS_PER_UNIT)) for variants in variants_by_unit.values()):
        raise PracticeBankValidationError("each diagnostic unit must cover variants 0-9 exactly once")
    delayed = [item for item in questions if item["role_eligibility"]["delayed_validation"]]
    if len(delayed) != 16:
        raise PracticeBankValidationError("each module must reserve sixteen delayed-validation items")
    for unit_id in unit_ids:
        unit_questions = [item for item in questions if item["diagnostic_unit_id"] == unit_id]
        regular_families = {
            item["evidence_family_id"]
            for item in unit_questions
            if item["role_eligibility"]["regular_practice"]
        }
        delayed_families = {
            item["evidence_family_id"]
            for item in unit_questions
            if item["role_eligibility"]["delayed_validation"]
        }
        if regular_families & delayed_families:
            raise PracticeBankValidationError(
                "delayed validation must use evidence families unseen in ordinary practice"
            )
        if len({item["material_group_id"] for item in unit_questions}) != QUESTIONS_PER_UNIT:
            raise PracticeBankValidationError("unrelated question stimuli must not share a material group")


def safe_question_view(question: Mapping[str, Any]) -> dict[str, Any]:
    """Answer-safe projection shared with the v2 client contract."""

    verify_common_question(question)
    return {
        "schema_version": PUBLIC_QUESTION_SCHEMA_VERSION,
        "question_id": question["question_id"],
        "version": question["version"],
        "domain": question["domain"],
        "user_facing_type": question["user_facing_type"],
        "prompt": question["prompt"],
        "response_mode": "single_choice",
        "options": copy.deepcopy(dict(question["options"])),
    }


def score_question(question: Mapping[str, Any], answer: str) -> dict[str, Any]:
    if not isinstance(answer, str) or answer.strip().upper() not in question.get("options", {}):
        raise PracticeBankValidationError("response must be one of A, B, C, or D")
    selected = answer.strip().upper()
    scoring = question["scoring"]
    correct = selected == scoring["correct_option"]
    mapping = {} if correct else scoring["error_option_mappings"][selected]
    return {
        "question_id": question["question_id"],
        "question_version": question["version"],
        "selected_option": selected,
        "correct": correct,
        "observed_error_signature_id": mapping.get("signature_id"),
        "cause_candidate_ids": copy.deepcopy(mapping.get("cause_candidate_ids", [])),
        "observation": mapping.get("observation"),
    }


def unique_records(records: Iterable[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        value = str(record[key])
        if value in result and result[value] != dict(record):
            raise PracticeBankValidationError(f"conflicting {key}: {value}")
        result[value] = copy.deepcopy(dict(record))
    return [result[value] for value in sorted(result)]
