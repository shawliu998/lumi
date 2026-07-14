#!/usr/bin/env python3
"""Validate P0.3 fixtures and schema-version vocabulary isolation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from generate_fixtures import (
    EVALUATION_FIXTURE_EVIDENCE_ORIGIN,
    FIXTURE_GENERATOR_VERSION,
    ID_NAMESPACE_FORMULA,
    ID_NAMESPACE_VERSION,
    PASTED_TEXT,
    make_case,
)
from lumi_study_pack.models import GENERATOR_ID
from lumi_study_pack.parsing import parse_pasted_text, parse_text_pdf


ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "evals" / "contracts"
FIXTURES = Path(__file__).resolve().parent


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validator(schema: dict[str, Any]) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def top_schema_version(schema: dict[str, Any]) -> str | None:
    return schema.get("properties", {}).get("schema_version", {}).get("const")


def unique_top_schema_version_owners(
    schemas: dict[str, dict[str, Any]],
) -> dict[str, str]:
    owners: dict[str, list[str]] = {}
    for schema_name, schema in schemas.items():
        version = top_schema_version(schema)
        if version is not None:
            owners.setdefault(version, []).append(schema_name)
    duplicates = {
        version: sorted(schema_names)
        for version, schema_names in owners.items()
        if len(schema_names) != 1
    }
    if duplicates:
        raise AssertionError(
            f"top-level schema_version has multiple vocabulary owners: {duplicates}"
        )
    return {version: schema_names[0] for version, schema_names in owners.items()}


def validate_generator_reproducibility() -> dict[str, int]:
    pasted_text = (FIXTURES / "pasted_text.txt").read_text(encoding="utf-8")
    if pasted_text != PASTED_TEXT:
        raise AssertionError("stored pasted-text input drifted from the generator source")
    case_specs = (
        (
            "pasted_text.case.json",
            "pasted_text.source.json",
            "pasted-text-chinese-v1",
            parse_pasted_text(pasted_text),
            "资料分析基本规则",
        ),
        (
            "text_bearing_chinese.case.json",
            "text_bearing_chinese.source.json",
            "text-pdf-chinese-v1",
            parse_text_pdf((FIXTURES / "text_bearing_chinese.pdf").read_bytes()),
            "证据式学习规则",
        ),
    )
    compared_spans = 0
    compared_artifacts = 0
    compared_links = 0
    compared_decisions = 0
    pdf_semantic_practice_items = 0
    pdf_semantic_assertion_groups = 0
    pdf_semantic_negative_probes = 0
    for path_name, source_path_name, case_name, parsed, title in case_specs:
        stored = load(FIXTURES / path_name)
        rebuilt = make_case(case_name, parsed, title)
        if load(FIXTURES / source_path_name) != stored.get("source_document"):
            raise AssertionError(
                f"standalone source document drifted from its case: {path_name}"
            )
        compared_fields = (
            "source_document",
            "source_spans",
            "pack",
            "artifacts",
            "private_artifact_contents",
            "candidate_skill_links",
            "verifier_decisions",
            "scorer_vector",
            "fixture_semantics",
        )
        mismatches = [
            field for field in compared_fields if stored.get(field) != rebuilt.get(field)
        ]
        if mismatches:
            raise AssertionError(
                f"current generator cannot reproduce {path_name}: {mismatches}"
            )
        if canonical_digest(stored) != canonical_digest(rebuilt):
            raise AssertionError(
                f"current generator cannot reproduce the complete case: {path_name}"
            )
        reviewed_digest = stored["pack"]["verifier_summary"][
            "reviewed_content_digest"
        ]
        rebuilt_digest = rebuilt["pack"]["verifier_summary"][
            "reviewed_content_digest"
        ]
        if reviewed_digest != rebuilt_digest:
            raise AssertionError(f"artifact-set digest drifted: {path_name}")
        if path_name == "text_bearing_chinese.case.json":
            pdf_semantic_practice_items = validate_real_pdf_semantics(stored)
            pdf_semantic_assertion_groups = 6
            pdf_semantic_negative_probes = (
                validate_real_pdf_semantic_negative_probes(stored)
            )
        compared_spans += len(stored["source_spans"])
        compared_artifacts += len(stored["artifacts"])
        compared_links += len(stored["candidate_skill_links"])
        compared_decisions += len(stored["verifier_decisions"])
    return {
        "reproducible_cases": len(case_specs),
        "reproducible_spans": compared_spans,
        "reproducible_artifacts": compared_artifacts,
        "reproducible_links": compared_links,
        "reproducible_decisions": compared_decisions,
        "reproducible_artifact_set_digests": len(case_specs),
        "reproducible_scorer_vectors": len(case_specs),
        "pdf_semantic_practice_items": pdf_semantic_practice_items,
        "pdf_semantic_assertion_groups": pdf_semantic_assertion_groups,
        "pdf_semantic_negative_probes": pdf_semantic_negative_probes,
    }


def validate_real_pdf_semantics(case: dict[str, Any]) -> int:
    private_contents = [
        item["content"] for item in case["private_artifact_contents"]
    ]
    note = next(
        item
        for item in private_contents
        if item.get("schema_version") == "study_pack.one_page_notes.v1"
    )
    practices = [
        item
        for item in private_contents
        if item.get("schema_version") == "study_pack.practice_item.v1"
    ]
    claims = note.get("claims")
    if not isinstance(claims, list) or len(claims) < 3:
        raise AssertionError("real PDF has fewer than three substantive claims")
    if len(claims) != len(set(claims)):
        raise AssertionError("real PDF claims are not exactly deduplicated")
    if "Lumi 学习材料" in claims:
        raise AssertionError("real PDF page title leaked into claims")
    explanations = [item.get("explanation") for item in practices]
    if len(practices) != 3 or len(explanations) != len(set(explanations)):
        raise AssertionError("real PDF practice explanations are not three distinct claims")
    if not all(
        isinstance(item, str)
        and len(item) >= 12
        and item.endswith(("。", "！", "？"))
        and item != "Lumi 学习材料"
        for item in explanations
    ):
        raise AssertionError("real PDF practice explanation is not substantive body text")
    for index, practice in enumerate(practices, start=1):
        expected_prompt = f"根据本地材料，完整输入第 {index} 条核心表述。"
        if practice.get("item_kind") != "normalized_exact_v1":
            raise AssertionError("real Chinese PDF used an unsafe cloze transform")
        if practice.get("prompt") != expected_prompt:
            raise AssertionError("real Chinese PDF practice prompt is not readable")
        if practice.get("answer") != practice.get("explanation"):
            raise AssertionError("normalized-exact answer drifted from its cited statement")
        if practice["answer"] in practice["prompt"]:
            raise AssertionError("real PDF answer leaked into its prompt")
    return len(practices)


def validate_real_pdf_semantic_negative_probes(case: dict[str, Any]) -> int:
    probes: list[dict[str, Any]] = []

    insufficient = copy.deepcopy(case)
    _private_content(insufficient, "study_pack.one_page_notes.v1")["claims"] = (
        _private_content(insufficient, "study_pack.one_page_notes.v1")["claims"][:2]
    )
    probes.append(insufficient)

    page_chrome = copy.deepcopy(case)
    _private_content(page_chrome, "study_pack.one_page_notes.v1")["claims"][0] = (
        "Lumi 学习材料"
    )
    probes.append(page_chrome)

    duplicate_explanation = copy.deepcopy(case)
    duplicate_practices = _private_practices(duplicate_explanation)
    duplicate_practices[1]["explanation"] = duplicate_practices[0]["explanation"]
    probes.append(duplicate_explanation)

    unsafe_cloze = copy.deepcopy(case)
    unsafe_practice = _private_practices(unsafe_cloze)[0]
    unsafe_practice["item_kind"] = "cloze_exact_v1"
    unsafe_practice["prompt"] = "材料填空 1：证据定位要求回____到材料中的原句。"
    unsafe_practice["answer"] = "答前先找"
    probes.append(unsafe_cloze)

    unreadable_prompt = copy.deepcopy(case)
    _private_practices(unreadable_prompt)[0]["prompt"] = "请输入答案。"
    probes.append(unreadable_prompt)

    answer_leak = copy.deepcopy(case)
    leaked_practice = _private_practices(answer_leak)[0]
    leaked_practice["prompt"] = leaked_practice["answer"]
    probes.append(answer_leak)

    for index, probe in enumerate(probes, start=1):
        try:
            validate_real_pdf_semantics(probe)
        except AssertionError:
            continue
        raise AssertionError(f"real PDF semantic negative probe {index} was accepted")
    return len(probes)


def _private_content(case: dict[str, Any], schema_version: str) -> dict[str, Any]:
    return next(
        item["content"]
        for item in case["private_artifact_contents"]
        if item["content"].get("schema_version") == schema_version
    )


def _private_practices(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item["content"]
        for item in case["private_artifact_contents"]
        if item["content"].get("schema_version")
        == "study_pack.practice_item.v1"
    ]


def main() -> int:
    schemas = {
        path.stem.removesuffix(".schema"): load(path)
        for path in CONTRACTS.glob("study-*.schema.json")
    }
    schemas["source-document"] = load(CONTRACTS / "source-document.schema.json")
    schemas["source-span"] = load(CONTRACTS / "source-span.schema.json")
    validators = {name: validator(schema) for name, schema in schemas.items()}

    version_owners = {
        "lumi.study-pack.v1": "study-pack",
        "lumi.study-pack-detail.v1": "study-pack-detail",
        "lumi.study-pack-attempt.v1": "study-pack-attempt",
        "lumi.study-pack-attempt-result.v1": "study-pack-attempt-result",
    }
    all_owners = unique_top_schema_version_owners(schemas)
    actual_owners = {
        version: all_owners.get(version) for version in version_owners
    }
    if actual_owners != version_owners:
        raise AssertionError(
            f"top-level schema-version ownership drifted: {actual_owners}"
        )
    duplicate_probe = dict(schemas)
    duplicate_probe["deliberate-study-pack-duplicate"] = copy.deepcopy(
        schemas["study-pack"]
    )
    try:
        unique_top_schema_version_owners(duplicate_probe)
    except AssertionError:
        schema_version_duplicate_negative_probes = 1
    else:
        raise AssertionError("duplicate schema_version negative probe was accepted")

    canonical_pack = schemas["study-pack"]
    detail = schemas["study-pack-detail"]
    canonical_pack_fields = set(canonical_pack["properties"])
    detail_fields = set(detail["properties"])
    if not {"source_ref", "artifact_refs", "verifier_summary"}.issubset(
        canonical_pack_fields
    ):
        raise AssertionError("canonical Study Pack ref vocabulary is incomplete")
    if {"source", "artifacts", "review"}.intersection(canonical_pack_fields):
        raise AssertionError("canonical Study Pack schema absorbed detail fields")
    if not {"source", "artifacts", "review"}.issubset(detail_fields):
        raise AssertionError("learner-facing detail vocabulary is incomplete")
    if {"source_ref", "artifact_refs", "verifier_summary"}.intersection(
        detail_fields
    ):
        raise AssertionError("detail schema absorbed canonical ref fields")

    canonical_attempt = schemas["study-pack-attempt"]
    result = schemas["study-pack-attempt-result"]
    nested_attempt = result["$defs"]["attempt"]
    if canonical_attempt["properties"] != nested_attempt["properties"]:
        raise AssertionError("nested canonical PracticeAttempt vocabulary drifted")
    if set(canonical_attempt["required"]) != set(nested_attempt["required"]):
        raise AssertionError("nested canonical PracticeAttempt required fields drifted")
    if not {"attempt", "result", "answer", "explanation", "links"}.issubset(
        result["properties"]
    ):
        raise AssertionError("attempt-result wrapper is incomplete")
    if {"result", "answer", "explanation", "links"}.intersection(
        canonical_attempt["properties"]
    ):
        raise AssertionError("canonical PracticeAttempt absorbed result-wrapper fields")
    attempt_probe = {
        "schema_version": "lumi.study-pack-attempt.v1",
        "attempt_id": "t_" + "A" * 40,
        "pack_id": "p_" + "A" * 40,
        "artifact_id": "a_" + "A" * 40,
        "artifact_version": 1,
        "answer_digest": "0" * 64,
        "correct": True,
        "score": 1.0,
        "activity_kind": "within_pack_practice",
        "scorer_id": "normalized_exact_v1@1.0.0",
    }
    for evidence_origin in (
        "human_local_interactive",
        EVALUATION_FIXTURE_EVIDENCE_ORIGIN,
    ):
        validators["study-pack-attempt"].validate(
            {**attempt_probe, "evidence_origin": evidence_origin}
        )
    invalid_origin_probe = {
        **attempt_probe,
        "evidence_origin": "synthetic_from_request",
    }
    if not list(
        validators["study-pack-attempt"].iter_errors(invalid_origin_probe)
    ):
        raise AssertionError("undeclared PracticeAttempt evidence origin was accepted")
    attempt_origin_validated_instances = 2
    attempt_origin_negative_probes = 1

    practice_content = detail["$defs"]["practice_content"]
    if practice_content.get("additionalProperties") is not False:
        raise AssertionError("practice detail content is not closed")
    if set(practice_content["properties"]) != {
        "schema_version",
        "item_kind",
        "prompt",
        "scorer",
    }:
        raise AssertionError("practice detail exposes private answer material")

    validated_instances = attempt_origin_validated_instances
    negative_probes = (
        schema_version_duplicate_negative_probes + attempt_origin_negative_probes
    )
    synthetic_evaluation_fixture_vectors = 0
    for case_path in sorted(FIXTURES.glob("*.case.json")):
        case = load(case_path)
        encoded = json.dumps(
            case, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        forbidden = (
            '"evidence_origin":"human_local_interactive"',
            '"practice_attempt"',
            '"attempt_id"',
            '"schema_version":"lumi.study-pack-detail.v1"',
            '"schema_version":"lumi.study-pack-attempt-result.v1"',
        )
        if any(token in encoded for token in forbidden):
            raise AssertionError(f"synthetic case impersonates a product record: {case_path}")
        if re.search(r'"t_[A-P]{40}"', encoded):
            raise AssertionError(f"synthetic case contains a product attempt ID: {case_path}")

        mappings = (
            ("source-document", [case["source_document"]]),
            ("source-span", case["source_spans"]),
            ("study-pack", [case["pack"]]),
            ("study-artifact", case["artifacts"]),
            (
                "study-artifact-content",
                [item["content"] for item in case["private_artifact_contents"]],
            ),
            ("study-candidate-skill-link", case["candidate_skill_links"]),
            ("study-verifier-decision", case["verifier_decisions"]),
        )
        for schema_name, instances in mappings:
            for instance in instances:
                validators[schema_name].validate(instance)
                validated_instances += 1
                invalid = copy.deepcopy(instance)
                invalid["_unexpected"] = "closed-schema-probe"
                if not list(validators[schema_name].iter_errors(invalid)):
                    raise AssertionError(f"{schema_name} accepted an unknown field")
                negative_probes += 1

        if not list(validators["study-pack-detail"].iter_errors(case["pack"])):
            raise AssertionError("canonical fixture also validates as Study Pack detail")
        negative_probes += 1
        scorer_vector = case["scorer_vector"]
        fixture_semantics = case.get("fixture_semantics", {})
        if (
            scorer_vector.get("synthetic_test_input") is not True
            or scorer_vector.get("evidence_origin")
            != EVALUATION_FIXTURE_EVIDENCE_ORIGIN
            or scorer_vector.get("product_attempt_record") is not False
            or scorer_vector.get("human_learner_projection_eligible") is not False
            or fixture_semantics.get("synthetic") is not True
            or fixture_semantics.get("attempt_evidence_origin")
            != EVALUATION_FIXTURE_EVIDENCE_ORIGIN
            or fixture_semantics.get("human_learner_projection_eligible") is not False
        ):
            raise AssertionError(
                f"synthetic case is not evaluation-only: {case_path}"
            )
        synthetic_evaluation_fixture_vectors += 1
        if not list(validators["study-pack-attempt"].iter_errors(scorer_vector)):
            raise AssertionError("synthetic scorer vector validates as PracticeAttempt")
        if not list(
            validators["study-pack-attempt-result"].iter_errors(scorer_vector)
        ):
            raise AssertionError("synthetic scorer vector validates as attempt result")
        negative_probes += 2

        private = {
            item["artifact_id"]: item["content"]
            for item in case["private_artifact_contents"]
        }
        for artifact in case["artifacts"]:
            if canonical_digest(private[artifact["artifact_id"]]) != artifact[
                "content_digest"
            ]:
                raise AssertionError("artifact content digest mismatch")

    manifest = load(FIXTURES / "fixture-manifest.json")
    manifest_files = {item["path"]: item for item in manifest["files"]}
    for item in manifest["files"]:
        raw = (FIXTURES / item["path"]).read_bytes()
        if len(raw) != item["byte_count"]:
            raise AssertionError("fixture byte count mismatch")
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise AssertionError("fixture hash mismatch")
    expected_generator_provenance = {
        "script": "generate_fixtures.py",
        "script_sha256": manifest_files["generate_fixtures.py"]["sha256"],
        "fixture_generator_version": FIXTURE_GENERATOR_VERSION,
        "implementation_id": GENERATOR_ID,
        "id_namespace_version": ID_NAMESPACE_VERSION,
        "id_namespace_formula": ID_NAMESPACE_FORMULA,
        "reportlab_invariant": True,
        "network_calls": 0,
        "ocr_calls": 0,
        "web_calls": 0,
    }
    if manifest.get("generator") != expected_generator_provenance:
        raise AssertionError("fixture generator provenance drifted")
    expected_synthetic_guard = {
        "product_practice_attempt_records": 0,
        "human_local_interactive_records": 0,
        "product_attempt_ids": 0,
        "evaluation_fixture_scorer_vectors": synthetic_evaluation_fixture_vectors,
        "scorer_vectors_are_product_evidence": False,
    }
    if manifest.get("synthetic_evidence_guard") != expected_synthetic_guard:
        raise AssertionError("synthetic evidence manifest guard drifted")

    reproducibility = validate_generator_reproducibility()
    schema_validated_instances = validated_instances
    schema_negative_probes = negative_probes
    validated_instances += reproducibility["pdf_semantic_assertion_groups"]
    negative_probes += reproducibility["pdf_semantic_negative_probes"]

    print(
        json.dumps(
            {
                "status": "pass",
                "schema_count": len(schemas),
                "schema_version_owner_count": len(version_owners),
                "schema_version_duplicate_negative_probes": schema_version_duplicate_negative_probes,
                "attempt_origin_validated_instances": attempt_origin_validated_instances,
                "attempt_origin_negative_probes": attempt_origin_negative_probes,
                "validated_instances": validated_instances,
                "negative_probes": negative_probes,
                "schema_validated_instances": schema_validated_instances,
                "schema_negative_probes": schema_negative_probes,
                "synthetic_product_detail_records": 0,
                "synthetic_product_attempt_records": 0,
                "synthetic_evaluation_fixture_vectors": synthetic_evaluation_fixture_vectors,
                **reproducibility,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
