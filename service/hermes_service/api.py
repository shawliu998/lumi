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
STUDY_PACK_MAX_BODY_BYTES = 12 * 1024 * 1024
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
RUN_ROUTE = re.compile(r"^/v1/runs/([^/]+)/(trace|replay)$")
ATTEMPT_RESPONSE_ROUTE = re.compile(r"^/v1/attempts/([^/]+)/responses$")
ATTEMPT_ASSISTANCE_ROUTE = re.compile(r"^/v1/attempts/([^/]+)/assistance$")
MISCONCEPTION_ROUTE = re.compile(r"^/v1/misconceptions/([^/]+)$")
TODAY_PLAN_ROUTE = re.compile(r"^/v1/today-plans/([^/]+)$")
TODAY_PLAN_REPLAY_ROUTE = re.compile(r"^/v1/today-plans/([^/]+)/replay$")
TODAY_PLAN_TASK_COMMAND_ROUTE = re.compile(
    r"^/v1/today-plans/([^/]+)/tasks/([^/]+)/commands$"
)
REVIEW_TASK_REPLAY_ROUTE = re.compile(r"^/v1/review-schedule/([^/]+)/replay$")
STUDY_PACK_ROUTE = re.compile(r"^/v1/study-packs/([^/]+)$")
STUDY_PACK_COMMAND_ROUTE = re.compile(r"^/v1/study-packs/([^/]+)/commands$")
STUDY_PACK_CITATION_ROUTE = re.compile(
    r"^/v1/study-packs/([^/]+)/citations/([^/]+)$"
)
STUDY_PACK_REPLAY_ROUTE = re.compile(r"^/v1/study-packs/([^/]+)/replay$")
STUDY_PACK_ITEM_LAUNCH_ROUTE = re.compile(
    r"^/v1/study-pack-items/([^/]+)/launch$"
)
STUDY_PACK_ITEM_ATTEMPT_ROUTE = re.compile(
    r"^/v1/study-pack-items/([^/]+)/attempts$"
)


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
        server_version = "HermesSidecar/0.3"
        sys_version = ""

        def version_string(self) -> str:
            return self.server_version

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
                if method == "POST" and parsed.path == "/v1/study-packs":
                    body = self._read_json(
                        {"title", "source", "command_id"},
                        max_body_bytes=STUDY_PACK_MAX_BODY_BYTES,
                    )
                    if set(body) != {"title", "source", "command_id"}:
                        raise ServiceError(
                            400,
                            "invalid_body",
                            "Study Pack creation requires title, source, and command_id",
                        )
                    payload = application.create_study_pack(
                        body["title"],
                        body["source"],
                        body["command_id"],
                    )
                    self._send(201, payload, request_id, origin)
                    return
                if method == "POST" and parsed.path == "/v1/today-plans":
                    body = self._read_json(
                        {
                            "plan_date",
                            "exam_date",
                            "daily_budget_minutes",
                            "expected_version",
                            "command_id",
                        }
                    )
                    required = {
                        "plan_date",
                        "daily_budget_minutes",
                        "expected_version",
                        "command_id",
                    }
                    if not required.issubset(body):
                        raise ServiceError(
                            400,
                            "invalid_body",
                            "TodayPlan body is missing a required field",
                        )
                    payload = application.create_today_plan(
                        body["plan_date"],
                        body.get("exam_date"),
                        body["daily_budget_minutes"],
                        body["expected_version"],
                        body["command_id"],
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
                            "prompt_instance_id",
                            "response",
                            "confidence",
                            "response_time_seconds",
                        }
                    )
                    required = {
                        "phase",
                        "expected_version",
                        "expected_state",
                        "prompt_instance_id",
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
                        body["prompt_instance_id"],
                        body["response"],
                        body["confidence"],
                        body["response_time_seconds"],
                    )
                    self._send(200, payload, request_id, origin)
                    return
                assistance_match = ATTEMPT_ASSISTANCE_ROUTE.fullmatch(parsed.path)
                if method == "POST" and assistance_match:
                    body = self._read_json(
                        {
                            "phase",
                            "expected_version",
                            "expected_state",
                            "prompt_instance_id",
                            "action",
                            "elapsed_time_seconds",
                            "command_id",
                        }
                    )
                    required = {
                        "phase",
                        "expected_version",
                        "expected_state",
                        "prompt_instance_id",
                        "action",
                        "elapsed_time_seconds",
                        "command_id",
                    }
                    if set(body) != required:
                        raise ServiceError(400, "invalid_body", "assistance body must contain every required field")
                    payload = application.deliver_assistance(
                        unquote(assistance_match.group(1)),
                        body["phase"],
                        body["expected_version"],
                        body["expected_state"],
                        body["prompt_instance_id"],
                        body["action"],
                        body["elapsed_time_seconds"],
                        body["command_id"],
                    )
                    self._send(200, payload, request_id, origin)
                    return
                study_pack_command_match = STUDY_PACK_COMMAND_ROUTE.fullmatch(
                    parsed.path
                )
                if method == "POST" and study_pack_command_match:
                    body = self._read_json(
                        {"action", "expected_version", "command_id"}
                    )
                    required = {"action", "expected_version", "command_id"}
                    if set(body) != required:
                        raise ServiceError(
                            400,
                            "invalid_body",
                            "Study Pack command requires every declared field",
                        )
                    payload = application.command_study_pack(
                        unquote(study_pack_command_match.group(1)),
                        body["action"],
                        body["expected_version"],
                        body["command_id"],
                    )
                    self._send(200, payload, request_id, origin)
                    return
                study_pack_attempt_match = STUDY_PACK_ITEM_ATTEMPT_ROUTE.fullmatch(
                    parsed.path
                )
                if method == "POST" and study_pack_attempt_match:
                    body = self._read_json(
                        {
                            "learner_answer",
                            "expected_pack_version",
                            "expected_artifact_version",
                            "command_id",
                        }
                    )
                    required = {
                        "learner_answer",
                        "expected_pack_version",
                        "expected_artifact_version",
                        "command_id",
                    }
                    if set(body) != required:
                        raise ServiceError(
                            400,
                            "invalid_body",
                            "Study Pack attempt requires every declared field",
                        )
                    payload = application.attempt_study_pack_item(
                        unquote(study_pack_attempt_match.group(1)),
                        body["learner_answer"],
                        body["expected_pack_version"],
                        body["expected_artifact_version"],
                        body["command_id"],
                    )
                    self._send(201, payload, request_id, origin)
                    return
                schedule_command_match = TODAY_PLAN_TASK_COMMAND_ROUTE.fullmatch(
                    parsed.path
                )
                if method == "POST" and schedule_command_match:
                    body = self._read_json(
                        {
                            "action",
                            "expected_version",
                            "expected_task_version",
                            "command_id",
                            "postpone_until",
                        }
                    )
                    required = {
                        "action",
                        "expected_version",
                        "expected_task_version",
                        "command_id",
                    }
                    if not required.issubset(body):
                        raise ServiceError(
                            400,
                            "invalid_body",
                            "schedule command body is missing a required field",
                        )
                    payload = application.transition_today_plan_task(
                        unquote(schedule_command_match.group(1)),
                        unquote(schedule_command_match.group(2)),
                        body["action"],
                        body["expected_version"],
                        body["expected_task_version"],
                        body["command_id"],
                        body.get("postpone_until"),
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
            if path == "/v1/misconceptions":
                if query:
                    raise ServiceError(400, "invalid_query", "misconception report does not accept query parameters")
                return application.misconception_report()
            if path == "/v1/review-schedule":
                if query:
                    raise ServiceError(
                        400,
                        "invalid_query",
                        "review schedule does not accept query parameters",
                    )
                return application.review_schedule()
            if path == "/v1/study-packs":
                if query:
                    raise ServiceError(
                        400,
                        "invalid_query",
                        "Study Pack list does not accept query parameters",
                    )
                return application.study_packs()
            study_pack_citation_match = STUDY_PACK_CITATION_ROUTE.fullmatch(path)
            if study_pack_citation_match:
                if query:
                    raise ServiceError(
                        400,
                        "invalid_query",
                        "Study Pack citation does not accept query parameters",
                    )
                return application.study_pack_citation(
                    unquote(study_pack_citation_match.group(1)),
                    unquote(study_pack_citation_match.group(2)),
                )
            study_pack_replay_match = STUDY_PACK_REPLAY_ROUTE.fullmatch(path)
            if study_pack_replay_match:
                if query:
                    raise ServiceError(
                        400,
                        "invalid_query",
                        "Study Pack replay does not accept query parameters",
                    )
                return application.study_pack_replay(
                    unquote(study_pack_replay_match.group(1))
                )
            study_pack_item_launch_match = STUDY_PACK_ITEM_LAUNCH_ROUTE.fullmatch(
                path
            )
            if study_pack_item_launch_match:
                if query:
                    raise ServiceError(
                        400,
                        "invalid_query",
                        "Study Pack launch does not accept query parameters",
                    )
                return application.launch_study_pack_item(
                    unquote(study_pack_item_launch_match.group(1))
                )
            study_pack_match = STUDY_PACK_ROUTE.fullmatch(path)
            if study_pack_match:
                if query:
                    raise ServiceError(
                        400,
                        "invalid_query",
                        "Study Pack does not accept query parameters",
                    )
                return application.study_pack(unquote(study_pack_match.group(1)))
            plan_replay_match = TODAY_PLAN_REPLAY_ROUTE.fullmatch(path)
            if plan_replay_match:
                if query:
                    raise ServiceError(400, "invalid_query", "plan replay does not accept query parameters")
                return application.schedule_replay(
                    "today_plan", unquote(plan_replay_match.group(1))
                )
            review_replay_match = REVIEW_TASK_REPLAY_ROUTE.fullmatch(path)
            if review_replay_match:
                if query:
                    raise ServiceError(400, "invalid_query", "task replay does not accept query parameters")
                return application.schedule_replay(
                    "review_task", unquote(review_replay_match.group(1))
                )
            plan_match = TODAY_PLAN_ROUTE.fullmatch(path)
            if plan_match:
                if query:
                    raise ServiceError(400, "invalid_query", "TodayPlan does not accept query parameters")
                return application.today_plan(unquote(plan_match.group(1)))
            misconception_match = MISCONCEPTION_ROUTE.fullmatch(path)
            if misconception_match:
                if query:
                    raise ServiceError(400, "invalid_query", "misconception dossier does not accept query parameters")
                return application.misconception_dossier(unquote(misconception_match.group(1)))
            match = RUN_ROUTE.fullmatch(path)
            if match:
                run_id = unquote(match.group(1))
                return application.trace(run_id) if match.group(2) == "trace" else application.replay(run_id)
            raise ServiceError(404, "route_not_found", "the requested API route does not exist")

        def _read_json(
            self,
            allowed_fields: set[str],
            *,
            max_body_bytes: int = MAX_BODY_BYTES,
        ) -> dict[str, Any]:
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
            if length < 0 or length > max_body_bytes:
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
