from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .api import create_server
from .application import SidecarApplication


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Lumi loopback-only local sidecar")
    result.add_argument("--db", default=str(Path.home() / ".hermes" / "sidecar.sqlite3"))
    commands = result.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve the API on 127.0.0.1 only")
    serve.add_argument("--port", type=int, default=8765)
    commands.add_parser("capabilities", help="print capabilities without starting HTTP")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    database = Path(args.db).expanduser()
    database.parent.mkdir(parents=True, exist_ok=True)
    application = SidecarApplication(database)
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
