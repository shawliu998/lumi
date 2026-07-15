from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .practice_v3_common import (
    BANK_ID,
    BANK_VERSION,
    GENERATOR_VERSION,
    MIXED_SCOPE_ID,
    MODULE_LABELS,
    MODULE_ORDER,
    MODULE_SCOPES,
    QUESTIONS_PER_MODULE,
    PracticeBankValidationError,
    canonical_digest,
    cause_records,
    intervention_records,
    signature_record,
    unique_records,
    validate_generated_module,
)
from .practice_v3_data_analysis import (
    UNITS as DATA_ANALYSIS_UNITS,
    generate_data_analysis_bank,
    verify_data_analysis_question,
)
from .practice_v3_judgment import JUDGMENT_UNITS, generate_judgment_bank, verify_judgment_question
from .practice_v3_quantitative import (
    UNITS as QUANTITATIVE_UNITS,
    generate_quantitative_bank,
    verify_quantitative_question,
)
from .practice_v3_verbal import VERBAL_UNITS, generate_verbal_bank, verify_verbal_question


MANIFEST_SCHEMA_VERSION = "lumi.practice-bank-manifest.v3"
BANK_SCHEMA_VERSION = "lumi.practice-bank.v3"
DEFAULT_PRACTICE_BANK_ROOT = Path(__file__).resolve().parents[1] / "practice_v3"
DEFAULT_SCOPE_ID = MODULE_SCOPES["data-analysis"]
EXPECTED_TOTAL = QUESTIONS_PER_MODULE * len(MODULE_ORDER)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

_CONTENT_SOURCE_FIELDS = {
    "content_source_id",
    "content_origin",
    "reference_title",
    "reference_page_range",
    "covered_modules",
    "source_use",
    "source_text_included",
    "rights_status",
    "authorization_status",
    "review_status",
    "authored_at",
}
_EXPECTED_SOURCE_COVERAGE = {
    "src.lumi.core320.wen-structure": [
        MODULE_SCOPES["verbal"],
        MODULE_SCOPES["judgment"],
    ],
    "src.lumi.core320.li-structure": [
        MODULE_SCOPES["quantitative"],
        MODULE_SCOPES["data-analysis"],
    ],
}


_GENERATORS = {
    "verbal": (generate_verbal_bank, verify_verbal_question, VERBAL_UNITS),
    "judgment": (generate_judgment_bank, verify_judgment_question, JUDGMENT_UNITS),
    "quantitative": (
        generate_quantitative_bank,
        verify_quantitative_question,
        QUANTITATIVE_UNITS,
    ),
    "data-analysis": (
        generate_data_analysis_bank,
        verify_data_analysis_question,
        DATA_ANALYSIS_UNITS,
    ),
}


