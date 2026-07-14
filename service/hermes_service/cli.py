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
from .xingce_adaptive_session import XingceAdaptiveSessionConfig, XingceAdaptiveSessionService
from .xingce_question_bank import configured_export_root


INTERNAL_ATTEMPT_ORIGIN_ENV = "LUMI_INTERNAL_STUDY_PACK_ATTEMPT_ORIGIN"
INTERNAL_LEARNING_ATTEMPT_ORIGIN_ENV = "LUMI_INTERNAL_LEARNING_ATTEMPT_ORIGIN"
INTERNAL_EVALUATION_PROJECTION_ENV = "LUMI_INTERNAL_EVALUATION_PROJECTION"
JUDGMENT_PACK_ROOT_ENV = "LUMI_JUDGMENT_PACK_ROOT"
XINGCE_ADAPTIVE_PACK_ROOTS_ENV = "LUMI_XINGCE_ADAPTIVE_PACK_ROOTS"
XINGCE_FULL_BANK_EXPORT_ENV = "LUMI_XINGCE_FULL_BANK_EXPORT"
DEFAULT_RELEASED_JUDGMENT_PACK_ROOT = (
    Path(__file__).resolve().parents[2]
    / "domains"
    / "released"
    / "judgment"
    / "lumi-conditional-reasoning-v0-0.1.0-reviewed-local-20260713"
)
DEFAULT_RELEASED_XINGCE_ADAPTIVE_PACKS_ROOT = (
    Path(__file__).resolve().parents[2]
    / "domains"
    / "released"
)


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
    root = DEFAULT_RELEASED_JUDGMENT_PACK_ROOT if value is None else Path(value).expanduser()
    if value is None and not root.is_dir():
        return None
    if not root.is_dir():
        raise SystemExit("configured judgment pack root is not a directory")
    return root


def configured_xingce_adaptive_session_services(
    database: Path,
    *,
    evidence_origin: str,
) -> dict[str, XingceAdaptiveSessionService]:
    """Discover only reviewed local generic packs from declared release roots.

    A missing default root means no generic subtype is registered. An explicit
    root must exist so packaging failures cannot silently fall back to a draft
    or a mutable question-bank directory.
    """
    configured = os.environ.get(XINGCE_ADAPTIVE_PACK_ROOTS_ENV)
    roots = [Path(part).expanduser() for part in configured.split(os.pathsep)] if configured else [DEFAULT_RELEASED_XINGCE_ADAPTIVE_PACKS_ROOT]
    if configured and any(not root.is_dir() for root in roots):
        raise SystemExit("configured Xingce adaptive pack root is not a directory")
    namespace_id = "eval:local-lumi" if evidence_origin == EVALUATION_ATTEMPT_EVIDENCE_ORIGIN else "human:local-lumi"
    config = XingceAdaptiveSessionConfig(namespace_id=namespace_id, evidence_origin=evidence_origin)
    services: dict[str, XingceAdaptiveSessionService] = {}
    for root in roots:
        if not root.is_dir():
            continue
        candidates = [root] if (root / "manifest.json").is_file() else sorted(item.parent for item in root.glob("**/manifest.json"))
        for pack_root in candidates:
            try:
                manifest = json.loads((pack_root / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SystemExit("released Xingce manifest cannot be loaded") from exc
            # The released conditional-logic pack uses the older specialised
            # reasoning schema and is registered by the judgment workspace.
            # Generic adaptive discovery must skip it, never try to coerce it.
            if manifest.get("schema_version") != "lumi.xingce-adaptive-pack.v1":
                continue
            service = XingceAdaptiveSessionService(database, reviewed_pack_root=pack_root, config=config)
            subtype_id = service.pack["subtype_id"]
            if subtype_id in services:
                raise SystemExit("multiple reviewed Xingce adaptive packs declare the same subtype")
            services[subtype_id] = service
    return services


def configured_xingce_full_bank_export() -> Path | None:
    return configured_export_root(os.environ.get(XINGCE_FULL_BANK_EXPORT_ENV))


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
        xingce_adaptive_session_services=configured_xingce_adaptive_session_services(
            database,
            evidence_origin=attempt_origin,
        ),
        xingce_full_bank_export=configured_xingce_full_bank_export(),
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
