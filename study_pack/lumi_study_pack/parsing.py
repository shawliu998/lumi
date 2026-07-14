from __future__ import annotations

import base64
import binascii
from io import BytesIO
import json
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .models import (
    NORMALIZATION_NAME,
    NORMALIZATION_VERSION,
    ParsedSource,
    SourceSegment,
    StudyPackError,
)


MAX_PASTED_BYTES = 512 * 1024
MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 120
MAX_CODEPOINTS = 250_000
PDF_DEADLINE_SECONDS = 10.0
MAX_PDF_DECOMPRESSED_STREAM_BYTES = 16 * 1024 * 1024
MAX_PDF_WORKER_ADDRESS_SPACE_BYTES = 384 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ExtractedPdf:
    page_count: int
    encrypted: bool
    page_texts: tuple[str, ...]
    parser_name: str
    parser_version: str


class PdfBackend(Protocol):
    def extract(self, pdf_bytes: bytes, deadline_seconds: float) -> ExtractedPdf: ...


class PyPdfBackend:
    """Pure-Python text parser in a dedicated, thread-safe subprocess."""

    def extract(self, pdf_bytes: bytes, deadline_seconds: float) -> ExtractedPdf:
        timeout = min(deadline_seconds, PDF_DEADLINE_SECONDS)
        try:
            completed = subprocess.run(
                pdf_worker_command(),
                input=pdf_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise StudyPackError("pdf_parse_failed", "PDF parser deadline exceeded") from None
        try:
            message = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise StudyPackError("pdf_parse_failed", "PDF parser failed") from None
        if not isinstance(message, dict) or message.get("ok") is not True:
            code = message.get("code") if isinstance(message, dict) else None
            if code not in {
                "pdf_parse_failed",
                "pdf_encrypted_unsupported",
                "source_too_large",
            }:
                code = "pdf_parse_failed"
            raise StudyPackError(str(code), "PDF text extraction failed")
        return ExtractedPdf(
            page_count=int(message["page_count"]),
            encrypted=False,
            page_texts=tuple(str(item) for item in message["page_texts"]),
            parser_name="pypdf",
            parser_version=str(message["parser_version"]),
        )


def prepare_frozen_pdf_worker() -> None:
    """Compatibility hook; the worker is a subprocess, not a fork/spawn child."""

    return None


def pdf_worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--lumi-study-pack-pdf-worker"]
    return [sys.executable, "-m", "lumi_study_pack.pdf_worker"]


def extract_pdf_worker_payload(pdf_bytes: bytes) -> dict[str, Any]:
    _apply_worker_resource_limits()
    try:
        import pypdf
    except ImportError:
        return {"ok": False, "code": "pdf_parse_failed"}
    if getattr(pypdf, "__version__", None) != "6.10.0":
        return {"ok": False, "code": "pdf_parse_failed"}
    _configure_pypdf_limits(pypdf)
    try:
        reader = pypdf.PdfReader(BytesIO(pdf_bytes), strict=True)
        if reader.is_encrypted:
            return {"ok": False, "code": "pdf_encrypted_unsupported"}
        page_count = len(reader.pages)
        if page_count < 1 or page_count > MAX_PDF_PAGES:
            return {"ok": False, "code": "source_too_large"}
        pages: list[str] = []
        total = 0
        for page in reader.pages:
            extracted = page.extract_text(extraction_mode="layout") or ""
            total += len(extracted)
            if total > MAX_CODEPOINTS:
                return {"ok": False, "code": "source_too_large"}
            pages.append(extracted)
        return {
            "ok": True,
            "page_count": page_count,
            "page_texts": pages,
            "parser_version": pypdf.__version__,
        }
    except Exception:
        return {"ok": False, "code": "pdf_parse_failed"}


def _configure_pypdf_limits(pypdf_module: Any) -> None:
    filters = pypdf_module.filters
    for name in (
        "MAX_DECLARED_STREAM_LENGTH",
        "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
        "JBIG2_MAX_OUTPUT_LENGTH",
        "LZW_MAX_OUTPUT_LENGTH",
        "RUN_LENGTH_MAX_OUTPUT_LENGTH",
        "ZLIB_MAX_OUTPUT_LENGTH",
    ):
        setattr(filters, name, MAX_PDF_DECOMPRESSED_STREAM_BYTES)
    filters.ZLIB_MAX_RECOVERY_INPUT_LENGTH = min(
        filters.ZLIB_MAX_RECOVERY_INPUT_LENGTH, MAX_PDF_BYTES
    )


def _apply_worker_resource_limits() -> None:
    try:
        import resource
    except ImportError:
        return
    limits = (
        (getattr(resource, "RLIMIT_AS", None), MAX_PDF_WORKER_ADDRESS_SPACE_BYTES),
        (getattr(resource, "RLIMIT_CPU", None), int(PDF_DEADLINE_SECONDS)),
    )
    for resource_kind, maximum in limits:
        if resource_kind is None:
            continue
        try:
            resource.setrlimit(resource_kind, (maximum, maximum))
        except (OSError, ValueError):
            # pypdf stream/output caps and the parent wall-clock deadline remain
            # mandatory even on platforms without this additional OS limit.
            continue


def normalize_text(value: str) -> str:
    canonical_newlines = value.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", canonical_newlines)


def parse_source(
    source: Mapping[str, Any], *, pdf_backend: PdfBackend | None = None
) -> ParsedSource:
    if not isinstance(source, Mapping) or not isinstance(source.get("kind"), str):
        raise StudyPackError("invalid_source_body", "source union is invalid")
    kind = source["kind"]
    if kind == "pasted_text":
        if set(source) != {"kind", "text"} or not isinstance(source.get("text"), str):
            raise StudyPackError("invalid_source_body", "pasted source body is invalid")
        return parse_pasted_text(source["text"])
    if kind == "text_pdf":
        if set(source) != {"kind", "pdf_base64"} or not isinstance(
            source.get("pdf_base64"), str
        ):
            raise StudyPackError("invalid_source_body", "PDF source body is invalid")
        try:
            raw = base64.b64decode(source["pdf_base64"], validate=True)
        except (binascii.Error, ValueError):
            raise StudyPackError("invalid_source_body", "PDF base64 is invalid") from None
        return parse_text_pdf(raw, backend=pdf_backend)
    raise StudyPackError("invalid_source_body", "source kind is unsupported")


def parse_pasted_text(text: str) -> ParsedSource:
    if not isinstance(text, str):
        raise StudyPackError("invalid_source_body", "pasted text must be UTF-8 text")
    try:
        original = text.encode("utf-8")
    except UnicodeEncodeError:
        raise StudyPackError("invalid_source_body", "pasted text is not valid Unicode") from None
    if not original or not text.strip():
        raise StudyPackError("invalid_source_body", "pasted text cannot be empty")
    if len(original) > MAX_PASTED_BYTES:
        raise StudyPackError("source_too_large", "pasted text byte limit exceeded")
    normalized = normalize_text(text)
    _validate_codepoint_limit(normalized)
    raw_sections = re.split(r"(?:\n[ \t]*\n)+", normalized)
    sections = tuple(
        SourceSegment("section", index, section)
        for index, section in enumerate(raw_sections, start=1)
        if section != ""
    )
    if not sections:
        raise StudyPackError("invalid_source_body", "pasted text has no sections")
    if len(sections) > MAX_PDF_PAGES:
        raise StudyPackError("source_too_large", "source locator limit exceeded")
    return ParsedSource(
        input_kind="pasted_text",
        media_type="text/plain;charset=utf-8",
        original_bytes=original,
        normalized_text=normalized,
        segments=sections,
        parser_name="lumi-pasted-section-parser",
        parser_version="1.0.0",
        normalization_name=NORMALIZATION_NAME,
        normalization_version=NORMALIZATION_VERSION,
    )


def parse_text_pdf(
    pdf_bytes: bytes, *, backend: PdfBackend | None = None
) -> ParsedSource:
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
        raise StudyPackError("invalid_source_body", "PDF bytes are required")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise StudyPackError("source_too_large", "PDF byte limit exceeded")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise StudyPackError("pdf_parse_failed", "PDF header is invalid")
    extracted = (backend or PyPdfBackend()).extract(
        pdf_bytes, PDF_DEADLINE_SECONDS
    )
    if extracted.encrypted:
        raise StudyPackError("pdf_encrypted_unsupported", "encrypted PDF is unsupported")
    if extracted.page_count < 1 or extracted.page_count > MAX_PDF_PAGES:
        raise StudyPackError("source_too_large", "PDF page limit exceeded")
    if len(extracted.page_texts) != extracted.page_count:
        raise StudyPackError("pdf_parse_failed", "PDF page extraction is inconsistent")
    normalized_pages = tuple(normalize_text(page) for page in extracted.page_texts)
    if not any(page.strip() for page in normalized_pages):
        raise StudyPackError(
            "pdf_text_unavailable_ocr_required",
            "PDF has no extractable text layer; OCR is not available",
        )
    normalized = "\f".join(normalized_pages)
    _validate_codepoint_limit(normalized)
    warnings = (
        ("empty_text_page",)
        if any(not page.strip() for page in normalized_pages)
        else ()
    )
    return ParsedSource(
        input_kind="text_pdf",
        media_type="application/pdf",
        original_bytes=pdf_bytes,
        normalized_text=normalized,
        segments=tuple(
            SourceSegment("page", index, page)
            for index, page in enumerate(normalized_pages, start=1)
        ),
        parser_name=extracted.parser_name,
        parser_version=extracted.parser_version,
        normalization_name=NORMALIZATION_NAME,
        normalization_version=NORMALIZATION_VERSION,
        warnings=warnings,
    )


def _validate_codepoint_limit(value: str) -> None:
    if len(value) > MAX_CODEPOINTS:
        raise StudyPackError("source_too_large", "normalized text code-point limit exceeded")
