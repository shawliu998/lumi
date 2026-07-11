from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Iterable

from .generation import (
    MAX_ARTIFACT_FIELD_CODEPOINTS,
    TaxonomySnapshot,
    compute_artifact_set_digest,
)
from .models import (
    ARTIFACT_TYPES,
    GENERATOR_ID,
    PRACTICE_KINDS,
    VERIFIER_ID,
    Artifact,
    CandidateSkillLink,
    SourceSpan,
    VerifierDecision,
    content_digest,
)
from .parsing import normalize_text


@dataclass(frozen=True, slots=True)
class VerificationResult:
    accepted: bool
    decisions: tuple[VerifierDecision, ...]


def normalized_exact(value: str) -> str:
    return normalize_text(value).strip()


def score_practice(content: dict[str, Any], learner_answer: str) -> tuple[bool, float]:
    scorer = content.get("scorer")
    if not isinstance(scorer, dict) or set(scorer) != {"kind", "version"}:
        return False, 0.0
    if scorer.get("kind") not in PRACTICE_KINDS or scorer.get("version") != "1.0.0":
        return False, 0.0
    answer = content.get("answer")
    if not isinstance(answer, str) or not isinstance(learner_answer, str):
        return False, 0.0
    correct = normalized_exact(learner_answer) == normalized_exact(answer)
    return correct, 1.0 if correct else 0.0


def verify_artifact_set(
    artifacts: Iterable[Artifact],
    spans: Iterable[SourceSpan],
    candidate_links: Iterable[CandidateSkillLink],
    *,
    resolve_span: Callable[[str], str],
    id_factory: Callable[[str], str],
    taxonomy: TaxonomySnapshot | None = None,
    expected_artifact_set_digest: str | None = None,
    expected_source_sha256: str | None = None,
) -> VerificationResult:
    artifact_list = list(artifacts)
    artifact_ids = {item.artifact_id for item in artifact_list}
    span_by_id = {span.span_id: span for span in spans}
    link_list = list(candidate_links)
    links_by_artifact: dict[str, list[CandidateSkillLink]] = {}
    for link in link_list:
        links_by_artifact.setdefault(link.artifact_id, []).append(link)

    counts = {
        artifact_type: sum(item.artifact_type == artifact_type for item in artifact_list)
        for artifact_type in ARTIFACT_TYPES
    }
    global_reasons: list[str] = []
    if len(artifact_ids) != len(artifact_list):
        global_reasons.append("duplicate_artifact_id")
    if any(link.artifact_id not in artifact_ids for link in link_list):
        global_reasons.append("candidate_skill_artifact_unresolved")
    if set(links_by_artifact) != artifact_ids or any(
        len(links_by_artifact[artifact_id]) != 1 for artifact_id in artifact_ids
    ):
        global_reasons.append("candidate_skill_link_count_invalid")
    if (
        expected_artifact_set_digest is not None
        and compute_artifact_set_digest(artifact_list) != expected_artifact_set_digest
    ):
        global_reasons.append("artifact_set_digest_mismatch")
    if counts["study_pack.one_page_notes"] != 1:
        global_reasons.append("invalid_note_count")
    if not 3 <= counts["study_pack.knowledge_card"] <= 5:
        global_reasons.append("invalid_card_count")
    if counts["study_pack.practice_item"] != 3:
        global_reasons.append("invalid_practice_count")
    if counts["study_pack.review_task"] != 1:
        global_reasons.append("invalid_review_task_count")
    global_reasons.extend(_verify_cross_artifact_transforms(artifact_list))

    decisions: list[VerifierDecision] = []
    for artifact in artifact_list:
        reasons = list(global_reasons)
        if artifact.artifact_type not in ARTIFACT_TYPES:
            reasons.append("artifact_unsupported")
        if artifact.lifecycle != "draft":
            reasons.append("invalid_artifact_lifecycle")
        if artifact.generator_id != GENERATOR_ID:
            reasons.append("generator_mismatch")
        if content_digest(artifact.content) != artifact.content_digest:
            reasons.append("artifact_digest_mismatch")
        metadata = artifact.generator_metadata
        expected_metadata_keys = {
            "generator_id",
            "mode",
            "model_calls",
            "network_calls",
            "ocr_calls",
            "source_normalized_sha256",
        }
        if not isinstance(metadata, dict) or set(metadata) != expected_metadata_keys:
            reasons.append("generator_metadata_invalid")
        else:
            if (
                metadata.get("generator_id") != GENERATOR_ID
                or metadata.get("mode") != "deterministic_extractive"
                or not isinstance(metadata.get("source_normalized_sha256"), str)
                or re.fullmatch(
                    r"[0-9a-f]{64}", metadata["source_normalized_sha256"]
                )
                is None
            ):
                reasons.append("generator_metadata_invalid")
            call_counts = (
                metadata.get("model_calls"),
                metadata.get("network_calls"),
                metadata.get("ocr_calls"),
            )
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value != 0
                for value in call_counts
            ):
                reasons.append("isolation_violation")
        if (
            expected_source_sha256 is not None
            and metadata.get("source_normalized_sha256") != expected_source_sha256
        ):
            reasons.append("generator_source_mismatch")
        reasons.extend(
            _verify_content(
                artifact,
                span_by_id=span_by_id,
                resolve_span=resolve_span,
            )
        )
        for link in links_by_artifact.get(artifact.artifact_id, []):
            reasons.extend(_verify_candidate_link(link, taxonomy))
        decisions.append(
            VerifierDecision(
                decision_id=id_factory("v_"),
                pack_id=artifact.pack_id,
                artifact_id=artifact.artifact_id,
                artifact_version=artifact.artifact_version,
                artifact_digest=artifact.content_digest,
                verifier_id=VERIFIER_ID,
                accepted=not reasons,
                reason_codes=tuple(sorted(set(reasons))),
            )
        )
    return VerificationResult(
        accepted=bool(decisions) and all(item.accepted for item in decisions),
        decisions=tuple(decisions),
    )


