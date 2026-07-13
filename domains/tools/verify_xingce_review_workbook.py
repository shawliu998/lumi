#!/usr/bin/env python3
"""Derive release attestations only from a completed Xingce review workbook.

This verifier is deliberately narrow.  It reads a human-completed OOXML
workbook, validates every record of one draft pack against the signing row,
then writes an attestation file.  It never fills in approvals, reviewer IDs,
or dates.  A release build can therefore bind its payload to the exact
workbook that supplied the two reviewer decisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from hermes_domains.xingce_adaptive_pack import load_xingce_adaptive_pack


ATTESTATION_SCHEMA = "lumi.xingce-review-workbook-attestations.v1"
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REF = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


class WorkbookReviewError(ValueError):
    """The review workbook cannot safely serve as release evidence."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _column_index(cell_reference: str) -> int:
    match = _CELL_REF.fullmatch(cell_reference)
    if not match:
        raise WorkbookReviewError(f"invalid worksheet cell reference: {cell_reference!r}")
    value = 0
    for character in match.group(1):
        value = value * 26 + ord(character) - ord("A") + 1
    return value


def _text(element: ET.Element | None) -> str:
    return "" if element is None else "".join(element.itertext())


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [_text(item) for item in root.findall(f"{{{_MAIN_NS}}}si")]


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return _text(cell.find(f"{{{_MAIN_NS}}}is"))
    value = _text(cell.find(f"{{{_MAIN_NS}}}v"))
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (IndexError, ValueError) as exc:
            raise WorkbookReviewError("invalid shared string reference") from exc
    return value


def _worksheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relation_targets = {
        relation.get("Id"): relation.get("Target", "")
        for relation in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
    }
    worksheets: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        name = sheet.get("name", "")
        relation_id = sheet.get(f"{{{_DOC_REL_NS}}}id")
        target = relation_targets.get(relation_id)
        if not name or not target:
            raise WorkbookReviewError("workbook sheet relationship is incomplete")
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        worksheets[name] = path
    return worksheets


def _read_sheet(archive: zipfile.ZipFile, path: str, shared_strings: list[str]) -> dict[int, dict[int, str]]:
    root = ET.fromstring(archive.read(path))
    result: dict[int, dict[int, str]] = {}
    for row in root.findall(f".//{{{_MAIN_NS}}}sheetData/{{{_MAIN_NS}}}row"):
        row_number = int(row.get("r", "0"))
        cells: dict[int, str] = {}
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            reference = cell.get("r", "")
            cells[_column_index(reference)] = _cell_value(cell, shared_strings).strip()
        if cells:
            result[row_number] = cells
    return result


def _find_header_row(sheet: dict[int, dict[int, str]], required: set[str], sheet_name: str) -> tuple[int, dict[str, int]]:
    for row_number, row in sorted(sheet.items()):
        columns = {value: column for column, value in row.items() if value}
        if required.issubset(columns):
            return row_number, columns
    missing = ", ".join(sorted(required))
    raise WorkbookReviewError(f"{sheet_name} is missing the required headers: {missing}")


def _require_text(value: str, label: str) -> str:
    result = value.strip()
    if not result:
        raise WorkbookReviewError(f"{label} is required")
    return result


