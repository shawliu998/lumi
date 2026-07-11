from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from lumi_study_pack import pdf_worker_main
from lumi_study_pack.store import (
    EVALUATION_ATTEMPT_EVIDENCE_ORIGIN,
    HUMAN_ATTEMPT_EVIDENCE_ORIGIN,
)

from .api import create_server
from .application import SidecarApplication


INTERNAL_ATTEMPT_ORIGIN_ENV = "LUMI_INTERNAL_STUDY_PACK_ATTEMPT_ORIGIN"


def configured_study_pack_attempt_origin() -> str:
    value = os.environ.get(INTERNAL_ATTEMPT_ORIGIN_ENV)
    if value is None:
        return HUMAN_ATTEMPT_EVIDENCE_ORIGIN
    if value == EVALUATION_ATTEMPT_EVIDENCE_ORIGIN:
        return value
    raise SystemExit("invalid internal Study Pack attempt origin")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Lumi loopback-only local sidecar")
    result.add_argument("--db", default=str(Path.home() / ".hermes" / "sidecar.sqlite3"))
    commands = result.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve the API on 127.0.0.1 only")
    serve.add_argument("--port", type=int, default=8765)
    commands.add_parser("capabilities", help="print capabilities without starting HTTP")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--lumi-study-pack-pdf-worker"]:
        return pdf_worker_main()
    args = parser().parse_args(arguments)
    database = Path(args.db).expanduser()
    database.parent.mkdir(parents=True, exist_ok=True)
    application = SidecarApplication(
        database,
        study_pack_attempt_evidence_origin=(
            configured_study_pack_attempt_origin()
        ),
    )
    if args.command == "capabilities":
        print(json.dumps(application.capabilities(), ensure_ascii=False, indent=2))
        return 0
    server = create_server(application, port=args.port)
    actual_port = server.server_address[1]
    print(f"Lumi sidecar listening on http://127.0.0.1:{actual_port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
