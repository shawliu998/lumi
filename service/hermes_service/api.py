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
LESSON_ROUTE = re.compile(r"^/v1/lessons/([^/]+)$")
PRACTICE_SESSION_ROUTE = re.compile(r"^/v1/practice-sessions/([^/]+)$")
PRACTICE_SESSION_REPORT_ROUTE = re.compile(
    r"^/v1/practice-sessions/([^/]+)/report$"
)
PRACTICE_ANSWER_ROUTE = re.compile(r"^/v1/practice-sessions/([^/]+)/answers$")
PRACTICE_PROBE_ROUTE = re.compile(r"^/v1/practice-sessions/([^/]+)/probes$")
PRACTICE_END_ROUTE = re.compile(r"^/v1/practice-sessions/([^/]+)/end$")
PRACTICE_SCOPE_IDS = frozenset(
    {
        "xingce.verbal.core",
        "xingce.judgment.core",
        "xingce.quantitative.core",
        "xingce.data-analysis.core",
        "xingce.mixed.core",
    }
)
PRACTICE_MODULE_IDS = PRACTICE_SCOPE_IDS - {"xingce.mixed.core"}


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
                if method == "POST" and parsed.path == "/v1/practice-sessions":
                    body = self._read_json({"unit_id", "scope_id"})
                    if body.get("unit_id") is not None and (
                        not isinstance(body["unit_id"], str)
                        or not body["unit_id"].strip()
                        or len(body["unit_id"]) > 200
                    ):
                        raise ServiceError(400, "invalid_unit_id", "unit_id must be a non-empty string")
                    if body.get("scope_id") is not None and (
                        not isinstance(body["scope_id"], str)
                        or not body["scope_id"].strip()
                        or len(body["scope_id"]) > 200
                    ):
                        raise ServiceError(400, "invalid_scope_id", "scope_id must be a non-empty string")
                    if body.get("unit_id") is not None and body.get("scope_id") is not None:
                        raise ServiceError(
                            400,
                            "ambiguous_practice_scope",
                            "unit_id and scope_id cannot be supplied together",
                        )
                    payload = application.start_practice_session(
                        body.get("unit_id"),
                        scope_id=body.get("scope_id"),
                    )
                    self._send(201, payload, request_id, origin)
                    return
                practice_answer_match = PRACTICE_ANSWER_ROUTE.fullmatch(parsed.path)
                if method == "POST" and practice_answer_match:
                    body = self._read_json(
                        {"question_id", "question_version_id", "answer", "response_time_seconds"}
                    )
                    required = {"question_id", "question_version_id", "answer"}
                    if not required.issubset(body):
                        raise ServiceError(400, "invalid_body", "practice answer is missing a required field")
                    if not isinstance(body["question_id"], str) or not body["question_id"].strip() or len(body["question_id"]) > 200:
                        raise ServiceError(400, "invalid_question_id", "question_id must be non-empty text")
                    if (
                        not isinstance(body["question_version_id"], str)
                        or not body["question_version_id"].strip()
                        or len(body["question_version_id"]) > 100
                    ):
                        raise ServiceError(400, "invalid_question_version", "question_version_id must be non-empty text")
                    if not isinstance(body["answer"], str) or not body["answer"].strip() or len(body["answer"]) > 100:
                        raise ServiceError(400, "invalid_answer", "answer must be non-empty text")
                    payload = application.submit_practice_answer(
                        unquote(practice_answer_match.group(1)),
                        body["question_id"],
                        body["question_version_id"],
                        body["answer"],
                        body.get("response_time_seconds"),
                    )
                    self._send(200, payload, request_id, origin)
                    return
                practice_probe_match = PRACTICE_PROBE_ROUTE.fullmatch(parsed.path)
                if method == "POST" and practice_probe_match:
                    body = self._read_json({"hypothesis_id", "answer"})
                    if set(body) != {"hypothesis_id", "answer"}:
                        raise ServiceError(400, "invalid_body", "probe body must contain hypothesis_id and answer")
                    if (
                        not isinstance(body["hypothesis_id"], str)
                        or not body["hypothesis_id"].strip()
                        or len(body["hypothesis_id"]) > 200
                    ):
                        raise ServiceError(400, "invalid_hypothesis_id", "hypothesis_id must be non-empty text")
                    if not isinstance(body["answer"], str) or len(body["answer"]) > 2000:
                        raise ServiceError(400, "invalid_probe_answer", "probe answer must be text")
                    payload = application.submit_practice_probe(
                        unquote(practice_probe_match.group(1)),
                        body["hypothesis_id"],
                        body["answer"],
                    )
                    self._send(200, payload, request_id, origin)
                    return
                practice_end_match = PRACTICE_END_ROUTE.fullmatch(parsed.path)
                if method == "POST" and practice_end_match:
                    body = self._read_json({"reason"})
                    if body.get("reason") is not None and not isinstance(body["reason"], str):
                        raise ServiceError(400, "invalid_reason", "reason must be a string")
                    payload = application.end_practice_session(
                        unquote(practice_end_match.group(1)),
                        body.get("reason"),
                    )
                    self._send(200, payload, request_id, origin)
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
            if path == "/v1/lessons":
                if query:
                    raise ServiceError(400, "invalid_query", "lesson catalog does not accept query parameters")
                return application.lessons()
            lesson_match = LESSON_ROUTE.fullmatch(path)
            if lesson_match:
                if query:
                    raise ServiceError(400, "invalid_query", "lesson detail does not accept query parameters")
                return application.lesson(unquote(lesson_match.group(1)))
            if path == "/v1/skills/report":
                if query:
                    raise ServiceError(400, "invalid_query", "skill report does not accept query parameters")
                return application.skill_report()
            if path == "/v1/practice/overview":
                if query:
                    raise ServiceError(400, "invalid_query", "practice overview does not accept query parameters")
                return application.practice_overview()
            if path == "/v1/practice/profile":
                if query:
                    raise ServiceError(400, "invalid_query", "practice profile does not accept query parameters")
                return application.practice_profile()
            if path == "/v1/practice/history":
                unknown = set(query) - {"limit", "offset", "scope_id", "status"}
                if unknown:
                    raise ServiceError(400, "invalid_query", "unsupported practice history query parameter")
                limit, offset = _pagination(query)
                scope_id = _single_query(query, "scope_id")
                status = _single_query(query, "status")
                if scope_id is not None and scope_id not in PRACTICE_SCOPE_IDS:
                    raise ServiceError(400, "invalid_query", "scope_id is not a Core-320 practice scope")
                if status is not None and status not in {"active", "completed", "ended_early"}:
                    raise ServiceError(400, "invalid_query", "status is not a public practice session status")
                return application.practice_history(
                    limit=limit,
                    offset=offset,
                    scope_id=scope_id,
                    status=status,
                )
            if path == "/v1/practice/wrong-questions":
                unknown = set(query) - {"limit", "offset", "state", "module_id"}
                if unknown:
                    raise ServiceError(400, "invalid_query", "unsupported wrong-question query parameter")
                limit, offset = _pagination(query)
                state = _single_query(query, "state") or "needs_review"
                module_id = _single_query(query, "module_id")
                if state not in {"needs_review", "resolved", "all"}:
                    raise ServiceError(400, "invalid_query", "state must be needs_review, resolved, or all")
                if module_id is not None and module_id not in PRACTICE_MODULE_IDS:
                    raise ServiceError(400, "invalid_query", "module_id is not a Core-320 module")
                return application.practice_wrong_questions(
                    limit=limit,
                    offset=offset,
                    state=state,
                    module_id=module_id,
                )
            practice_report_match = PRACTICE_SESSION_REPORT_ROUTE.fullmatch(path)
            if practice_report_match:
                if query:
                    raise ServiceError(400, "invalid_query", "practice report does not accept query parameters")
                return application.practice_session_report(
                    unquote(practice_report_match.group(1))
                )
            practice_session_match = PRACTICE_SESSION_ROUTE.fullmatch(path)
            if practice_session_match:
                if query:
                    raise ServiceError(400, "invalid_query", "practice session does not accept query parameters")
                return application.practice_session(unquote(practice_session_match.group(1)))
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


def _pagination(query: dict[str, list[str]]) -> tuple[int, int]:
    raw_limit = _single_query(query, "limit")
    raw_offset = _single_query(query, "offset")
    try:
        limit = 50 if raw_limit is None else int(raw_limit)
        offset = 0 if raw_offset is None else int(raw_offset)
    except ValueError:
        raise ServiceError(400, "invalid_query", "limit and offset must be decimal integers") from None
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ServiceError(400, "invalid_query", "limit must be in [1, 100]")
    if isinstance(offset, bool) or not 0 <= offset <= 1_000_000:
        raise ServiceError(400, "invalid_query", "offset must be in [0, 1000000]")
    return limit, offset
