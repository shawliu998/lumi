from __future__ import annotations

import base64
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from helpers import make_compression_bomb_pdf, make_encrypted_pdf, make_text_pdf
from lumi_study_pack.models import StudyPackError
from lumi_study_pack.parsing import (
    MAX_CODEPOINTS,
    MAX_PASTED_BYTES,
    MAX_PDF_BYTES,
    MAX_PDF_DECOMPRESSED_STREAM_BYTES,
    ExtractedPdf,
    PyPdfBackend,
    normalize_text,
    pdf_worker_command,
    parse_pasted_text,
    parse_source,
    parse_text_pdf,
    prepare_frozen_pdf_worker,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class StaticBackend:
    def __init__(self, extracted: ExtractedPdf) -> None:
        self.extracted = extracted

    def extract(self, pdf_bytes: bytes, deadline_seconds: float) -> ExtractedPdf:
        return self.extracted


class ParsingTests(unittest.TestCase):
    def assert_code(self, code: str, function, *args, **kwargs) -> None:
        with self.assertRaises(StudyPackError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_pasted_text_normalizes_nfc_newlines_and_blank_line_sections_only(self) -> None:
        parsed = parse_pasted_text("Cafe\u0301 第一条。\r\n\r\n第二条保留  两个空格。\r第三行。")
        self.assertEqual(parsed.normalized_text, "Café 第一条。\n\n第二条保留  两个空格。\n第三行。")
        self.assertEqual(len(parsed.segments), 2)
        self.assertEqual([item.locator_index for item in parsed.segments], [1, 2])
        self.assertIn("  ", parsed.segments[1].text)
        self.assertEqual(parsed.parser_name, "lumi-pasted-section-parser")

    def test_real_pypdf_text_layer_uses_exact_dependency_and_no_path_input(self) -> None:
        raw = make_text_pdf(
            [
                "First source statement explains local evidence.",
                "Second source statement describes exact scoring.",
                "Third source statement requires citation checks.",
            ]
        )
        parsed = parse_text_pdf(raw)
        self.assertEqual(parsed.parser_name, "pypdf")
        self.assertEqual(parsed.parser_version, "6.10.0")
        self.assertEqual(parsed.segments[0].locator_kind, "page")
        self.assertIn("Second source statement", parsed.segments[0].text)
        self.assertEqual(
            parse_source(
                {
                    "kind": "text_pdf",
                    "pdf_base64": base64.b64encode(raw).decode("ascii"),
                }
            ).normalized_sha256,
            parsed.normalized_sha256,
        )
        self.assert_code(
            "invalid_source_body",
            parse_source,
            {"kind": "text_pdf", "path": "/tmp/private.pdf"},
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(parse_text_pdf, (raw, raw)))
        self.assertEqual(
            {item.normalized_sha256 for item in results}, {parsed.normalized_sha256}
        )

    def test_malformed_encrypted_scanned_and_invalid_base64_fail_stably(self) -> None:
        self.assert_code("pdf_parse_failed", parse_text_pdf, b"not-a-pdf")
        self.assert_code(
            "pdf_encrypted_unsupported",
            parse_text_pdf,
            make_encrypted_pdf(),
        )
        self.assert_code(
            "pdf_text_unavailable_ocr_required", parse_text_pdf, make_text_pdf([])
        )
        self.assert_code(
            "invalid_source_body",
            parse_source,
            {"kind": "text_pdf", "pdf_base64": "***not-base64***"},
        )

    def test_page_and_codepoint_limits_are_fail_closed(self) -> None:
        over_pages = StaticBackend(
            ExtractedPdf(121, False, tuple("x" for _ in range(121)), "fake", "1")
        )
        self.assert_code(
            "source_too_large", parse_text_pdf, b"%PDF-1.4\n", backend=over_pages
        )
        over_chars = StaticBackend(
            ExtractedPdf(1, False, ("x" * (MAX_CODEPOINTS + 1),), "fake", "1")
        )
        self.assert_code(
            "source_too_large", parse_text_pdf, b"%PDF-1.4\n", backend=over_chars
        )
        self.assert_code("source_too_large", parse_pasted_text, "x" * (MAX_CODEPOINTS + 1))
        self.assert_code(
            "source_too_large",
            parse_pasted_text,
            "é" * (MAX_PASTED_BYTES // 2 + 1),
        )
        self.assert_code(
            "source_too_large",
            parse_text_pdf,
            b"%PDF-" + b"x" * MAX_PDF_BYTES,
        )
        self.assert_code(
            "source_too_large", parse_pasted_text, "\n\n".join("section" for _ in range(121))
        )
        partial = parse_text_pdf(
            b"%PDF-1.4\n",
            backend=StaticBackend(
                ExtractedPdf(2, False, ("可提取的页面文字。", ""), "fake", "1")
            ),
        )
        self.assertEqual(partial.warnings, ("empty_text_page",))

    def test_parser_timeout_is_stable_and_does_not_use_thread_fork(self) -> None:
        with patch(
            "lumi_study_pack.parsing.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["python"], timeout=10),
        ):
            self.assert_code(
                "pdf_parse_failed", PyPdfBackend().extract, b"%PDF-1.4", 10
            )
        prepare_frozen_pdf_worker()
        source = (REPOSITORY_ROOT / "study_pack/lumi_study_pack/parsing.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('get_context("fork")', source)
        with patch("lumi_study_pack.parsing.sys.frozen", False, create=True):
            self.assertEqual(
                pdf_worker_command()[-2:], ["-m", "lumi_study_pack.pdf_worker"]
            )
        with patch("lumi_study_pack.parsing.sys.frozen", True, create=True):
            self.assertEqual(
                pdf_worker_command()[-1], "--lumi-study-pack-pdf-worker"
            )

    def test_compression_bomb_hits_worker_limit(self) -> None:
        raw = make_compression_bomb_pdf(MAX_PDF_DECOMPRESSED_STREAM_BYTES + 1)
        self.assertLess(len(raw), 8 * 1024 * 1024)
        self.assert_code("pdf_parse_failed", parse_text_pdf, raw)

    def test_pyproject_pins_only_pypdf_runtime_dependency(self) -> None:
        pyproject = (REPOSITORY_ROOT / "study_pack/pyproject.toml").read_text(
            encoding="utf-8"
        )
        self.assertIn('dependencies = ["pypdf==6.10.0"]', pyproject)
        self.assertNotIn("pdfplumber", pyproject)
        self.assertNotIn("poppler", pyproject.lower())


if __name__ == "__main__":
    unittest.main()
