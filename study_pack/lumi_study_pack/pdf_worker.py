from __future__ import annotations

import json
import sys

from .parsing import MAX_PDF_BYTES, extract_pdf_worker_payload


def main() -> int:
    payload = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
    if len(payload) > MAX_PDF_BYTES:
        result = {"ok": False, "code": "source_too_large"}
    else:
        result = extract_pdf_worker_payload(payload)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
