#!/usr/bin/env python3
"""Generate deterministic, original P0.3 Study Pack contract fixtures.

The PDF uses ReportLab's invariant mode and a built-in CJK CID font.  The
script intentionally keeps every intermediate render in a temporary directory
outside the repository and removes it before returning.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "study_pack"))
os.environ["PYTHONPATH"] = os.pathsep.join(
    [
        str(ROOT / "study_pack"),
        *([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []),
    ]
)

# Load the bounded modules directly so fixture generation does not depend on
# the service/store assembly being present yet.
package = types.ModuleType("lumi_study_pack")
package.__path__ = [str(ROOT / "study_pack" / "lumi_study_pack")]
sys.modules.setdefault("lumi_study_pack", package)

from lumi_study_pack.generation import (  # noqa: E402
    TaxonomySnapshot,
    generate_extractive_pack,
)
from lumi_study_pack.models import (  # noqa: E402
    GENERATOR_ID,
    SourceDocument,
    canonical_json,
    sha256_bytes,
    sha256_text,
)
from lumi_study_pack.parsing import parse_pasted_text, parse_text_pdf  # noqa: E402
from lumi_study_pack.verification import verify_artifact_set  # noqa: E402


PASTED_TEXT = """增长率表示现期量相对基期量的变化比例，计算时分母使用基期量。

定位基期和现期后，先计算增长量，再用增长量除以基期量。

单位不一致时必须先统一单位，避免把万元和亿元直接代入同一算式。

完成提示练习后，应使用另一道未显示答案的题独立作答；同一道题重做不能证明迁移。

复习任务完成只表示计划状态变化，不直接证明学习效果。
"""

PDF_PAGES = (
    (
        "证据定位要求回答前先找到材料中的原句。",
        "独立作答要求提示结束后在没有帮助的情况下重新回答。",
        "复习记录只说明任务完成，不能直接证明已经掌握。",
    ),
    (
        "候选技能链接必须保持未确认，直到版本化技能表能够解析。",
        "生成题必须能够从引用材料中找到确定答案。",
        "扫描型 PDF 需要 OCR，本阶段不处理。",
    ),
)

FIXED_TIME = "2026-07-11T00:00:00Z"
FIXTURE_GENERATOR_VERSION = "lumi-study-pack-fixtures@2"
EVALUATION_FIXTURE_EVIDENCE_ORIGIN = "evaluation_fixture"
ID_NAMESPACE_VERSION = "lumi-ap-deterministic-fixture-ids@1"
ID_NAMESPACE_FORMULA = (
    "sha256(utf8('lumi-p03-fixture:' + namespace + ':' + prefix + ':' + "
    "decimal_counter))[:20] -> prefix + 40 A-P nibbles"
)


class DeterministicIds:
    """Produce the production A-P encoding from deterministic fixture bytes."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        count = self.counts.get(prefix, 0) + 1
        self.counts[prefix] = count
        raw = hashlib.sha256(
            f"lumi-p03-fixture:{self.namespace}:{prefix}:{count}".encode("utf-8")
        ).digest()[:20]
        encoded = "".join(
            chr(ord("A") + nibble)
            for byte in raw
            for nibble in (byte >> 4, byte & 0x0F)
        )
        return prefix + encoded


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def generate_pdf(path: Path) -> None:
    import reportlab
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    if reportlab.Version != "4.4.2":
        raise RuntimeError("fixture generation requires reportlab 4.4.2")
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    document = canvas.Canvas(
        str(path),
        pagesize=A4,
        pageCompression=1,
        invariant=1,
        pdfVersion=(1, 4),
    )
    document.setTitle("Lumi P0.3 Chinese text-layer fixture")
    document.setAuthor("Lumi")
    document.setSubject("Original local Study Pack evaluation material")
    document.setCreator("Lumi deterministic fixture generator")
    width, height = A4
    for page_number, statements in enumerate(PDF_PAGES, start=1):
        document.setFont("STSong-Light", 18)
        document.drawString(64, height - 72, "Lumi 学习材料")
        document.setFont("STSong-Light", 12)
        y = height - 126
        for statement in statements:
            document.drawString(72, y, statement)
            y -= 34
        document.setFont("STSong-Light", 9)
        document.drawCentredString(width / 2, 36, f"第 {page_number} 页")
        document.showPage()
    document.save()


