from __future__ import annotations

import zlib
from io import BytesIO


CHINESE_SOURCE = (
    "增长率用于描述数量随时间变化的相对幅度。"
    "基期量是计算增长率时使用的分母。"
    "现期量减去基期量可以得到增长量。\r\n\r\n"
    "比较两个时期时必须保持统计口径一致。"
    "独立作答能够检验知识是否真正迁移。"
)


def opaque_id(prefix: str, number: int) -> str:
    raw = number.to_bytes(20, "big")
    encoded = "".join(
        chr(ord("A") + nibble)
        for byte in raw
        for nibble in (byte >> 4, byte & 0x0F)
    )
    return prefix + encoded


class SequentialIdFactory:
    def __init__(self) -> None:
        self.value = 100

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return opaque_id(prefix, self.value)


def make_text_pdf(lines: list[str]) -> bytes:
    commands = []
    y = 740
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"BT /F1 12 Tf 72 {y} Td ({escaped}) Tj ET")
        y -= 24
    stream = "\n".join(commands).encode("latin-1")
    return _build_pdf(stream, filter_name=None)


def make_compression_bomb_pdf(output_size: int) -> bytes:
    stream = zlib.compress(b" " * output_size, level=9)
    return _build_pdf(stream, filter_name="FlateDecode")


def make_encrypted_pdf() -> bytes:
    from pypdf import PdfWriter

    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("local-test-password")
    writer.write(output)
    return output.getvalue()


def _build_pdf(stream: bytes, filter_name: str | None) -> bytes:
    filter_entry = f" /Filter /{filter_name}" if filter_name else ""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            f"<< /Length {len(stream)}{filter_entry} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        ),
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)
