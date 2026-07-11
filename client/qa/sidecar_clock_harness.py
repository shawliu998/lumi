#!/usr/bin/env python3
"""QA-only local sidecar launcher with an explicit injected calendar date.

This file is test infrastructure, not a production service entry point. It uses
the real SidecarApplication and database while replacing only today_provider so
browser QA can verify historical-plan guards and next-learning-day resurfacing.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from hermes_service.api import create_server
from hermes_service.application import SidecarApplication


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    injected_date = args.date
    application = SidecarApplication(
        str(args.db),
        today_provider=lambda: injected_date,
    )
    application.health()
    server = create_server(application, port=args.port)
    print(
        f"Lumi QA sidecar date={args.date.isoformat()} port={server.server_address[1]}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