def source_document(parsed: Any, *, ids: DeterministicIds, pack_id: str) -> dict[str, Any]:
    record = SourceDocument(
        document_id=ids("d_"),
        pack_id=pack_id,
        source_version=1,
        input_kind=parsed.input_kind,
        media_type=parsed.media_type,
        original_sha256=parsed.original_sha256,
        normalized_sha256=parsed.normalized_sha256,
        byte_count=len(parsed.original_bytes),
        locator_count=len(parsed.segments),
        codepoint_count=parsed.codepoint_count,
        parser_name=parsed.parser_name,
        parser_version=parsed.parser_version,
        normalization_name=parsed.normalization_name,
        normalization_version=parsed.normalization_version,
        extraction_state="accepted_with_warnings" if parsed.warnings else "accepted",
        warning_codes=parsed.warnings,
    ).to_dict()
    return {"schema_version": "lumi.source-document.v1", **record}


def resolved_slice(parsed: Any, span: Any) -> str:
    segment = next(
        item
        for item in parsed.segments
        if item.locator_kind == span.locator_kind
        and item.locator_index == span.locator_index
    )
    value = segment.text[span.start_offset : span.end_offset]
    if sha256_text(value) != span.slice_sha256:
        raise RuntimeError("fixture source span does not resolve")
    return value