def _require_iso_date(value: str, label: str) -> str:
    candidate = _require_text(value, label)
    try:
        parsed = date.fromisoformat(candidate)
    except ValueError as exc:
        raise WorkbookReviewError(f"{label} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != candidate:
        raise WorkbookReviewError(f"{label} must use YYYY-MM-DD")
    return candidate


def _values_for_pack(sheet: dict[int, dict[int, str]], *, header_row: int, columns: dict[str, int], pack_id: str) -> list[dict[str, str]]:
    pack_column = columns["题包"]
    rows: list[dict[str, str]] = []
    for row_number, row in sorted(sheet.items()):
        if row_number <= header_row or row.get(pack_column, "") != pack_id:
            continue
        values = {header: row.get(column, "").strip() for header, column in columns.items()}
        values["__row__"] = str(row_number)
        rows.append(values)
    return rows


def verify(source: str | Path, review_workbook: str | Path, release_version: str) -> dict[str, Any]:
    """Validate one pack's rows and return attestation facts from the workbook."""

    source_path = Path(source).resolve()
    workbook_path = Path(review_workbook).resolve()
    version = release_version.strip()
    if not version:
        raise WorkbookReviewError("release_version is required")
    if not workbook_path.is_file():
        raise WorkbookReviewError("completed review workbook is required")

    pack = load_xingce_adaptive_pack(source_path)
    pack_id = pack["pack_id"]
    expected_record_ids = {record["record_id"] for record in pack["records"]}

    try:
        with zipfile.ZipFile(workbook_path) as archive:
            shared_strings = _read_shared_strings(archive)
            worksheet_paths = _worksheet_paths(archive)
            try:
                signing_sheet = _read_sheet(archive, worksheet_paths["题包签署"], shared_strings)
                item_sheet = _read_sheet(archive, worksheet_paths["逐题审核"], shared_strings)
            except KeyError as exc:
                raise WorkbookReviewError("workbook must contain 题包签署 and 逐题审核 worksheets") from exc
    except zipfile.BadZipFile as exc:
        raise WorkbookReviewError("review workbook must be a valid .xlsx file") from exc

    signing_headers = {"题包", "逻辑审核人 ID", "逻辑审核日期（YYYY-MM-DD）", "编辑/权属审核人 ID", "编辑/权属审核日期（YYYY-MM-DD）"}
    sign_header_row, sign_columns = _find_header_row(signing_sheet, signing_headers, "题包签署")
    signing_rows = _values_for_pack(signing_sheet, header_row=sign_header_row, columns=sign_columns, pack_id=pack_id)
    if len(signing_rows) != 1:
        raise WorkbookReviewError(f"题包签署 must contain exactly one row for {pack_id}")
    signing = signing_rows[0]
    logic_reviewer = _require_text(signing["逻辑审核人 ID"], "signing logic reviewer ID")
    logic_date = _require_iso_date(signing["逻辑审核日期（YYYY-MM-DD）"], "signing logic review date")
    editorial_reviewer = _require_text(signing["编辑/权属审核人 ID"], "signing editorial/rights reviewer ID")
    editorial_date = _require_iso_date(signing["编辑/权属审核日期（YYYY-MM-DD）"], "signing editorial/rights review date")
    if logic_reviewer == editorial_reviewer:
        raise WorkbookReviewError("logic and editorial/rights reviewers must be different people")

    item_headers = {"题包", "记录 ID", "逻辑结论", "逻辑审核人", "逻辑审核日期", "编辑/权属结论", "编辑审核人", "编辑审核日期"}
    item_header_row, item_columns = _find_header_row(item_sheet, item_headers, "逐题审核")
    item_rows = _values_for_pack(item_sheet, header_row=item_header_row, columns=item_columns, pack_id=pack_id)
    item_ids = [row["记录 ID"] for row in item_rows]
    if len(item_ids) != len(set(item_ids)) or set(item_ids) != expected_record_ids:
        raise WorkbookReviewError(f"逐题审核 must cover every record of {pack_id} exactly once")
    for row in item_rows:
        location = f"逐题审核 row {row['__row__']} ({pack_id}/{row['记录 ID']})"
        if row["逻辑结论"] != "Approved" or row["编辑/权属结论"] != "Approved":
            raise WorkbookReviewError(f"{location} requires Approved from both reviewers")
        if _require_text(row["逻辑审核人"], f"{location} logic reviewer") != logic_reviewer:
            raise WorkbookReviewError(f"{location} logic reviewer must match the signing row")
        if _require_iso_date(row["逻辑审核日期"], f"{location} logic review date") != logic_date:
            raise WorkbookReviewError(f"{location} logic review date must match the signing row")
        if _require_text(row["编辑审核人"], f"{location} editorial reviewer") != editorial_reviewer:
            raise WorkbookReviewError(f"{location} editorial reviewer must match the signing row")
        if _require_iso_date(row["编辑审核日期"], f"{location} editorial review date") != editorial_date:
            raise WorkbookReviewError(f"{location} editorial review date must match the signing row")

    return {
        "schema_version": ATTESTATION_SCHEMA,
        "release_version": version,
        "source_pack": {
            "pack_id": pack_id,
            "pack_version": pack["pack_version"],
            "records_sha256": _sha256(source_path / "records.json"),
        },
        "review_workbook": {"name": workbook_path.name, "sha256": _sha256(workbook_path)},
        "reviewer_attestations": [
            {"review_kind": "logic", "reviewer_id": logic_reviewer, "reviewed_at": logic_date, "status": "approved"},
            {"review_kind": "editorial_rights", "reviewer_id": editorial_reviewer, "reviewed_at": editorial_date, "status": "approved"},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a completed Xingce review workbook and derive release attestations")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--review-workbook", required=True, type=Path)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise WorkbookReviewError("attestation output already exists")
    if not output.parent.is_dir():
        raise WorkbookReviewError("attestation output directory does not exist")
    try:
        result = verify(args.source, args.review_workbook, args.release_version)
    except WorkbookReviewError as exc:
        raise SystemExit(f"review verification failed: {exc}") from exc
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
