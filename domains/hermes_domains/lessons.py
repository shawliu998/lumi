from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .contract import ContractError, validate_fixture


LESSON_SCHEMA_VERSION = "hermes.lesson.v1"
PACKAGE_SCHEMA_VERSION = "hermes.lesson-package.v1"
DEFAULT_LESSON_ROOT = Path(__file__).resolve().parents[1] / "lessons"
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class LessonValidationError(ValueError):
    """A lesson package is incomplete, inconsistent, or not safe to load."""


def _nonempty(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LessonValidationError(f"{context} must be a non-empty string")
    return value


def _exact_object(
    value: Any,
    *,
    required: set[str],
    context: str,
    optional: set[str] | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LessonValidationError(f"{context} must be an object")
    keys = set(value)
    missing = required - keys
    if missing:
        raise LessonValidationError(f"{context} missing required fields: {sorted(missing)}")
    unknown = keys - required - (optional or set())
    if unknown:
        raise LessonValidationError(f"{context} has unknown fields: {sorted(unknown)}")
    return value


def _string_list(value: Any, context: str, *, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise LessonValidationError(f"{context} must contain at least {minimum} item(s)")
    result = [_nonempty(item, f"{context} item") for item in value]
    if len(result) != len(set(result)):
        raise LessonValidationError(f"{context} must not contain duplicates")
    return result


def _positive_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LessonValidationError(f"{context} must be a positive integer")
    return value


def _normalise_prompt(value: str) -> str:
    return "".join(value.split()).casefold()


def _validate_method_card(value: Any) -> None:
    card = _exact_object(
        value,
        required={"definition", "formula", "applicability", "common_mistake"},
        context="method_card",
    )
    _nonempty(card["definition"], "method_card.definition")
    _nonempty(card["formula"], "method_card.formula")
    _string_list(card["applicability"], "method_card.applicability")
    mistake = _exact_object(
        card["common_mistake"],
        required={"label", "explanation"},
        context="method_card.common_mistake",
    )
    _nonempty(mistake["label"], "method_card.common_mistake.label")
    _nonempty(mistake["explanation"], "method_card.common_mistake.explanation")


def _validate_worked_example(value: Any) -> str:
    example = _exact_object(
        value,
        required={"example_id", "prompt", "steps", "hint_ladder", "answer"},
        context="worked_example",
    )
    _nonempty(example["example_id"], "worked_example.example_id")
    prompt = _nonempty(example["prompt"], "worked_example.prompt")
    _nonempty(example["answer"], "worked_example.answer")

    steps = example["steps"]
    if not isinstance(steps, list) or len(steps) < 2:
        raise LessonValidationError("worked_example.steps must contain at least two steps")
    step_ids: list[str] = []
    for index, raw_step in enumerate(steps, start=1):
        step = _exact_object(
            raw_step,
            required={"step_id", "instruction", "content"},
            context=f"worked_example.steps[{index}]",
        )
        step_ids.append(_nonempty(step["step_id"], f"worked_example.steps[{index}].step_id"))
        _nonempty(step["instruction"], f"worked_example.steps[{index}].instruction")
        _nonempty(step["content"], f"worked_example.steps[{index}].content")
    if len(step_ids) != len(set(step_ids)):
        raise LessonValidationError("worked_example step_id values must be unique")

    hints = example["hint_ladder"]
    if not isinstance(hints, list) or len(hints) < 2:
        raise LessonValidationError("worked_example.hint_ladder must contain at least two hints")
    levels: list[int] = []
    reveal_ranks: list[int] = []
    hint_prompts: list[str] = []
    for index, raw_hint in enumerate(hints, start=1):
        hint = _exact_object(
            raw_hint,
            required={"level", "label", "prompt", "reveal_rank"},
            context=f"worked_example.hint_ladder[{index}]",
        )
        levels.append(_positive_int(hint["level"], f"hint[{index}].level"))
        reveal_ranks.append(_positive_int(hint["reveal_rank"], f"hint[{index}].reveal_rank"))
        _nonempty(hint["label"], f"hint[{index}].label")
        hint_prompts.append(_nonempty(hint["prompt"], f"hint[{index}].prompt"))
    if levels != list(range(1, len(hints) + 1)):
        raise LessonValidationError("hint levels must be contiguous and start at 1")
    if any(left >= right for left, right in zip(reveal_ranks, reveal_ranks[1:])):
        raise LessonValidationError("hint ladder must progress from weak to strong")
    if len({_normalise_prompt(item) for item in hint_prompts}) != len(hint_prompts):
        raise LessonValidationError("hint prompts must be unique")
    return prompt


def _validate_mcq_fixture(
    fixture: Mapping[str, Any],
    *,
    lesson: Mapping[str, Any],
    fixture_index: int,
) -> tuple[str, str]:
    try:
        validate_fixture(fixture)
    except ContractError as exc:
        raise LessonValidationError(
            f"practice_fixtures[{fixture_index}] violates hermes.domain-fixture.v1: {exc}"
        ) from exc
    if fixture["domain"] != lesson["domain"] or fixture["path"] != lesson["path"]:
        raise LessonValidationError("practice fixture domain/path must match its lesson")
    if fixture["module"] != lesson["module"]:
        raise LessonValidationError("practice fixture module must match its lesson")
    if fixture["mode"] != "success" or fixture["scoring"].get("adapter") != "xingce_mcq_v1":
        raise LessonValidationError("lesson practice must use success-mode xingce_mcq_v1 fixtures")

    declared_skills = set(lesson["skill_ids"])
    fixture_skills = {item.get("skill_id") for item in fixture["skills"]}
    if fixture_skills != declared_skills:
        raise LessonValidationError("every practice fixture must cover the lesson skill_ids")

    task = fixture["task"]
    options = task.get("options")
    correct = fixture["scoring"].get("correct_option")
    if task.get("response_mode") != "single_choice" or not isinstance(options, Mapping):
        raise LessonValidationError("lesson practice task must be a single-choice item with options")
    if correct not in options:
        raise LessonValidationError("practice correct_option must reference a task option")

    verification = fixture["independent_verify"]
    pass_condition = verification.get("pass_condition")
    verify_options = pass_condition.get("options") if isinstance(pass_condition, Mapping) else None
    verify_correct = pass_condition.get("correct_option") if isinstance(pass_condition, Mapping) else None
    if verification.get("response_mode") != "single_choice" or not isinstance(verify_options, Mapping):
        raise LessonValidationError("independent verification must be a single-choice item with options")
    if verify_correct not in verify_options:
        raise LessonValidationError("verification correct_option must reference a verification option")

    provenance = fixture.get("provenance")
    if not isinstance(provenance, Mapping):
        raise LessonValidationError("practice fixture provenance must be an object")
    for field in ("authoring_note", "prior_source"):
        _nonempty(provenance.get(field), f"practice fixture provenance.{field}")
    if provenance.get("content_origin") != "synthetic_original":
        raise LessonValidationError("practice fixtures must be synthetic original content")
    if provenance.get("source_use") != "concept_structure_only":
        raise LessonValidationError("practice fixture source_use must be concept_structure_only")
    if provenance.get("source_text_included") is not False:
        raise LessonValidationError("practice fixtures must not include source text")
    return task["prompt"], verification["prompt"]


def _validate_completion_policy(value: Any, *, question_count: int) -> None:
    policy = _exact_object(
        value,
        required={
            "minimum_questions",
            "consecutive_verified_transfers",
            "lesson_reading_changes_mastery",
            "hinted_evidence_discount",
        },
        context="completion_policy",
    )
    minimum = _positive_int(policy["minimum_questions"], "completion_policy.minimum_questions")
    if minimum < 3:
        raise LessonValidationError("completion_policy.minimum_questions must be at least 3")
    if minimum > question_count:
        raise LessonValidationError("completion policy requires more questions than the lesson provides")
    if policy["consecutive_verified_transfers"] != 2:
        raise LessonValidationError("completion requires exactly two consecutive verified transfers")
    if policy["lesson_reading_changes_mastery"] is not False:
        raise LessonValidationError("reading a lesson must never change mastery")
    discount = policy["hinted_evidence_discount"]
    if isinstance(discount, bool) or not isinstance(discount, (int, float)) or not 0 < discount < 1:
        raise LessonValidationError("hinted_evidence_discount must be between 0 and 1")


def _validate_provenance(value: Any) -> None:
    provenance = _exact_object(
        value,
        required={
            "content_origin",
            "source_title",
            "source_page_range",
            "source_use",
            "rights_status",
            "source_text_included",
            "author",
            "authored_at",
            "review_status",
        },
        context="provenance",
    )
    if provenance["content_origin"] != "synthetic_original":
        raise LessonValidationError("lesson content_origin must be synthetic_original")
    _nonempty(provenance["source_title"], "provenance.source_title")
    page_range = _exact_object(
        provenance["source_page_range"],
        required={"pdf_start", "pdf_end", "printed_start", "printed_end"},
        context="provenance.source_page_range",
    )
    for field in ("pdf_start", "pdf_end", "printed_start", "printed_end"):
        _positive_int(page_range[field], f"provenance.source_page_range.{field}")
    if page_range["pdf_start"] > page_range["pdf_end"] or page_range["printed_start"] > page_range["printed_end"]:
        raise LessonValidationError("provenance source page ranges are invalid")
    if provenance["source_use"] != "concept_structure_only":
        raise LessonValidationError("source_use must be concept_structure_only")
    if provenance["rights_status"] != "internal_review_required":
        raise LessonValidationError("rights_status must be internal_review_required")
    if provenance["source_text_included"] is not False:
        raise LessonValidationError("source_text_included must be false")
    _nonempty(provenance["author"], "provenance.author")
    authored_at = _nonempty(provenance["authored_at"], "provenance.authored_at")
    if not _DATE.fullmatch(authored_at):
        raise LessonValidationError("provenance.authored_at must use YYYY-MM-DD")
    if provenance["review_status"] != "internal_review_required":
        raise LessonValidationError("review_status must be internal_review_required")


def validate_lesson(lesson: Mapping[str, Any]) -> None:
    """Fail closed on malformed, non-original, or pedagogically incomplete lessons."""

    lesson = _exact_object(
        lesson,
        required={
            "schema_version",
            "lesson_id",
            "version",
            "domain",
            "path",
            "module",
            "title",
            "estimated_minutes",
            "skill_ids",
            "method_card",
            "worked_example",
            "practice_fixtures",
            "completion_policy",
            "provenance",
        },
        context="lesson",
    )
    if lesson["schema_version"] != LESSON_SCHEMA_VERSION:
        raise LessonValidationError("unsupported lesson schema_version")
    _nonempty(lesson["lesson_id"], "lesson.lesson_id")
    version = _nonempty(lesson["version"], "lesson.version")
    if not _SEMVER.fullmatch(version):
        raise LessonValidationError("lesson.version must be semantic x.y.z")
    if lesson["domain"] not in {"xingce", "shenlun", "interview"}:
        raise LessonValidationError("lesson.domain is unsupported")
    for field in ("path", "module", "title"):
        _nonempty(lesson[field], f"lesson.{field}")
    estimated_minutes = _positive_int(lesson["estimated_minutes"], "lesson.estimated_minutes")
    if not 5 <= estimated_minutes <= 8:
        raise LessonValidationError("lesson.estimated_minutes must be between 5 and 8")
    skill_ids = _string_list(lesson["skill_ids"], "lesson.skill_ids")
    if len(skill_ids) != 1:
        raise LessonValidationError("a lesson must target exactly one knowledge component")
    _validate_method_card(lesson["method_card"])
    worked_prompt = _validate_worked_example(lesson["worked_example"])

    fixtures = lesson["practice_fixtures"]
    if not isinstance(fixtures, list) or len(fixtures) < 2:
        raise LessonValidationError("practice_fixtures must contain at least two complete fixtures")
    fixture_ids: list[str] = []
    assessment_prompts: list[str] = []
    for index, fixture in enumerate(fixtures):
        if not isinstance(fixture, Mapping):
            raise LessonValidationError(f"practice_fixtures[{index}] must be an object")
        task_prompt, verify_prompt = _validate_mcq_fixture(fixture, lesson=lesson, fixture_index=index)
        fixture_ids.append(fixture["fixture_id"])
        assessment_prompts.extend((task_prompt, verify_prompt))
    if len(fixture_ids) != len(set(fixture_ids)):
        raise LessonValidationError("practice fixture_id values must be unique")
    normalised = [_normalise_prompt(item) for item in assessment_prompts]
    if len(normalised) != len(set(normalised)):
        raise LessonValidationError("practice and independent verification questions must all be different")
    if _normalise_prompt(worked_prompt) in set(normalised):
        raise LessonValidationError("worked example must differ from every practice and verification question")

    _validate_completion_policy(lesson["completion_policy"], question_count=len(assessment_prompts))
    _validate_provenance(lesson["provenance"])


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LessonValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json(raw: bytes, path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                LessonValidationError(f"non-finite JSON value: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LessonValidationError(f"invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LessonValidationError(f"{path.name} must contain a JSON object")
    return parsed


def _validate_manifest(value: Any) -> list[Mapping[str, Any]]:
    manifest = _exact_object(
        value,
        required={"schema_version", "package_id", "version", "created_at", "lessons"},
        context="lesson manifest",
    )
    if manifest["schema_version"] != PACKAGE_SCHEMA_VERSION:
        raise LessonValidationError("unsupported lesson manifest schema_version")
    _nonempty(manifest["package_id"], "lesson manifest.package_id")
    version = _nonempty(manifest["version"], "lesson manifest.version")
    if not _SEMVER.fullmatch(version):
        raise LessonValidationError("lesson manifest.version must be semantic x.y.z")
    created_at = _nonempty(manifest["created_at"], "lesson manifest.created_at")
    if not _DATE.fullmatch(created_at):
        raise LessonValidationError("lesson manifest.created_at must use YYYY-MM-DD")
    entries = manifest["lessons"]
    if not isinstance(entries, list) or not entries:
        raise LessonValidationError("lesson manifest must list at least one lesson")
    ids: list[str] = []
    paths: list[str] = []
    for index, raw_entry in enumerate(entries):
        entry = _exact_object(
            raw_entry,
            required={"lesson_id", "version", "path", "sha256"},
            context=f"lesson manifest.lessons[{index}]",
        )
        ids.append(_nonempty(entry["lesson_id"], f"manifest lesson[{index}].lesson_id"))
        entry_version = _nonempty(entry["version"], f"manifest lesson[{index}].version")
        if not _SEMVER.fullmatch(entry_version):
            raise LessonValidationError("manifest lesson version must be semantic x.y.z")
        relative = _nonempty(entry["path"], f"manifest lesson[{index}].path")
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix != ".json":
            raise LessonValidationError("manifest lesson path must be a safe relative JSON path")
        if candidate.name == "manifest.json":
            raise LessonValidationError("manifest cannot list itself as a lesson")
        paths.append(relative)
        checksum = _nonempty(entry["sha256"], f"manifest lesson[{index}].sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise LessonValidationError("manifest sha256 must be 64 lowercase hexadecimal characters")
    if len(ids) != len(set(ids)):
        raise LessonValidationError("lesson IDs must be unique within the package")
    if len(paths) != len(set(paths)):
        raise LessonValidationError("lesson paths must be unique within the package")
    return entries


def _load_package(root: Path) -> tuple[list[dict[str, Any]], dict[Path, dict[str, Any]]]:
    root = root.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise LessonValidationError("lesson manifest.json is missing")
    manifest = _parse_json(manifest_path.read_bytes(), manifest_path)
    entries = _validate_manifest(manifest)

    listed_paths = {manifest_path.resolve()}
    documents: list[dict[str, Any]] = []
    by_path: dict[Path, dict[str, Any]] = {}
    for entry in entries:
        path = (root / entry["path"]).resolve()
        if root not in path.parents or not path.is_file():
            raise LessonValidationError("manifest lesson path escapes the root or does not exist")
        listed_paths.add(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise LessonValidationError(f"lesson checksum mismatch: {entry['path']}")
        document = _parse_json(raw, path)
        validate_lesson(document)
        if document["lesson_id"] != entry["lesson_id"] or document["version"] != entry["version"]:
            raise LessonValidationError("manifest identity/version does not match lesson document")
        documents.append(document)
        by_path[path] = document

    actual_json = {path.resolve() for path in root.rglob("*.json")}
    unexpected = actual_json - listed_paths
    if unexpected:
        names = sorted(str(path.relative_to(root)) for path in unexpected)
        raise LessonValidationError(f"unlisted lesson JSON files are not allowed: {names}")
    return documents, by_path


def load_lesson_catalog(lesson_root: Path | None = None) -> list[dict[str, Any]]:
    """Load every manifest-pinned lesson after integrity and semantic validation."""

    documents, _ = _load_package(lesson_root or DEFAULT_LESSON_ROOT)
    return copy.deepcopy(documents)


def load_lesson_document(
    path_or_id: Path | str,
    *,
    lesson_root: Path | None = None,
) -> dict[str, Any]:
    """Load one manifest-authorized lesson by lesson ID or JSON path."""

    root = (lesson_root or DEFAULT_LESSON_ROOT).resolve()
    documents, by_path = _load_package(root)
    if isinstance(path_or_id, Path) or str(path_or_id).endswith(".json") or "/" in str(path_or_id):
        requested = Path(path_or_id)
        requested = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
        document = by_path.get(requested)
    else:
        document = next((item for item in documents if item["lesson_id"] == path_or_id), None)
    if document is None:
        raise LessonValidationError(f"lesson is not listed in the manifest: {path_or_id}")
    return copy.deepcopy(document)