def make_case(case_name: str, parsed: Any, title: str) -> dict[str, Any]:
    ids = DeterministicIds(case_name)
    pack_id = ids("p_")
    document = source_document(parsed, ids=ids, pack_id=pack_id)
    generated = generate_extractive_pack(
        parsed,
        pack_id=pack_id,
        document_id=document["document_id"],
        source_version=document["source_version"],
        id_factory=ids,
        taxonomy=TaxonomySnapshot.default(),
    )
    span_by_id = {item.span_id: item for item in generated.spans}
    verification = verify_artifact_set(
        generated.artifacts,
        generated.spans,
        generated.candidate_skill_links,
        resolve_span=lambda span_id: resolved_slice(parsed, span_by_id[span_id]),
        id_factory=ids,
        taxonomy=TaxonomySnapshot.default(),
    )
    if not verification.accepted:
        reasons = sorted(
            {
                reason
                for decision in verification.decisions
                for reason in decision.reason_codes
            }
        )
        raise RuntimeError(f"fixture artifacts failed verification: {reasons}")

    published_artifacts = [
        replace(artifact, lifecycle="published") for artifact in generated.artifacts
    ]
    public_artifacts = [
        artifact.to_dict(include_private=False) for artifact in published_artifacts
    ]
    private_contents = [
        {
            "artifact_id": artifact.artifact_id,
            "content": artifact.content,
        }
        for artifact in published_artifacts
    ]
    artifacts_by_type: dict[str, int] = {}
    for artifact in published_artifacts:
        artifacts_by_type[artifact.artifact_type] = (
            artifacts_by_type.get(artifact.artifact_type, 0) + 1
        )
    artifact_refs = [
        {
            "artifact_id": artifact.artifact_id,
            "artifact_version": artifact.artifact_version,
            "artifact_type": artifact.artifact_type,
            "content_digest": artifact.content_digest,
            "lifecycle": artifact.lifecycle,
            "verification_decision": "accepted",
        }
        for artifact in published_artifacts
    ]
    pack = {
        "schema_version": "lumi.study-pack.v1",
        "pack_id": pack_id,
        "version": 3,
        "title": title,
        "lifecycle": "published",
        "source_ref": {
            "document_id": document["document_id"],
            "source_version": document["source_version"],
            "original_sha256": document["original_sha256"],
            "normalized_sha256": document["normalized_sha256"],
            "input_kind": document["input_kind"],
        },
        "generator_ref": {
            "generator_id": "extractive-local@1",
            "mode": "deterministic_extractive",
            "model_calls": 0,
            "network_calls": 0,
            "ocr_calls": 0,
        },
        "artifact_counts": {
            "one_page_notes": artifacts_by_type["study_pack.one_page_notes"],
            "knowledge_card": artifacts_by_type["study_pack.knowledge_card"],
            "practice_item": artifacts_by_type["study_pack.practice_item"],
            "review_task": artifacts_by_type["study_pack.review_task"],
            "total": len(published_artifacts),
        },
        "artifact_refs": artifact_refs,
        "verifier_summary": {
            "status": "accepted",
            "artifact_count": len(published_artifacts),
            "accepted_count": len(published_artifacts),
            "quarantined_count": 0,
            "verifier_id": "study-pack-deterministic-verifier@1",
            "reviewed_content_digest": generated.artifact_set_digest,
            "reviewed_at": FIXED_TIME,
        },
        "authority": "independent_study_pack_store",
        "write_capabilities": {
            "kt": False,
            "misconception_dossier": False,
            "today_plan": False,
            "review_schedule": False,
        },
        "population_evidence": "unavailable",
        "learning_effect_evidence": "unavailable",
        "created_at": FIXED_TIME,
        "updated_at": FIXED_TIME,
        "links": {
            "self": f"/v1/study-packs/{pack_id}",
            "replay": f"/v1/study-packs/{pack_id}/replay",
            "citation_template": f"/v1/study-packs/{pack_id}/citations/{{span_id}}",
        },
        "event_stream": {
            "stream_type": "study_pack",
            "stream_id": pack_id,
            "version": 3,
            "trace_verified": True,
            "projection_verified": True,
        },
    }
    practice = next(
        item
        for item in published_artifacts
        if item.artifact_type == "study_pack.practice_item"
    )
    answer = practice.content["answer"]
    case = {
        "schema_version": "lumi.study-pack-contract-fixture.v1",
        "case_id": case_name,
        "source_document": document,
        "source_spans": [
            {"schema_version": "lumi.source-span.v1", **span.to_dict()}
            for span in generated.spans
        ],
        "pack": pack,
        "artifacts": public_artifacts,
        "private_artifact_contents": private_contents,
        "candidate_skill_links": [
            link.to_dict() for link in generated.candidate_skill_links
        ],
        "verifier_decisions": [
            decision.to_dict() for decision in verification.decisions
        ],
        "scorer_vector": {
            "synthetic_test_input": True,
            "evidence_origin": EVALUATION_FIXTURE_EVIDENCE_ORIGIN,
            "artifact_id": practice.artifact_id,
            "artifact_version": practice.artifact_version,
            "candidate_answer_digest": sha256_text(answer),
            "scorer_id": f"{practice.content['item_kind']}@1.0.0",
            "expected_correct": True,
            "expected_score": 1.0,
            "product_attempt_record": False,
            "human_learner_projection_eligible": False,
        },
        "fixture_semantics": {
            "synthetic": True,
            "synthetic_scope": "engineering_fixture_only",
            "attempt_evidence_origin": EVALUATION_FIXTURE_EVIDENCE_ORIGIN,
            "human_learner_projection_eligible": False,
            "cohort_denominator_eligible": False,
            "calibration_eligible": False,
            "causal_claim_eligible": False,
            "fairness_claim_eligible": False,
            "learning_effect_claim_eligible": False,
        },
    }
    _assert_synthetic_case_is_not_human_evidence(case)
    return case


