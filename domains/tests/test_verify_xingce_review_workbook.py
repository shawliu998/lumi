from __future__ import annotations

import html
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from hermes_domains.xingce_adaptive_pack import load_xingce_adaptive_pack
from tools.create_reviewed_xingce_release import create
from tools.verify_xingce_review_workbook import WorkbookReviewError, _expected_review_content, _normalized_signing_date, _require_iso_date, _review_content_matches, verify


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
PACK_ROOT = DOMAIN_ROOT / "content" / "xingce" / "common_knowledge" / "lumi-management-v0"


def _column_name(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _worksheet_xml(rows: dict[int, list[str]]) -> str:
    body: list[str] = []
    for row_number, values in sorted(rows.items()):
        cells = "".join(
            f'<c r="{_column_name(index)}{row_number}" t="inlineStr"><is><t>{html.escape(value)}</t></is></c>'
            for index, value in enumerate(values, 1)
        )
        body.append(f'<row r="{row_number}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(body)}</sheetData></worksheet>'
    )


def _write_review_workbook(path: Path, *, logic_status: str = "Approved") -> None:
    pack = load_xingce_adaptive_pack(PACK_ROOT)
    sign_headers = ["题包", "逻辑审核人 ID", "逻辑审核日期（YYYY-MM-DD）", "编辑/权属审核人 ID", "编辑/权属审核日期（YYYY-MM-DD）"]
    item_headers = [
        "题包", "记录 ID", "题干 / 微课内容", "选项", "标准答案（审核可见）",
        "候选错因（未确认）", "路由 / 目标", "无提示", "逻辑结论", "逻辑审核人",
        "逻辑审核日期", "编辑/权属结论", "编辑审核人", "编辑审核日期",
    ]
    sign_rows = {5: sign_headers, 7: [pack["pack_id"], "logic-r1", "2026-07-13", "rights-r2", "2026-07-14"]}
    item_rows: dict[int, list[str]] = {5: item_headers}
    for row_number, record in enumerate(pack["records"], 7):
        expected = _expected_review_content(record)
        item_rows[row_number] = [
            pack["pack_id"], record["record_id"], expected["题干 / 微课内容"], expected["选项"],
            expected["标准答案（审核可见）"], expected["候选错因（未确认）"], expected["路由 / 目标"],
            expected["无提示"], logic_status, "logic-r1", "2026-07-13", "Approved", "rights-r2", "2026-07-14",
        ]
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="题包签署" sheetId="1" r:id="rId1"/>'
        '<sheet name="逐题审核" sheetId="2" r:id="rId2"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        '</Relationships>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", _worksheet_xml(sign_rows))
        archive.writestr("xl/worksheets/sheet2.xml", _worksheet_xml(item_rows))


class VerifyXingceReviewWorkbookTests(unittest.TestCase):
    def test_derives_two_attestations_only_from_complete_row_level_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "completed.xlsx"
            _write_review_workbook(workbook)
            result = verify(PACK_ROOT, workbook, "0.1.0-reviewed-local-20260713")
        self.assertEqual(result["source_pack"]["pack_id"], "lumi-management-v0")
        self.assertEqual(result["review_workbook"]["name"], "completed.xlsx")
        self.assertEqual(result["reviewer_attestations"], [
            {"review_kind": "logic", "reviewer_id": "logic-r1", "reviewed_at": "2026-07-13", "status": "approved"},
            {"review_kind": "editorial_rights", "reviewer_id": "rights-r2", "reviewed_at": "2026-07-14", "status": "approved"},
        ])

    def test_rejects_any_unapproved_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "needs-revision.xlsx"
            _write_review_workbook(workbook, logic_status="Needs revision")
            with self.assertRaisesRegex(WorkbookReviewError, "requires Approved"):
                verify(PACK_ROOT, workbook, "0.1.0-reviewed-local-20260713")

    def test_normalizes_an_excel_serial_date_only_in_a_plausible_range(self) -> None:
        self.assertEqual(_require_iso_date("46216", "review date"), "2026-07-13")
        self.assertEqual(_normalized_signing_date("7.13", {"2026-07-13"}, "signing date"), "2026-07-13")
        with self.assertRaisesRegex(WorkbookReviewError, "YYYY-MM-DD"):
            _require_iso_date("1", "review date")

    def test_source_material_review_text_must_preserve_the_literal_source_prompt(self) -> None:
        record = {"prompt": "根据材料，正确的是：", "source_material": {"kind": "table"}}
        self.assertTrue(_review_content_matches(record, "题干 / 微课内容", "表格材料：甲为 10。\n\n根据材料，正确的是："))
        self.assertFalse(_review_content_matches(record, "题干 / 微课内容", "表格材料：甲为 10。"))
        self.assertFalse(_review_content_matches(record, "题干 / 微课内容", "根据材料，正确的是："))

    def test_release_builder_accepts_only_the_workbook_derived_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "completed.xlsx"
            attestations = root / "attestations.json"
            release = root / "release"
            _write_review_workbook(workbook)
            result = verify(PACK_ROOT, workbook, "0.1.0-reviewed-local-20260713")
            attestations.write_text(json.dumps(result), encoding="utf-8")
            created = create(PACK_ROOT, release, workbook, attestations)
            self.assertEqual(created["status"], "release_ready")
            self.assertEqual(created["pack_version"], "0.1.0-reviewed-local-20260713")


if __name__ == "__main__":
    unittest.main()