def _verify_content(
    artifact: Artifact,
    *,
    span_by_id: dict[str, SourceSpan],
    resolve_span: Callable[[str], str],
) -> list[str]:
    content = artifact.content
    expected_keys: dict[str, set[str]] = {
        "study_pack.one_page_notes": {"schema_version", "title", "claims", "citations"},
        "study_pack.knowledge_card": {"schema_version", "question", "answer", "citations"},
        "study_pack.practice_item": {
            "schema_version",
            "item_kind",
            "prompt",
            "scorer",
            "answer",
            "explanation",
            "citations",
        },
        "study_pack.review_task": {
            "schema_version",
            "instruction",
            "citations",
            "scope",
            "schedule_write_capability",
        },
    }
    if artifact.artifact_type not in expected_keys:
        return ["artifact_unsupported"]
    reasons: list[str] = []
    if any(
        isinstance(value, str) and len(value) > MAX_ARTIFACT_FIELD_CODEPOINTS
        for value in _walk_values(content)
    ):
        reasons.append("artifact_field_too_large")
    if set(content) != expected_keys[artifact.artifact_type]:
        reasons.append("artifact_schema_invalid")
        return reasons
    expected_schema_versions = {
        "study_pack.one_page_notes": "study_pack.one_page_notes.v1",
        "study_pack.knowledge_card": "study_pack.knowledge_card.v1",
        "study_pack.practice_item": "study_pack.practice_item.v1",
        "study_pack.review_task": "study_pack.review_task.v1",
    }
    if content.get("schema_version") != expected_schema_versions[artifact.artifact_type]:
        reasons.append("artifact_schema_invalid")
    citations = content.get("citations")
    if not isinstance(citations, list):
        return ["citation_schema_invalid"]
    expected_pointers: set[str]
    if artifact.artifact_type == "study_pack.one_page_notes":
        claims = content.get("claims")
        if content.get("title") != "一页笔记":
            reasons.append("artifact_schema_invalid")
        if not isinstance(claims, list) or not 3 <= len(claims) <= 5 or not all(
            isinstance(item, str) and item for item in claims
        ):
            reasons.append("artifact_schema_invalid")
            expected_pointers = set()
        else:
            expected_pointers = {f"/claims/{index}" for index in range(len(claims))}
            if sum(len(item) for item in claims) > 2_000:
                reasons.append("one_page_note_too_long")
    elif artifact.artifact_type == "study_pack.knowledge_card":
        expected_pointers = {"/answer"}
        if not isinstance(content.get("question"), str) or not content.get(
            "question"
        ) or not isinstance(content.get("answer"), str) or not content.get("answer"):
            reasons.append("artifact_schema_invalid")
    elif artifact.artifact_type == "study_pack.practice_item":
        expected_pointers = {"/answer", "/explanation"}
        if content.get("item_kind") not in PRACTICE_KINDS:
            reasons.append("artifact_unsupported")
        scorer = content.get("scorer")
        if (
            not isinstance(scorer, dict)
            or set(scorer) != {"kind", "version"}
            or scorer.get("kind") != content.get("item_kind")
            or scorer.get("version") != "1.0.0"
        ):
            reasons.append("scorer_invalid")
        answer = content.get("answer")
        prompt = content.get("prompt")
        if (
            not isinstance(prompt, str)
            or not prompt
            or not isinstance(content.get("explanation"), str)
            or not content.get("explanation")
        ):
            reasons.append("artifact_schema_invalid")
        if not isinstance(answer, str) or not answer:
            reasons.append("answer_invalid")
        elif isinstance(prompt, str) and normalized_exact(answer).casefold() in normalized_exact(prompt).casefold():
            reasons.append("answer_leakage")
    else:
        expected_pointers = {"/instruction"}
        if not isinstance(content.get("instruction"), str) or not content.get(
            "instruction"
        ):
            reasons.append("artifact_schema_invalid")
        if content.get("scope") != "pack_local_only" or content.get(
            "schedule_write_capability"
        ) is not False:
            reasons.append("isolation_violation")

    actual_pointers: set[str] = set()
    for citation in citations:
        if not isinstance(citation, dict) or set(citation) != {
            "field_pointer",
            "span_ref",
        }:
            reasons.append("citation_schema_invalid")
            continue
        pointer = citation.get("field_pointer")
        span_ref = citation.get("span_ref")
        if not isinstance(pointer, str) or not isinstance(span_ref, str):
            reasons.append("citation_schema_invalid")
            continue
        actual_pointers.add(pointer)
        if span_ref not in span_by_id:
            reasons.append("citation_unresolved")
            continue
        try:
            excerpt = resolve_span(span_ref)
        except Exception:
            reasons.append("citation_unresolved")
            continue
        field_value = _pointer_value(content, pointer)
        if not isinstance(field_value, str):
            reasons.append("citation_field_invalid")
        elif artifact.artifact_type == "study_pack.review_task":
            if excerpt not in field_value:
                reasons.append("citation_content_mismatch")
        elif field_value != excerpt:
            reasons.append("citation_content_mismatch")
    if actual_pointers != expected_pointers:
        reasons.append("citation_incomplete")
    return reasons


