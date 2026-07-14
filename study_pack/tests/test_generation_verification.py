from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from helpers import CHINESE_SOURCE, SequentialIdFactory, opaque_id
from lumi_study_pack.generation import TaxonomySnapshot, generate_extractive_pack
from lumi_study_pack.models import StudyPackError, content_digest, sha256_text
from lumi_study_pack.parsing import parse_pasted_text, parse_text_pdf
from lumi_study_pack.verification import score_practice, verify_artifact_set


class GenerationVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parsed = parse_pasted_text("Cafe\u0301 能验证 Unicode 规范化。" + CHINESE_SOURCE)
        self.ids = SequentialIdFactory()
        self.generated = generate_extractive_pack(
            self.parsed,
            pack_id=opaque_id("p_", 1),
            document_id=opaque_id("d_", 2),
            source_version=1,
            id_factory=self.ids,
        )

    def resolver(self, span_id: str) -> str:
        span = next(item for item in self.generated.spans if item.span_id == span_id)
        segment = next(
            item
            for item in self.parsed.segments
            if item.locator_kind == span.locator_kind
            and item.locator_index == span.locator_index
        )
        excerpt = segment.text[span.start_offset : span.end_offset]
        if sha256_text(excerpt) != span.slice_sha256:
            raise ValueError("slice hash mismatch")
        return excerpt

    def test_generator_produces_closed_counts_citations_and_no_model_capability(self) -> None:
        artifacts = self.generated.artifacts
        regenerated = generate_extractive_pack(
            self.parsed,
            pack_id=opaque_id("p_", 1),
            document_id=opaque_id("d_", 2),
            source_version=1,
            id_factory=SequentialIdFactory(),
        )
        self.assertEqual(
            [item.content for item in regenerated.artifacts],
            [item.content for item in artifacts],
        )
        self.assertEqual(regenerated.artifact_set_digest, self.generated.artifact_set_digest)
        self.assertEqual(
            sum(item.artifact_type == "study_pack.one_page_notes" for item in artifacts), 1
        )
        self.assertTrue(
            3
            <= sum(item.artifact_type == "study_pack.knowledge_card" for item in artifacts)
            <= 5
        )
        self.assertEqual(
            sum(item.artifact_type == "study_pack.practice_item" for item in artifacts), 3
        )
        self.assertEqual(
            sum(item.artifact_type == "study_pack.review_task" for item in artifacts), 1
        )
        self.assertTrue(
            all(
                item.generator_metadata["model_calls"] == 0
                and item.generator_metadata["network_calls"] == 0
                and item.generator_metadata["ocr_calls"] == 0
                for item in artifacts
            )
        )
        result = verify_artifact_set(
            artifacts,
            self.generated.spans,
            self.generated.candidate_skill_links,
            resolve_span=self.resolver,
            id_factory=SequentialIdFactory(),
        )
        self.assertTrue(result.accepted)
        self.assertEqual(len(result.decisions), len(artifacts))
        mismatched = verify_artifact_set(
            artifacts,
            self.generated.spans,
            self.generated.candidate_skill_links,
            resolve_span=self.resolver,
            id_factory=SequentialIdFactory(),
            expected_artifact_set_digest="0" * 64,
            expected_source_sha256="f" * 64,
        )
        self.assertFalse(mismatched.accepted)
        self.assertTrue(
            all(
                "artifact_set_digest_mismatch" in item.reason_codes
                and "generator_source_mismatch" in item.reason_codes
                for item in mismatched.decisions
            )
        )

    def test_unicode_codepoint_offsets_resolve_the_exact_nfc_slice(self) -> None:
        excerpts = [self.resolver(item.span_id) for item in self.generated.spans]
        self.assertTrue(any("Café" in item for item in excerpts))
        self.assertTrue(
            all(len(item) == span.end_offset - span.start_offset for item, span in zip(excerpts, self.generated.spans))
        )

    def test_citation_tamper_and_answer_leakage_quarantine_verification(self) -> None:
        artifacts = list(self.generated.artifacts)
        note_index = next(
            index
            for index, item in enumerate(artifacts)
            if item.artifact_type == "study_pack.one_page_notes"
        )
        note = artifacts[note_index]
        tampered_note_content = dict(note.content)
        tampered_citations = [dict(item) for item in tampered_note_content["citations"]]
        tampered_citations[0]["span_ref"] = opaque_id("s_", 999)
        tampered_note_content["citations"] = tampered_citations
        artifacts[note_index] = replace(
            note,
            content=tampered_note_content,
            content_digest=content_digest(tampered_note_content),
        )
        citation_result = verify_artifact_set(
            artifacts,
            self.generated.spans,
            self.generated.candidate_skill_links,
            resolve_span=self.resolver,
            id_factory=SequentialIdFactory(),
        )
        self.assertFalse(citation_result.accepted)
        self.assertTrue(
            any("citation_unresolved" in item.reason_codes for item in citation_result.decisions)
        )

        artifacts = list(self.generated.artifacts)
        practice_index = next(
            index
            for index, item in enumerate(artifacts)
            if item.artifact_type == "study_pack.practice_item"
        )
        practice = artifacts[practice_index]
        leaking = dict(practice.content)
        leaking["prompt"] = f"答案是：{leaking['answer']}"
        artifacts[practice_index] = replace(
            practice, content=leaking, content_digest=content_digest(leaking)
        )
        leakage_result = verify_artifact_set(
            artifacts,
            self.generated.spans,
            self.generated.candidate_skill_links,
            resolve_span=self.resolver,
            id_factory=SequentialIdFactory(),
        )
        self.assertFalse(leakage_result.accepted)
        self.assertTrue(
            any("answer_leakage" in item.reason_codes for item in leakage_result.decisions)
        )

    def test_candidate_skill_is_label_only_without_taxonomy_and_resolved_when_versioned(self) -> None:
        self.assertTrue(
            all(
                item.status == "unconfirmed_candidate"
                and item.label
                and item.skill_id is None
                and item.taxonomy_version is None
                for item in self.generated.candidate_skill_links
            )
        )

    def test_verifier_recomputes_transforms_provenance_and_link_completeness(self) -> None:
        practice_index = next(
            index
            for index, item in enumerate(self.generated.artifacts)
            if item.artifact_type == "study_pack.practice_item"
        )
        practice = self.generated.artifacts[practice_index]

        invalid_schema_content = dict(practice.content)
        invalid_schema_content["schema_version"] = "study_pack.practice_item.v2"
        invalid_schema = list(self.generated.artifacts)
        invalid_schema[practice_index] = replace(
            practice,
            content=invalid_schema_content,
            content_digest=content_digest(invalid_schema_content),
        )

        invalid_transform_content = dict(practice.content)
        invalid_transform_content["prompt"] = "材料填空 1：无关内容____"
        invalid_transform = list(self.generated.artifacts)
        invalid_transform[practice_index] = replace(
            practice,
            content=invalid_transform_content,
            content_digest=content_digest(invalid_transform_content),
        )

        invalid_provenance = list(self.generated.artifacts)
        invalid_provenance[practice_index] = replace(
            practice,
            generator_metadata={**practice.generator_metadata, "extra": "not-closed"},
        )

        probes = (
            (invalid_schema, self.generated.candidate_skill_links, "artifact_schema_invalid"),
            (invalid_transform, self.generated.candidate_skill_links, "practice_transform_mismatch"),
            (invalid_provenance, self.generated.candidate_skill_links, "generator_metadata_invalid"),
            (self.generated.artifacts, self.generated.candidate_skill_links[:-1], "candidate_skill_link_count_invalid"),
        )
        for artifacts, links, reason in probes:
            with self.subTest(reason=reason):
                result = verify_artifact_set(
                    artifacts,
                    self.generated.spans,
                    links,
                    resolve_span=self.resolver,
                    id_factory=SequentialIdFactory(),
                )
                self.assertFalse(result.accepted)
                self.assertTrue(
                    any(reason in decision.reason_codes for decision in result.decisions)
                )
        taxonomy = TaxonomySnapshot.default()
        resolved = generate_extractive_pack(
            self.parsed,
            pack_id=opaque_id("p_", 3),
            document_id=opaque_id("d_", 4),
            source_version=1,
            id_factory=SequentialIdFactory(),
            taxonomy=taxonomy,
        )
        self.assertTrue(
            all(
                item.skill_id == "study.source-recall"
                and item.taxonomy_version == taxonomy.version
                and item.taxonomy_digest == taxonomy.digest
                and item.status == "unconfirmed_candidate"
                for item in resolved.candidate_skill_links
            )
        )

    def test_exact_scorer_is_recomputable_and_source_insufficiency_is_stable(self) -> None:
        practices = [
            item
            for item in self.generated.artifacts
            if item.artifact_type == "study_pack.practice_item"
        ]
        self.assertEqual(practices[0].content["item_kind"], "cloze_exact_v1")
        self.assertEqual(practices[0].content["answer"], "Unicode")
        practice = practices[1]
        self.assertEqual(practice.content["item_kind"], "normalized_exact_v1")
        self.assertEqual(practice.content["answer"], practice.content["explanation"])
        self.assertNotIn(practice.content["answer"], practice.content["prompt"])
        self.assertEqual(score_practice(practice.content, practice.content["answer"]), (True, 1.0))
        self.assertEqual(score_practice(practice.content, "错误回答"), (False, 0.0))
        with self.assertRaises(StudyPackError) as caught:
            generate_extractive_pack(
                parse_pasted_text("只有一个足够长但无法组成练习包的句子。"),
                pack_id=opaque_id("p_", 5),
                document_id=opaque_id("d_", 6),
                source_version=1,
                id_factory=SequentialIdFactory(),
            )
        self.assertEqual(caught.exception.code, "source_insufficient_for_pack")

    def test_cloze_requires_a_defensible_token_boundary(self) -> None:
        parsed = parse_pasted_text(
            "BKT 用于根据作答证据估计掌握概率。"
            "完整陈述作答避免从中文短语中间挖空。"
            "独立迁移题用于验证是否真正掌握。"
        )
        generated = generate_extractive_pack(
            parsed,
            pack_id=opaque_id("p_", 70),
            document_id=opaque_id("d_", 71),
            source_version=1,
            id_factory=SequentialIdFactory(),
        )
        practices = [
            item
            for item in generated.artifacts
            if item.artifact_type == "study_pack.practice_item"
        ]
        self.assertEqual(practices[0].content["item_kind"], "cloze_exact_v1")
        self.assertEqual(practices[0].content["answer"], "BKT")
        self.assertEqual(
            practices[0].content["prompt"],
            "材料填空 1：____ 用于根据作答证据估计掌握概率。",
        )
        for practice in practices[1:]:
            self.assertEqual(practice.content["item_kind"], "normalized_exact_v1")
            self.assertEqual(practice.content["answer"], practice.content["explanation"])
            self.assertNotIn("____", practice.content["prompt"])

    def test_real_chinese_pdf_excludes_repeated_page_chrome_and_awkward_clozes(self) -> None:
        root = Path(__file__).resolve().parents[2]
        parsed = parse_text_pdf(
            (root / "evals/fixtures/study_pack/text_bearing_chinese.pdf").read_bytes()
        )
        generated = generate_extractive_pack(
            parsed,
            pack_id=opaque_id("p_", 80),
            document_id=opaque_id("d_", 81),
            source_version=1,
            id_factory=SequentialIdFactory(),
        )
        note = next(
            item
            for item in generated.artifacts
            if item.artifact_type == "study_pack.one_page_notes"
        )
        claims = note.content["claims"]
        self.assertGreaterEqual(len(claims), 3)
        self.assertEqual(len(claims), len(set(claims)))
        self.assertNotIn("Lumi 学习材料", claims)

        practices = [
            item.content
            for item in generated.artifacts
            if item.artifact_type == "study_pack.practice_item"
        ]
        explanations = [item["explanation"] for item in practices]
        self.assertEqual(len(explanations), len(set(explanations)))
        self.assertTrue(all(len(item) >= 12 for item in explanations))
        self.assertTrue(all(item.endswith(("。", "！", "？")) for item in explanations))
        self.assertNotIn("Lumi 学习材料", explanations)
        for index, practice in enumerate(practices, start=1):
            self.assertEqual(practice["item_kind"], "normalized_exact_v1")
            self.assertEqual(practice["answer"], practice["explanation"])
            self.assertEqual(
                practice["prompt"],
                f"根据本地材料，完整输入第 {index} 条核心表述。",
            )
            self.assertNotIn(practice["answer"], practice["prompt"])

    def test_very_long_source_statements_are_bounded_before_public_artifacts(self) -> None:
        parsed = parse_pasted_text(
            "甲" + "知识" * 1_000 + "。"
            "乙" + "能力" * 1_000 + "。"
            "丙" + "迁移" * 1_000 + "。"
        )
        generated = generate_extractive_pack(
            parsed,
            pack_id=opaque_id("p_", 50),
            document_id=opaque_id("d_", 51),
            source_version=1,
            id_factory=SequentialIdFactory(),
        )
        strings = []

        def collect(value):
            if isinstance(value, str):
                strings.append(value)
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        for artifact in generated.artifacts:
            collect(artifact.content)
        self.assertLessEqual(max(map(len, strings)), 2000)


if __name__ == "__main__":
    unittest.main()
