from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .models import (
    GENERATOR_ID,
    Artifact,
    CandidateSkillLink,
    ParsedSource,
    SourceSpan,
    StudyPackError,
    canonical_json,
    content_digest,
    sha256_text,
)


MAX_ARTIFACT_FIELD_CODEPOINTS = 2_000
MAX_EXCERPT_CODEPOINTS = 360


@dataclass(frozen=True, slots=True)
class TaxonomySnapshot:
    version: str
    skills: frozenset[str]
    digest: str

    @classmethod
    def default(cls) -> "TaxonomySnapshot":
        value = {
            "version": "lumi-taxonomy-seed.v1",
            "skills": ["study.source-recall"],
        }
        return cls(
            version=value["version"],
            skills=frozenset(value["skills"]),
            digest=sha256_text(canonical_json(value)),
        )


@dataclass(frozen=True, slots=True)
class GeneratedPack:
    spans: tuple[SourceSpan, ...]
    artifacts: tuple[Artifact, ...]
    candidate_skill_links: tuple[CandidateSkillLink, ...]
    artifact_set_digest: str


@dataclass(frozen=True, slots=True)
class _Excerpt:
    locator_kind: str
    locator_index: int
    start: int
    end: int
    text: str


def generate_extractive_pack(
    parsed: ParsedSource,
    *,
    pack_id: str,
    document_id: str,
    source_version: int,
    id_factory: Callable[[str], str],
    taxonomy: TaxonomySnapshot | None = None,
) -> GeneratedPack:
    excerpts = _extract_excerpts(parsed)
    if len(excerpts) < 3:
        raise StudyPackError(
            "source_insufficient_for_pack",
            "source does not contain three citable core statements",
        )
    selected = excerpts[:5]
    spans: list[SourceSpan] = []
    span_by_excerpt: dict[_Excerpt, SourceSpan] = {}
    for excerpt in selected:
        span = SourceSpan(
            span_id=id_factory("s_"),
            document_id=document_id,
            source_version=source_version,
            normalized_source_sha256=parsed.normalized_sha256,
            locator_kind=excerpt.locator_kind,
            locator_index=excerpt.locator_index,
            start_offset=excerpt.start,
            end_offset=excerpt.end,
            slice_sha256=sha256_text(excerpt.text),
        )
        spans.append(span)
        span_by_excerpt[excerpt] = span

    metadata = {
        "generator_id": GENERATOR_ID,
        "mode": "deterministic_extractive",
        "model_calls": 0,
        "network_calls": 0,
        "ocr_calls": 0,
        "source_normalized_sha256": parsed.normalized_sha256,
    }
    artifacts: list[Artifact] = []

    claims = [excerpt.text for excerpt in selected]
    note_content = {
        "schema_version": "study_pack.one_page_notes.v1",
        "title": "一页笔记",
        "claims": claims,
        "citations": [
            {
                "field_pointer": f"/claims/{index}",
                "span_ref": span_by_excerpt[excerpt].span_id,
            }
            for index, excerpt in enumerate(selected)
        ],
    }
    artifacts.append(_artifact(id_factory, pack_id, "study_pack.one_page_notes", note_content, metadata))

    for index, excerpt in enumerate(selected, start=1):
        card_content = {
            "schema_version": "study_pack.knowledge_card.v1",
            "question": f"材料中的第 {index} 条核心表述是什么？",
            "answer": excerpt.text,
            "citations": [
                {
                    "field_pointer": "/answer",
                    "span_ref": span_by_excerpt[excerpt].span_id,
                }
            ],
        }
        artifacts.append(
            _artifact(
                id_factory,
                pack_id,
                "study_pack.knowledge_card",
                card_content,
                metadata,
            )
        )

    for index, excerpt in enumerate(selected[:3], start=1):
        item_kind, prompt, answer, answer_start, answer_end = _practice_transform(
            excerpt, index
        )
        if answer_start == 0 and answer_end == len(excerpt.text):
            answer_span = span_by_excerpt[excerpt]
        else:
            answer_span = SourceSpan(
                span_id=id_factory("s_"),
                document_id=document_id,
                source_version=source_version,
                normalized_source_sha256=parsed.normalized_sha256,
                locator_kind=excerpt.locator_kind,
                locator_index=excerpt.locator_index,
                start_offset=excerpt.start + answer_start,
                end_offset=excerpt.start + answer_end,
                slice_sha256=sha256_text(answer),
            )
            spans.append(answer_span)
        item_content = {
            "schema_version": "study_pack.practice_item.v1",
            "item_kind": item_kind,
            "prompt": prompt,
            "scorer": {
                "kind": item_kind,
                "version": "1.0.0",
            },
            "answer": answer,
            "explanation": excerpt.text,
            "citations": [
                {
                    "field_pointer": "/answer",
                    "span_ref": answer_span.span_id,
                },
                {
                    "field_pointer": "/explanation",
                    "span_ref": span_by_excerpt[excerpt].span_id,
                },
            ],
        }
        artifacts.append(
            _artifact(
                id_factory,
                pack_id,
                "study_pack.practice_item",
                item_content,
                metadata,
            )
        )

    first = selected[0]
    review_content = {
        "schema_version": "study_pack.review_task.v1",
        "instruction": f"复习并独立复述这一材料要点：{first.text}",
        "citations": [
            {
                "field_pointer": "/instruction",
                "span_ref": span_by_excerpt[first].span_id,
            }
        ],
        "scope": "pack_local_only",
        "schedule_write_capability": False,
    }
    artifacts.append(
        _artifact(
            id_factory,
            pack_id,
            "study_pack.review_task",
            review_content,
            metadata,
        )
    )

    links: list[CandidateSkillLink] = []
    resolved_skill_id = (
        "study.source-recall"
        if taxonomy is not None and "study.source-recall" in taxonomy.skills
        else None
    )
    for artifact in artifacts:
        links.append(
            CandidateSkillLink(
                artifact_id=artifact.artifact_id,
                label="材料要点复述",
                skill_id=resolved_skill_id,
                status="unconfirmed_candidate",
                taxonomy_version=taxonomy.version if resolved_skill_id else None,
                taxonomy_digest=taxonomy.digest if resolved_skill_id else None,
            )
        )
    return GeneratedPack(
        spans=tuple(spans),
        artifacts=tuple(artifacts),
        candidate_skill_links=tuple(links),
        artifact_set_digest=compute_artifact_set_digest(artifacts),
    )


