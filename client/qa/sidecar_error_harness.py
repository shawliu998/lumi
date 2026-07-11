#!/usr/bin/env python3
"""QA-only HTTP harness for a connected sidecar whose planning read returns 500."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path == "/v1/health":
            self._json(200, {
                "status": "ok",
                "service": "hermes-local-sidecar",
                "version": "0.3.0",
                "local_only": True,
            })
            return
        if self.path == "/v1/skills/report":
            self._json(200, {"policy": "trace-summary-v1", "items": []})
            return
        self._json(500, {
            "error": {
                "code": "qa_injected_planning_failure",
                "message": "QA-only injected planning failure",
                "request_id": "qa-error-harness",
            }
        })

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler contract
        self.send_response(204)
        self._cors()
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:1420")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type, X-Request-ID")
        self.send_header("Cache-Control", "no-store")

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("Lumi QA error harness port=8765", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
