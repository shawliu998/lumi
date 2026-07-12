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
INTERNAL_LEARNING_ATTEMPT_ORIGIN_ENV = "LUMI_INTERNAL_LEARNING_ATTEMPT_ORIGIN"
INTERNAL_EVALUATION_PROJECTION_ENV = "LUMI_INTERNAL_EVALUATION_PROJECTION"
JUDGMENT_PACK_ROOT_ENV = "LUMI_JUDGMENT_PACK_ROOT"


def configured_study_pack_attempt_origin() -> str:
    value = os.environ.get(INTERNAL_ATTEMPT_ORIGIN_ENV)
    if value is None:
        return HUMAN_ATTEMPT_EVIDENCE_ORIGIN
    if value == EVALUATION_ATTEMPT_EVIDENCE_ORIGIN:
        return value
    raise SystemExit("invalid internal Study Pack attempt origin")


def configured_learning_attempt_origin() -> str:
    value = os.environ.get(INTERNAL_LEARNING_ATTEMPT_ORIGIN_ENV)
    if value is None:
        return HUMAN_ATTEMPT_EVIDENCE_ORIGIN
    if value == EVALUATION_ATTEMPT_EVIDENCE_ORIGIN:
        return value
    raise SystemExit("invalid internal learning attempt origin")


def configured_evaluation_projection(*, attempt_origin: str) -> bool:
    value = os.environ.get(INTERNAL_EVALUATION_PROJECTION_ENV)
    if value is None:
        return False
    if value != "1" or attempt_origin != EVALUATION_ATTEMPT_EVIDENCE_ORIGIN:
        raise SystemExit("invalid internal evaluation projection configuration")
    return True


def configured_judgment_pack_root() -> Path | None:
    """Return an explicitly selected, locally reviewed Domain Pack path.

    The repository draft is intentionally not a default.  A missing value keeps
    the workspace honest (`content_review_required`) rather than silently
    loading unreviewed content or an external question bank.
    """

    value = os.environ.get(JUDGMENT_PACK_ROOT_ENV)
    if value is None:
        return None
    root = Path(value).expanduser()
    if not root.is_dir():
        raise SystemExit("configured judgment pack root is not a directory")
    return root


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
    attempt_origin = configured_learning_attempt_origin()
    evaluation_projection_enabled = configured_evaluation_projection(
        attempt_origin=attempt_origin
    )
    application = SidecarApplication(
        database,
        study_pack_attempt_evidence_origin=(
            configured_study_pack_attempt_origin()
        ),
        attempt_evidence_origin=attempt_origin,
        review_commit_evidence_origins=(
            frozenset({EVALUATION_ATTEMPT_EVIDENCE_ORIGIN})
            if evaluation_projection_enabled
            else None
        ),
        evaluation_projection_enabled=evaluation_projection_enabled,
        judgment_pack_root=configured_judgment_pack_root(),
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