def _validate_content_sources(sources: Any) -> None:
    if not isinstance(sources, list) or len(sources) != 2:
        raise PracticeBankValidationError("practice-v3 requires two explicit concept references")
    source_ids: list[str] = []
    covered_modules: list[str] = []
    for source in sources:
        if not isinstance(source, Mapping) or set(source) != _CONTENT_SOURCE_FIELDS:
            raise PracticeBankValidationError("content source record is malformed")
        source_id = source["content_source_id"]
        if source_id not in _EXPECTED_SOURCE_COVERAGE:
            raise PracticeBankValidationError("content source ID is not supported")
        source_ids.append(source_id)
        if source.get("content_origin") != "synthetic_original":
            raise PracticeBankValidationError("all generated content must be original synthetic content")
        if not isinstance(source.get("reference_title"), str) or not source["reference_title"].strip():
            raise PracticeBankValidationError("content source title cannot be blank")
        page_range = source.get("reference_page_range")
        if not isinstance(page_range, Mapping) or set(page_range) != {
            "pdf_start",
            "pdf_end",
            "printed_start",
            "printed_end",
        }:
            raise PracticeBankValidationError("content source page range is malformed")
        for prefix in ("pdf", "printed"):
            start, end = page_range[f"{prefix}_start"], page_range[f"{prefix}_end"]
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 1
                or end < start
            ):
                raise PracticeBankValidationError("content source page range is invalid")
        expected_coverage = _EXPECTED_SOURCE_COVERAGE[source_id]
        if source.get("covered_modules") != expected_coverage:
            raise PracticeBankValidationError("content source module coverage is invalid")
        covered_modules.extend(expected_coverage)
        if source.get("source_use") != "concept_structure_reference":
            raise PracticeBankValidationError("PDF use must remain limited to concept structure")
        if source.get("source_text_included") is not False:
            raise PracticeBankValidationError("PDF source text must never enter the generated bank")
        if source.get("rights_status") != "rights_review_required":
            raise PracticeBankValidationError("content source rights gate cannot be removed")
        if source.get("authorization_status") != "internal_mvp_only":
            raise PracticeBankValidationError("unreviewed content must remain internal-only")
        if source.get("review_status") != "human_review_required_before_external_release":
            raise PracticeBankValidationError("external content review marker cannot be removed")
        if not isinstance(source.get("authored_at"), str) or not _ISO_DATE.fullmatch(source["authored_at"]):
            raise PracticeBankValidationError("content source authored date is invalid")
    if source_ids != list(_EXPECTED_SOURCE_COVERAGE) or len(source_ids) != len(set(source_ids)):
        raise PracticeBankValidationError("content source order and IDs must be deterministic")
    if set(covered_modules) != set(MODULE_SCOPES.values()):
        raise PracticeBankValidationError("content sources must cover all four modules exactly")


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root.resolve() / "manifest.json"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PracticeBankValidationError(f"practice-v3 manifest is unavailable: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PracticeBankValidationError(f"practice-v3 manifest is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise PracticeBankValidationError("practice-v3 manifest must be an object")
    required = {
        "schema_version",
        "bank_id",
        "version",
        "generator_version",
        "status",
        "expected_question_count",
        "expected_module_counts",
        "generated_sha256",
        "content_sources",
    }
    if set(value) != required:
        raise PracticeBankValidationError("practice-v3 manifest fields do not match the v3 contract")
    if value["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise PracticeBankValidationError("unsupported practice-v3 manifest schema")
    if value["bank_id"] != BANK_ID or value["version"] != BANK_VERSION:
        raise PracticeBankValidationError("practice-v3 bank identity is not supported")
    if value["generator_version"] != GENERATOR_VERSION:
        raise PracticeBankValidationError("practice-v3 generator version is not supported")
    if value["status"] != "published_internal":
        raise PracticeBankValidationError("only internally published banks may load")
    if value["expected_question_count"] != EXPECTED_TOTAL:
        raise PracticeBankValidationError("core practice bank must contain exactly 320 questions")
    expected_counts = {MODULE_SCOPES[module]: QUESTIONS_PER_MODULE for module in MODULE_ORDER}
    if value["expected_module_counts"] != expected_counts:
        raise PracticeBankValidationError("practice-v3 module counts must be 80 each")
    if not isinstance(value["generated_sha256"], str) or not _SHA256.fullmatch(value["generated_sha256"]):
        raise PracticeBankValidationError("practice-v3 generated SHA-256 is invalid")
    _validate_content_sources(value["content_sources"])
    return value


def _scope_records(units_by_module: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    all_unit_ids: list[str] = []
    for module in MODULE_ORDER:
        unit_ids = sorted(spec.diagnostic_unit_id for spec in units_by_module[module])
        all_unit_ids.extend(unit_ids)
        result.append(
            {
                "scope_id": MODULE_SCOPES[module],
                "title": f"{MODULE_LABELS[module]} · 固定8题",
                "module_label": MODULE_LABELS[module],
                "question_count": QUESTIONS_PER_MODULE,
                "diagnostic_unit_ids": unit_ids,
            }
        )
    result.append(
        {
            "scope_id": MIXED_SCOPE_ID,
            "title": "四模块混合 · 固定8题",
            "module_label": "行测混合",
            "question_count": EXPECTED_TOTAL,
            "diagnostic_unit_ids": sorted(all_unit_ids),
        }
    )
    return result


def _digest_payload(bank: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": bank["schema_version"],
        "bank_id": bank["bank_id"],
        "version": bank["version"],
        "generator_version": bank["generator_version"],
        "status": bank["status"],
        "content_sources": bank["content_sources"],
        "scopes": bank["scopes"],
        "error_signatures": bank["error_signatures"],
        "cause_candidates": bank["cause_candidates"],
        "interventions": bank["interventions"],
        "questions": bank["questions"],
    }


def generate_practice_bank(*, content_sources: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    normalized_sources = [dict(item) for item in content_sources]
    _validate_content_sources(normalized_sources)
    units_by_module: dict[str, Sequence[Any]] = {}
    all_questions: list[dict[str, Any]] = []
    all_units: list[Any] = []
    for module in MODULE_ORDER:
        generator, verifier, declared_units = _GENERATORS[module]
        units, questions = generator()
        if (
            tuple(units) != tuple(declared_units)
            or len(units) != 8
            or len(questions) != QUESTIONS_PER_MODULE
        ):
            raise PracticeBankValidationError(f"{module} generator did not produce 8 x 10 questions")
        for question in questions:
            verifier(question)
        units_by_module[module] = tuple(units)
        all_units.extend(units)
        all_questions.extend(copy.deepcopy(list(questions)))

    signatures = unique_records((signature_record(spec) for spec in all_units), "signature_id")
    causes = unique_records(
        (record for spec in all_units for record in cause_records(spec)),
        "cause_id",
    )
    tutorials: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    for spec in all_units:
        tutorial, unit_probes = intervention_records(spec)
        tutorials.append(tutorial)
        probes.extend(unit_probes)
    interventions = {
        "microtutorials": unique_records(tutorials, "asset_id"),
        "probes": unique_records(probes, "asset_id"),
    }
    bank = {
        "schema_version": BANK_SCHEMA_VERSION,
        "bank_id": BANK_ID,
        "version": BANK_VERSION,
        "generator_version": GENERATOR_VERSION,
        "status": "published_internal",
        "content_sources": copy.deepcopy(normalized_sources),
        "scopes": _scope_records(units_by_module),
        "error_signatures": signatures,
        "cause_candidates": causes,
        "interventions": interventions,
        "questions": sorted(all_questions, key=lambda item: item["question_id"]),
    }
    validate_practice_bank(bank)
    return bank


def validate_practice_bank(bank: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "bank_id", "version", "generator_version", "status",
        "content_sources", "scopes", "error_signatures", "cause_candidates",
        "interventions", "questions",
    }
    if set(bank) != required:
        raise PracticeBankValidationError("generated bank fields do not match the v3 contract")
    if (
        bank["schema_version"] != BANK_SCHEMA_VERSION
        or bank["bank_id"] != BANK_ID
        or bank["version"] != BANK_VERSION
        or bank["generator_version"] != GENERATOR_VERSION
        or bank["status"] != "published_internal"
    ):
        raise PracticeBankValidationError("generated bank identity is invalid")
    _validate_content_sources(bank["content_sources"])
    questions = bank["questions"]
    if not isinstance(questions, list) or len(questions) != EXPECTED_TOTAL:
        raise PracticeBankValidationError("generated bank must contain exactly 320 questions")
    ids = [item["question_id"] for item in questions]
    prompts = ["".join(str(item["prompt"]).split()).casefold() for item in questions]
    if len(ids) != len(set(ids)) or len(prompts) != len(set(prompts)):
        raise PracticeBankValidationError("question IDs and normalized prompts must be globally unique")
    if ids != sorted(ids):
        raise PracticeBankValidationError("question versions must remain in deterministic ID order")
    material_ids = [item.get("material_group_id") for item in questions]
    if len(material_ids) != len(set(material_ids)):
        raise PracticeBankValidationError("independent question stimuli must have unique material groups")
    source_ids = {
        item.get("content_source_id")
        for item in bank["content_sources"]
        if isinstance(item, Mapping)
    }
    if any(item["content_source_id"] not in source_ids for item in questions):
        raise PracticeBankValidationError("a generated question references an unknown content source")
    units_by_module = {
        module: tuple(_GENERATORS[module][2]) for module in MODULE_ORDER
    }
    for module in MODULE_ORDER:
        selected = [item for item in questions if item["module_id"] == MODULE_SCOPES[module]]
        if len(selected) != QUESTIONS_PER_MODULE:
            raise PracticeBankValidationError(f"{module} must contain exactly 80 questions")
        verifier = _GENERATORS[module][1]
        validate_generated_module(module, units_by_module[module], selected, verifier)
        key_counts = {
            key: sum(item["scoring"]["correct_option"] == key for item in selected)
            for key in "ABCD"
        }
        if set(key_counts.values()) != {QUESTIONS_PER_MODULE // 4}:
            raise PracticeBankValidationError(f"{module} answer keys are not balanced: {key_counts}")
    scopes = bank["scopes"]
    if scopes != _scope_records(units_by_module):
        raise PracticeBankValidationError("generated bank scope catalog is inconsistent")

    all_units = [spec for module in MODULE_ORDER for spec in units_by_module[module]]
    expected_signatures = unique_records(
        (signature_record(spec) for spec in all_units),
        "signature_id",
    )
    expected_causes = unique_records(
        (record for spec in all_units for record in cause_records(spec)),
        "cause_id",
    )
    tutorials: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    for spec in all_units:
        tutorial, unit_probes = intervention_records(spec)
        tutorials.append(tutorial)
        probes.extend(unit_probes)
    expected_interventions = {
        "microtutorials": unique_records(tutorials, "asset_id"),
        "probes": unique_records(probes, "asset_id"),
    }
    if bank["error_signatures"] != expected_signatures:
        raise PracticeBankValidationError("error-signature catalog is inconsistent")
    if bank["cause_candidates"] != expected_causes:
        raise PracticeBankValidationError("cause-candidate catalog is inconsistent")
    if bank["interventions"] != expected_interventions:
        raise PracticeBankValidationError("intervention catalog is inconsistent")


def load_practice_bank(practice_root: Path | None = None) -> dict[str, Any]:
    manifest = _load_manifest(practice_root or DEFAULT_PRACTICE_BANK_ROOT)
    bank = generate_practice_bank(content_sources=manifest["content_sources"])
    digest = canonical_digest(_digest_payload(bank))
    if digest != manifest["generated_sha256"]:
        raise PracticeBankValidationError(
            "generated practice bank differs from the manifest-pinned QuestionVersions"
        )
    bank["generated_sha256"] = digest
    return copy.deepcopy(bank)


def load_scope_catalog(practice_root: Path | None = None) -> list[dict[str, Any]]:
    bank = load_practice_bank(practice_root)
    return copy.deepcopy(bank["scopes"])


def resolve_scope(scope_id: str, practice_root: Path | None = None) -> dict[str, Any]:
    bank = load_practice_bank(practice_root)
    scope = next((item for item in bank["scopes"] if item["scope_id"] == scope_id), None)
    if scope is None:
        raise PracticeBankValidationError(f"unknown practice scope: {scope_id}")
    return copy.deepcopy(scope)


def safe_bank_catalog(practice_root: Path | None = None) -> dict[str, Any]:
    bank = load_practice_bank(practice_root)
    return {
        "schema_version": "lumi.practice-scope-catalog.v1",
        "bank_id": bank["bank_id"],
        "version": bank["version"],
        "generated_sha256": bank["generated_sha256"],
        "question_count": len(bank["questions"]),
        "default_scope_id": DEFAULT_SCOPE_ID,
        "scopes": copy.deepcopy(bank["scopes"]),
    }