def _assert_synthetic_case_is_not_human_evidence(case: dict[str, Any]) -> None:
    encoded = canonical_json(case)
    forbidden = (
        '"evidence_origin":"human_local_interactive"',
        '"practice_attempt"',
        '"attempt_id"',
        '"human_response_accepted"',
    )
    present = [token for token in forbidden if token in encoded]
    if present:
        raise RuntimeError(f"synthetic case contains product learner evidence: {present}")
    if re.search(r'"t_[A-P]{40}"', encoded):
        raise RuntimeError("synthetic case contains a product practice-attempt identifier")
    scorer = case.get("scorer_vector", {})
    semantics = case.get("fixture_semantics", {})
    if (
        scorer.get("synthetic_test_input") is not True
        or scorer.get("evidence_origin") != EVALUATION_FIXTURE_EVIDENCE_ORIGIN
        or scorer.get("product_attempt_record") is not False
        or scorer.get("human_learner_projection_eligible") is not False
        or semantics.get("synthetic") is not True
        or semantics.get("attempt_evidence_origin")
        != EVALUATION_FIXTURE_EVIDENCE_ORIGIN
        or semantics.get("human_learner_projection_eligible") is not False
    ):
        raise RuntimeError("synthetic scorer provenance is not evaluation-only")


def command_version(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    text = (result.stdout or result.stderr).strip().splitlines()
    return text[0] if text else "unknown"


def pdf_validation(pdf_path: Path) -> dict[str, Any]:
    import pdfplumber
    import pypdf
    import reportlab

    if pypdf.__version__ != "6.10.0":
        raise RuntimeError("fixture validation requires pypdf 6.10.0")
    if pdfplumber.__version__ != "0.11.7":
        raise RuntimeError("fixture validation requires pdfplumber 0.11.7")

    reader = pypdf.PdfReader(str(pdf_path), strict=True)
    pypdf_text = "\f".join(
        page.extract_text(extraction_mode="layout") or "" for page in reader.pages
    )
    with pdfplumber.open(str(pdf_path)) as document:
        plumber_pages = [page.extract_text() or "" for page in document.pages]
    pdftotext = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    required_phrases = [statement for page in PDF_PAGES for statement in page]
    for extractor, text in (
        ("pypdf", pypdf_text),
        ("pdfplumber", "\f".join(plumber_pages)),
        ("pdftotext", pdftotext),
    ):
        missing = [phrase for phrase in required_phrases if phrase not in text]
        if missing:
            raise RuntimeError(f"{extractor} missed fixture phrases: {missing}")

    info = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    page_match = re.search(r"^Pages:\s+(\d+)$", info, re.MULTILINE)
    encrypted_match = re.search(r"^Encrypted:\s+(\S+)$", info, re.MULTILINE)
    if page_match is None or int(page_match.group(1)) != len(PDF_PAGES):
        raise RuntimeError("pdfinfo page count mismatch")
    if encrypted_match is None or encrypted_match.group(1).lower() != "no":
        raise RuntimeError("fixture PDF must not be encrypted")

    with tempfile.TemporaryDirectory(prefix="lumi-p03-pdf-render-") as temporary:
        prefix = Path(temporary) / "page"
        subprocess.run(
            ["pdftoppm", "-png", "-r", "96", str(pdf_path), str(prefix)],
            check=True,
            capture_output=True,
        )
        renders = sorted(Path(temporary).glob("page-*.png"))
        if len(renders) != len(PDF_PAGES):
            raise RuntimeError("pdftoppm render page count mismatch")
        render_hashes = [sha256_bytes(path.read_bytes()) for path in renders]

    return {
        "reportlab_version": reportlab.Version,
        "invariant_mode": True,
        "pypdf_version": pypdf.__version__,
        "pdfplumber_version": pdfplumber.__version__,
        "pdfinfo_version": command_version(["pdfinfo", "-v"]),
        "pdftoppm_version": command_version(["pdftoppm", "-v"]),
        "page_count": len(reader.pages),
        "encrypted": bool(reader.is_encrypted),
        "pypdf_text_sha256": sha256_text(pypdf_text),
        "pdfplumber_text_sha256": sha256_text("\f".join(plumber_pages)),
        "pdftotext_sha256": sha256_text(pdftotext),
        "required_phrase_count": len(required_phrases),
        "all_required_phrases_extracted": True,
        "render_page_count": len(PDF_PAGES),
        "render_png_sha256": render_hashes,
        "temporary_renders_retained": False,
    }


def file_record(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": path.name, "byte_count": len(raw), "sha256": sha256_bytes(raw)}


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = FIXTURE_DIR / "text_bearing_chinese.pdf"
    pasted_path = FIXTURE_DIR / "pasted_text.txt"
    generate_pdf(pdf_path)
    pasted_path.write_text(PASTED_TEXT, encoding="utf-8", newline="\n")

    pasted_case = make_case(
        "pasted-text-chinese-v1",
        parse_pasted_text(PASTED_TEXT),
        "资料分析基本规则",
    )
    pdf_case = make_case(
        "text-pdf-chinese-v1",
        parse_text_pdf(pdf_path.read_bytes()),
        "证据式学习规则",
    )
    write_json(FIXTURE_DIR / "pasted_text.source.json", pasted_case["source_document"])
    write_json(FIXTURE_DIR / "pasted_text.case.json", pasted_case)
    write_json(
        FIXTURE_DIR / "text_bearing_chinese.source.json",
        pdf_case["source_document"],
    )
    write_json(FIXTURE_DIR / "text_bearing_chinese.case.json", pdf_case)

    generated_files = [
        FIXTURE_DIR / "requirements.txt",
        FIXTURE_DIR / "generate_fixtures.py",
        FIXTURE_DIR / "validate_contracts.py",
        pasted_path,
        FIXTURE_DIR / "pasted_text.source.json",
        FIXTURE_DIR / "pasted_text.case.json",
        pdf_path,
        FIXTURE_DIR / "text_bearing_chinese.source.json",
        FIXTURE_DIR / "text_bearing_chinese.case.json",
    ]
    file_records = [file_record(path) for path in generated_files]
    generator_script_sha256 = next(
        item["sha256"]
        for item in file_records
        if item["path"] == "generate_fixtures.py"
    )
    manifest = {
        "schema_version": "lumi.study-pack-fixture-manifest.v1",
        "fixture_origin": "synthetic_original_engineering_only",
        "contains_pii_or_secrets": False,
        "generator": {
            "script": "generate_fixtures.py",
            "script_sha256": generator_script_sha256,
            "fixture_generator_version": FIXTURE_GENERATOR_VERSION,
            "implementation_id": GENERATOR_ID,
            "id_namespace_version": ID_NAMESPACE_VERSION,
            "id_namespace_formula": ID_NAMESPACE_FORMULA,
            "reportlab_invariant": True,
            "network_calls": 0,
            "ocr_calls": 0,
            "web_calls": 0,
        },
        "synthetic_evidence_guard": {
            "product_practice_attempt_records": 0,
            "human_local_interactive_records": 0,
            "product_attempt_ids": 0,
            "evaluation_fixture_scorer_vectors": sum(
                case["scorer_vector"].get("evidence_origin")
                == EVALUATION_FIXTURE_EVIDENCE_ORIGIN
                for case in (pasted_case, pdf_case)
            ),
            "scorer_vectors_are_product_evidence": False,
        },
        "schema_vocabulary_guard": {
            "canonical_pack_schema_version": "lumi.study-pack.v1",
            "detail_schema_version": "lumi.study-pack-detail.v1",
            "canonical_attempt_schema_version": "lumi.study-pack-attempt.v1",
            "attempt_result_schema_version": "lumi.study-pack-attempt-result.v1",
            "detail_records_in_synthetic_cases": 0,
            "attempt_result_records_in_synthetic_cases": 0,
        },
        "files": file_records,
        "pdf_validation": pdf_validation(pdf_path),
    }
    write_json(FIXTURE_DIR / "fixture-manifest.json", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