def compute_artifact_set_digest(artifacts: list[Artifact] | tuple[Artifact, ...]) -> str:
    digest_input = [
        {
            "artifact_id": artifact.artifact_id,
            "artifact_type": artifact.artifact_type,
            "artifact_version": artifact.artifact_version,
            "content_digest": artifact.content_digest,
        }
        for artifact in sorted(artifacts, key=lambda item: item.artifact_id)
    ]
    return sha256_text(canonical_json(digest_input))


def _artifact(
    id_factory: Callable[[str], str],
    pack_id: str,
    artifact_type: str,
    content: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> Artifact:
    value = dict(content)
    return Artifact(
        artifact_id=id_factory("a_"),
        pack_id=pack_id,
        artifact_version=1,
        artifact_type=artifact_type,
        lifecycle="draft",
        content=value,
        content_digest=content_digest(value),
        generator_id=GENERATOR_ID,
        generator_metadata=dict(metadata),
    )


def _extract_excerpts(parsed: ParsedSource) -> list[_Excerpt]:
    candidates: list[_Excerpt] = []
    pattern = re.compile(r"[^。！？!?；;\.\n]+[。！？!?；;\.]?")
    for segment in parsed.segments:
        for match in pattern.finditer(segment.text):
            start, end = match.span()
            while start < end and segment.text[start].isspace():
                start += 1
            while end > start and segment.text[end - 1].isspace():
                end -= 1
            cursor = start
            while cursor < end:
                chunk_end = min(end, cursor + MAX_EXCERPT_CODEPOINTS)
                while cursor < chunk_end and segment.text[cursor].isspace():
                    cursor += 1
                while chunk_end > cursor and segment.text[chunk_end - 1].isspace():
                    chunk_end -= 1
                text = segment.text[cursor:chunk_end]
                if len(text) >= 8 and any(character.isalnum() for character in text):
                    candidates.append(
                        _Excerpt(
                            locator_kind=segment.locator_kind,
                            locator_index=segment.locator_index,
                            start=cursor,
                            end=chunk_end,
                            text=text,
                        )
                    )
                cursor = max(chunk_end, cursor + 1)
    first_page_texts: list[str] = []
    seen_pages: set[int] = set()
    for candidate in candidates:
        if (
            candidate.locator_kind == "page"
            and candidate.locator_index not in seen_pages
        ):
            seen_pages.add(candidate.locator_index)
            first_page_texts.append(candidate.text)
    repeated_page_headers = {
        text for text in first_page_texts if first_page_texts.count(text) > 1
    }

    excerpts: list[_Excerpt] = []
    seen_texts: set[str] = set()
    for candidate in candidates:
        if candidate.text in repeated_page_headers or candidate.text in seen_texts:
            continue
        seen_texts.add(candidate.text)
        excerpts.append(candidate)
    return excerpts


def _practice_transform(
    excerpt: _Excerpt, index: int
) -> tuple[str, str, str, int, int]:
    text = excerpt.text
    candidates = _defensible_token_spans(text)
    candidates.sort(key=lambda item: (abs((item[0] + item[1]) / 2 - len(text) / 2), item[0]))
    for start, end in candidates:
        answer = text[start:end]
        if text.count(answer) != 1:
            continue
        prompt = f"材料填空 {index}：" + text[:start] + "____" + text[end:]
        if normalized_casefold(answer) not in normalized_casefold(prompt):
            return "cloze_exact_v1", prompt, answer, start, end
    return (
        "normalized_exact_v1",
        f"根据本地材料，完整输入第 {index} 条核心表述。",
        text,
        0,
        len(text),
    )


def _defensible_token_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9]{2,39}", text):
        start, end = match.span()
        before = text[start - 1] if start else ""
        after = text[end] if end < len(text) else ""
        if _is_token_boundary(before) and _is_token_boundary(after):
            spans.append((start, end))
    return spans


def _is_token_boundary(character: str) -> bool:
    return (
        not character
        or character.isspace()
        or unicodedata.category(character).startswith("P")
    )


def normalized_casefold(value: str) -> str:
    return value.strip().casefold()