def _verify_cross_artifact_transforms(artifacts: list[Artifact]) -> list[str]:
    notes = [
        item for item in artifacts if item.artifact_type == "study_pack.one_page_notes"
    ]
    cards = [
        item for item in artifacts if item.artifact_type == "study_pack.knowledge_card"
    ]
    practices = [
        item for item in artifacts if item.artifact_type == "study_pack.practice_item"
    ]
    reviews = [
        item for item in artifacts if item.artifact_type == "study_pack.review_task"
    ]
    if len(notes) != 1 or len(reviews) != 1 or not 3 <= len(cards) <= 5 or len(
        practices
    ) != 3:
        return []
    claims = notes[0].content.get("claims")
    if not isinstance(claims, list) or not all(
        isinstance(claim, str) and claim for claim in claims
    ):
        return []

    reasons: list[str] = []
    card_answers: dict[int, str] = {}
    for card in cards:
        question = card.content.get("question")
        answer = card.content.get("answer")
        match = (
            re.fullmatch(r"材料中的第 ([1-5]) 条核心表述是什么？", question)
            if isinstance(question, str)
            else None
        )
        if match is None or not isinstance(answer, str):
            reasons.append("card_transform_mismatch")
            continue
        index = int(match.group(1))
        if index in card_answers:
            reasons.append("card_transform_mismatch")
        card_answers[index] = answer
    expected_card_answers = {
        index: claim for index, claim in enumerate(claims, start=1)
    }
    if card_answers != expected_card_answers:
        reasons.append("card_transform_mismatch")

    practice_explanations: dict[int, str] = {}
    for practice in practices:
        content = practice.content
        item_kind = content.get("item_kind")
        prompt = content.get("prompt")
        answer = content.get("answer")
        explanation = content.get("explanation")
        index: int | None = None
        transform_matches = False
        if all(isinstance(value, str) for value in (prompt, answer, explanation)):
            if item_kind == "cloze_exact_v1":
                match = re.fullmatch(r"材料填空 ([1-3])：(.*)", prompt, flags=re.DOTALL)
                if match is not None:
                    index = int(match.group(1))
                    body = match.group(2)
                    transform_matches = (
                        body.count("____") == 1
                        and body.replace("____", answer) == explanation
                    )
            elif item_kind == "normalized_exact_v1":
                match = re.fullmatch(
                    r"根据本地材料，完整输入第 ([1-3]) 条核心表述。", prompt
                )
                if match is not None:
                    index = int(match.group(1))
                    transform_matches = answer == explanation
        if index is None or not transform_matches or index in practice_explanations:
            reasons.append("practice_transform_mismatch")
            continue
        practice_explanations[index] = explanation
    expected_practice = {
        index: claim for index, claim in enumerate(claims[:3], start=1)
    }
    if practice_explanations != expected_practice:
        reasons.append("practice_transform_mismatch")

    expected_instruction = f"复习并独立复述这一材料要点：{claims[0]}"
    if reviews[0].content.get("instruction") != expected_instruction:
        reasons.append("review_transform_mismatch")
    return reasons


def _verify_candidate_link(
    link: CandidateSkillLink, taxonomy: TaxonomySnapshot | None
) -> list[str]:
    reasons: list[str] = []
    if link.status != "unconfirmed_candidate":
        reasons.append("candidate_skill_status_invalid")
    if not link.label:
        reasons.append("candidate_skill_label_missing")
    if link.skill_id is None:
        if link.taxonomy_version is not None or link.taxonomy_digest is not None:
            reasons.append("candidate_skill_taxonomy_invalid")
    elif (
        taxonomy is None
        or link.skill_id not in taxonomy.skills
        or link.taxonomy_version != taxonomy.version
        or link.taxonomy_digest != taxonomy.digest
    ):
        reasons.append("candidate_skill_unresolved")
    return reasons


def _pointer_value(content: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith("/"):
        return None
    value: Any = content
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value.get(token)
        elif isinstance(value, list) and token.isdigit():
            index = int(token)
            if not 0 <= index < len(value):
                return None
            value = value[index]
        else:
            return None
    return value


def _walk_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    else:
        yield value
