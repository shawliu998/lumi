from __future__ import annotations

import json
import re
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlsplit

from .application import ServiceError, SidecarApplication


DEFAULT_ALLOWED_ORIGINS = frozenset(
    {
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "tauri://localhost",
        "https://tauri.localhost",
    }
)
MAX_BODY_BYTES = 64 * 1024
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
RUN_ROUTE = re.compile(r"^/v1/runs/([^/]+)/(trace|replay)$")
ATTEMPT_RESPONSE_ROUTE = re.compile(r"^/v1/attempts/([^/]+)/responses$")


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(
    application: SidecarApplication,
    *,
    port: int = 8765,
    host: str = "127.0.0.1",
    allowed_origins: Iterable[str] = DEFAULT_ALLOWED_ORIGINS,
) -> LocalThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("Lumi sidecar may only bind to 127.0.0.1")
    if not 0 <= port <= 65535:
        raise ValueError("port must be in [0, 65535]")
    handler = _handler_factory(application, frozenset(allowed_origins))
    return LocalThreadingHTTPServer((host, port), handler)


def _handler_factory(application: SidecarApplication, allowed_origins: frozenset[str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "HermesSidecar/0.1"
        sys_version = ""

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_OPTIONS(self) -> None:
            self._dispatch("OPTIONS")

        def do_PUT(self) -> None:
            self._method_not_allowed()

        def do_PATCH(self) -> None:
            self._method_not_allowed()

        def do_DELETE(self) -> None:
            self._method_not_allowed()

        def log_message(self, format: str, *args: Any) -> None:
            # The embedding client owns structured logging. Avoid emitting
            # request content or local filesystem details from this layer.
            return

        def _dispatch(self, method: str) -> None:
            request_id = self._request_id()
            self._active_request_id = request_id
            origin = self.headers.get("Origin")
            if origin is not None and origin not in allowed_origins:
                self._error(ServiceError(403, "origin_denied", "request origin is not allowed"), request_id)
                return
            if not self._valid_host_header():
                self._error(ServiceError(400, "invalid_host", "Host must identify the local sidecar"), request_id)
                return
            if method == "OPTIONS":
                self._send(204, None, request_id, origin)
                return
            try:
                parsed = urlsplit(self.path)
                if method == "GET":
                    payload = self._route_get(parsed.path, parse_qs(parsed.query, keep_blank_values=True))
                    self._send(200, payload, request_id, origin)
                    return
                if method == "POST" and parsed.path == "/v1/runs":
                    body = self._read_json({"mode", "run_id"})
                    if not isinstance(body.get("mode"), str):
                        raise ServiceError(400, "invalid_mode", "mode must be success, ambiguous, or offline")
                    if body.get("run_id") is not None and not isinstance(body["run_id"], str):
                        raise ServiceError(400, "invalid_run_id", "run_id must be a string")
                    payload = application.run_learning_loop(body.get("mode"), body.get("run_id"))
                    self._send(201, payload, request_id, origin)
                    return
                if method == "POST" and parsed.path == "/v1/attempts":
                    body = self._read_json(
                        {"fixture_id", "response", "confidence", "response_time_seconds", "run_id"}
                    )
                    required = {"fixture_id", "response", "confidence", "response_time_seconds"}
                    if not required.issubset(body):
                        raise ServiceError(400, "invalid_body", "attempt body is missing a required field")
                    payload = application.submit_attempt(
                        body["fixture_id"],
                        body["response"],
                        body["confidence"],
                        body["response_time_seconds"],
                        body.get("run_id"),
                    )
                    self._send(201, payload, request_id, origin)
                    return
                continuation_match = ATTEMPT_RESPONSE_ROUTE.fullmatch(parsed.path)
                if method == "POST" and continuation_match:
                    body = self._read_json(
                        {
                            "phase",
                            "expected_version",
                            "expected_state",
                            "response",
                            "confidence",
                            "response_time_seconds",
                        }
                    )
                    required = {
                        "phase",
                        "expected_version",
                        "expected_state",
                        "response",
                        "confidence",
                        "response_time_seconds",
                    }
                    if set(body) != required:
                        raise ServiceError(400, "invalid_body", "continuation body must contain every required field")
                    payload = application.continue_attempt_session(
                        unquote(continuation_match.group(1)),
                        body["phase"],
                        body["expected_version"],
                        body["expected_state"],
                        body["response"],
                        body["confidence"],
                        body["response_time_seconds"],
                    )
                    self._send(200, payload, request_id, origin)
                    return
                if method == "POST":
                    raise ServiceError(404, "route_not_found", "the requested API route does not exist")
                raise ServiceError(405, "method_not_allowed", "HTTP method is not allowed for this route")
            except ServiceError as exc:
                self._error(exc, request_id, origin)
            except Exception:
                self._error(
                    ServiceError(500, "internal_error", "an unexpected local service error occurred"),
                    request_id,
                    origin,
                )

        def _route_get(self, path: str, query: dict[str, list[str]]) -> dict[str, Any]:
            if path == "/v1/health":
                return application.health()
            if path == "/v1/capabilities":
                return application.capabilities()
            if path == "/v1/scenarios":
                domain = _single_query(query, "domain")
                mode = _single_query(query, "mode")
                unknown = set(query) - {"domain", "mode"}
                if unknown:
                    raise ServiceError(400, "invalid_query", "unsupported scenario query parameter")
                return application.scenarios(domain=domain, mode=mode)
            if path == "/v1/skills/report":
                if query:
                    raise ServiceError(400, "invalid_query", "skill report does not accept query parameters")
                return application.skill_report()
            match = RUN_ROUTE.fullmatch(path)
            if match:
                run_id = unquote(match.group(1))
                return application.trace(run_id) if match.group(2) == "trace" else application.replay(run_id)
            raise ServiceError(404, "route_not_found", "the requested API route does not exist")

        def _read_json(self, allowed_fields: set[str]) -> dict[str, Any]:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise ServiceError(415, "unsupported_media_type", "Content-Type must be application/json")
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise ServiceError(411, "length_required", "Content-Length is required")
            try:
                length = int(raw_length)
            except ValueError:
                raise ServiceError(400, "invalid_content_length", "Content-Length must be an integer") from None
            if length < 0 or length > MAX_BODY_BYTES:
                raise ServiceError(413, "payload_too_large", "request body exceeds the local API limit")
            try:
                decoded = self.rfile.read(length).decode("utf-8")
                payload = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ServiceError(400, "invalid_json", "request body must be valid UTF-8 JSON") from None
            if not isinstance(payload, dict):
                raise ServiceError(400, "invalid_body", "request body must be a JSON object")
            unknown = set(payload) - allowed_fields
            if unknown:
                raise ServiceError(400, "invalid_body", "request body contains unsupported fields")
            return payload

        def _method_not_allowed(self) -> None:
            request_id = self._request_id()
            self._error(ServiceError(405, "method_not_allowed", "HTTP method is not allowed"), request_id)

        def _request_id(self) -> str:
            supplied = self.headers.get("X-Request-ID", "")
            return supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid.uuid4().hex

        def _valid_host_header(self) -> bool:
            value = self.headers.get("Host", "")
            host = value.rsplit(":", 1)[0].lower() if ":" in value else value.lower()
            return host in {"127.0.0.1", "localhost"}

        def _error(self, error: ServiceError, request_id: str, origin: str | None = None) -> None:
            self._send(
                error.status,
                {"error": {"code": error.code, "message": error.message, "request_id": request_id}},
                request_id,
                origin,
            )

        def _send(self, status: int, payload: Any, request_id: str, origin: str | None = None) -> None:
            encoded = b"" if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("X-Request-ID", request_id)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            if origin is not None and origin in allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Request-ID")
            if payload is not None:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            if encoded:
                self.wfile.write(encoded)

    return Handler


def _single_query(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if values is None:
        return None
    if len(values) != 1 or not values[0]:
        raise ServiceError(400, "invalid_query", f"{key} must appear exactly once with a value")
    return values[0]
