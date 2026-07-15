from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import threading
from typing import Any

from hermes_integration.loop import (
    SCENARIOS,
    ContinuationError,
    attempt_state_name,
    continue_attempt,
    run_attempt,
    run_scenario,
)
from hermes_runtime.store import EventStore

from .catalog import LessonCatalog, ScenarioCatalog
from .practice_v2 import PracticeServiceError, SmartPracticeCoordinator


SERVICE_VERSION = "0.2.0"


class ServiceError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class SidecarApplication:
    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        self.catalog = ScenarioCatalog()
        self.lesson_catalog = LessonCatalog()
        self.smart_practice = SmartPracticeCoordinator(self.database)
        self._continuation_lock = threading.Lock()
        self._practice_lock = threading.Lock()

    def health(self) -> dict[str, Any]:
        store = EventStore(self.database)
        run_count = len(store.run_ids())
        store.close()
        return {
            "status": "ok",
            "service": "hermes-local-sidecar",
            "version": SERVICE_VERSION,
            "storage": "sqlite-append-only",
            "run_count": run_count,
            "local_only": True,
        }

    def capabilities(self) -> dict[str, Any]:
        scenarios = self.catalog.list()
        lessons = self.lesson_catalog.list()
        payload = {
            "service_version": SERVICE_VERSION,
            "api_version": "v1",
            "local_only": True,
            "domains": sorted({item["domain"] for item in scenarios}),
            "learning_modes": sorted(SCENARIOS),
            "scenario_count": len(scenarios),
            "lesson_count": len(lessons),
            "smart_practice_package": {
                "package_id": self.smart_practice.package_id,
                "version": self.smart_practice.package_version,
                "target_count": 8,
            },
            "features": [
                "representative-scenario-catalog",
                "auditable-lesson-catalog-v1",
                "lesson-practice-via-existing-runtime",
                "answer-only-smart-practice-v2",
                "fixed-eight-session-policy",
                "cross-family-transfer-validation",
                "domain-engine-runtime-loop",
                "real-learner-attempt-v1",
                "optimistic-attempt-continuation-v1",
                "append-only-trace",
                "hash-verified-replay",
                "skill-summary",
                "offline-deterministic-path",
            ],
            "endpoints": {
                "health": "GET /v1/health",
                "capabilities": "GET /v1/capabilities",
                "scenarios": "GET /v1/scenarios",
                "lessons": "GET /v1/lessons",
                "lesson_detail": "GET /v1/lessons/{lesson_id}",
                "practice_session": "POST /v1/practice-sessions",
                "practice_session_detail": "GET /v1/practice-sessions/{session_id}",
                "practice_answer": "POST /v1/practice-sessions/{session_id}/answers",
                "practice_probe": "POST /v1/practice-sessions/{session_id}/probes",
                "practice_end": "POST /v1/practice-sessions/{session_id}/end",
                "practice_session_report": "GET /v1/practice-sessions/{session_id}/report",
                "practice_overview": "GET /v1/practice/overview",
                "practice_history": "GET /v1/practice/history",
                "practice_wrong_questions": "GET /v1/practice/wrong-questions",
                "practice_profile": "GET /v1/practice/profile",
                "run": "POST /v1/runs",
                "attempt": "POST /v1/attempts",
                "attempt_response": "POST /v1/attempts/{run_id}/responses",
                "trace": "GET /v1/runs/{run_id}/trace",
                "replay": "GET /v1/runs/{run_id}/replay",
                "skills": "GET /v1/skills/report",
            },
        }
        bank = self.smart_practice.bank_capability()
        if bank is not None:
            payload["smart_practice_bank"] = bank
            payload["practice_learning_records"] = {
                "read_only": True,
                "authoritative_source": "verified_append_only_practice_trace",
                "schemas": {
                    "session_report": "lumi.practice-session-report.v1",
                    "overview": "lumi.practice-overview.v1",
                    "profile": "lumi.practice-profile.v1",
                    "history": "lumi.practice-history.v1",
                    "wrong_questions": "lumi.wrong-question-book.v1",
                },
                "empty_collection_status": 200,
                "independent_evidence_only_for_profile_status": True,
                "error_causes_are_reversible_hypotheses": True,
            }
            payload["features"].append("scope-bound-core-320-practice-v3")
            payload["features"].extend(
                [
                    "rebuildable-practice-session-report-v1",
                    "rebuildable-practice-history-v1",
                    "evidence-backed-wrong-question-book-v1",
                    "independent-evidence-practice-profile-v1",
                    "deterministic-next-scope-overview-v1",
                ]
            )
        return payload

    def scenarios(self, domain: str | None = None, mode: str | None = None) -> dict[str, Any]:
        if domain is not None and domain not in {"xingce", "shenlun", "interview"}:
            raise ServiceError(400, "invalid_domain", "domain must be xingce, shenlun, or interview")
        if mode is not None and mode not in {"success", "ambiguous", "offline"}:
            raise ServiceError(400, "invalid_mode", "mode must be success, ambiguous, or offline")
        items = self.catalog.list(domain=domain, mode=mode)
        return {
            "policy": "safe-practice-catalog-v1",
            "count": len(items),
            "items": items,
        }

    def lessons(self) -> dict[str, Any]:
        items = [public_safe(item) for item in self.lesson_catalog.list()]
        for item in items:
            item["links"] = {"self": f"/v1/lessons/{item['lesson_id']}"}
        return {
            "schema_version": "hermes.lesson-catalog.v1",
            "policy": "auditable-lesson-catalog-v1",
            "count": len(items),
            "items": items,
        }

    def lesson(self, lesson_id: str) -> dict[str, Any]:
        if len(lesson_id) > 200 or not _safe_identifier(lesson_id):
            raise ServiceError(400, "invalid_lesson_id", "lesson_id contains unsupported characters")
        try:
            lesson = public_safe(self.lesson_catalog.resolve(lesson_id))
        except KeyError:
            raise ServiceError(404, "lesson_not_found", "lesson_id is not in the lesson catalog") from None
        return {
            "schema_version": "hermes.lesson-detail.v1",
            "policy": "auditable-lesson-catalog-v1",
            "lesson": lesson,
            "links": {"catalog": "/v1/lessons"},
        }

    def start_practice_session(
        self,
        unit_id: str | None = None,
        *,
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        with self._practice_lock:
            return self._practice_call(
                self.smart_practice.start,
                unit_id,
                scope_id=scope_id,
            )

    def practice_session(self, session_id: str) -> dict[str, Any]:
        with self._practice_lock:
            return self._practice_call(self.smart_practice.get, session_id)

    def submit_practice_answer(
        self,
        session_id: str,
        question_id: Any,
        question_version_id: Any,
        answer: Any,
        response_time_seconds: Any = None,
    ) -> dict[str, Any]:
        with self._practice_lock:
            return self._practice_call(
                self.smart_practice.submit_answer,
                session_id,
                question_id,
                question_version_id,
                answer,
                response_time_seconds,
            )

    def submit_practice_probe(
        self,
        session_id: str,
        hypothesis_id: Any,
        answer: Any,
    ) -> dict[str, Any]:
        with self._practice_lock:
            return self._practice_call(
                self.smart_practice.submit_probe,
                session_id,
                hypothesis_id,
                answer,
            )

    def end_practice_session(self, session_id: str, reason: str | None = None) -> dict[str, Any]:
        with self._practice_lock:
            return self._practice_call(self.smart_practice.end, session_id, reason)

    def practice_session_report(self, session_id: str) -> dict[str, Any]:
        with self._practice_lock:
            return self._practice_call(
                self.smart_practice.practice_session_report,
                session_id,
            )

    def practice_overview(self) -> dict[str, Any]:
        with self._practice_lock:
            return self._practice_call(self.smart_practice.practice_overview)

    def practice_history(
        self,
        *,
        limit: int,
        offset: int,
        scope_id: str | None,
        status: str | None,
    ) -> dict[str, Any]:
        with self._practice_lock:
            return self._practice_call(
                self.smart_practice.practice_history,
                limit=limit,
                offset=offset,
                scope_id=scope_id,
                status=status,
            )

    def practice_wrong_questions(
        self,
        *,
        limit: int,
        offset: int,
        state: str,
        module_id: str | None,
    ) -> dict[str, Any]:
        with self._practice_lock:
            return self._practice_call(
                self.smart_practice.practice_wrong_questions,
                limit=limit,
                offset=offset,
                state=state,
                module_id=module_id,
            )

    def practice_profile(self) -> dict[str, Any]:
        with self._practice_lock:
            return self._practice_call(self.smart_practice.practice_profile)

    @staticmethod
    def _practice_call(function: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return function(*args, **kwargs)
        except PracticeServiceError as exc:
            raise ServiceError(exc.status, exc.code, exc.message) from None

    def submit_attempt(
        self,
        fixture_id: str,
        response: str,
        confidence: float,
        response_time_seconds: float,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(fixture_id, str) or not fixture_id or len(fixture_id) > 200:
            raise ServiceError(400, "invalid_fixture_id", "fixture_id must be a non-empty catalog identifier")
        try:
            fixture = self._resolve_attempt_fixture(fixture_id)
        except KeyError:
            raise ServiceError(
                404,
                "fixture_not_found",
                "fixture_id is not in the representative or lesson practice catalog",
            ) from None
        if not isinstance(response, str) or not response.strip():
            raise ServiceError(400, "invalid_response", "response must be non-empty text")
        if len(response) > 20_000:
            raise ServiceError(413, "response_too_large", "response exceeds the 20000-character limit")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ServiceError(400, "invalid_confidence", "confidence must be a number in [0, 1]")
        if (
            isinstance(response_time_seconds, bool)
            or not isinstance(response_time_seconds, (int, float))
            or not 0 <= response_time_seconds <= 7200
        ):
            raise ServiceError(
                400,
                "invalid_response_time",
                "response_time_seconds must be a number in [0, 7200]",
            )
        if run_id is not None and (not run_id or len(run_id) > 96 or not _safe_identifier(run_id)):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        try:
            session, result = run_attempt(
                fixture,
                response,
                float(confidence),
                float(response_time_seconds),
                self.database,
                run_id=run_id,
            )
        except ValueError as exc:
            if "already exists" in str(exc):
                raise ServiceError(409, "run_exists", "a run with this identifier already exists") from None
            raise ServiceError(422, "attempt_rejected", "the learner attempt could not be processed") from None
        try:
            artifacts = result.state.artifacts
            score = artifacts["observe"][-1]["score"]
            diagnosis = artifacts["diagnose"][-1]
            version = session.store.events(result.state.run_id)[-1].seq
            return {
                "schema_version": "hermes.attempt-session.v1",
                "run_id": result.state.run_id,
                "fixture_id": fixture_id,
                "domain": fixture["domain"],
                "mode": fixture["mode"],
                "status": result.state.status.value,
                "state": attempt_state_name(result.state),
                "state_version": version,
                "steps": result.state.step_count,
                "score": {
                    "score": score["score"],
                    "max_score": score["max_score"],
                    "passed": score["passed"],
                    "adapter_version": score["adapter_version"],
                },
                "diagnosis": {
                    "decision": diagnosis["decision"],
                    "hypotheses": diagnosis["diagnosis"]["hypotheses"],
                    "uncertainty": diagnosis["diagnosis"]["uncertainty"],
                    "semantics": "ranked_unconfirmed_hypotheses",
                    "model_version": diagnosis["model_version"],
                },
                "response_evidence": artifacts["observe"][-1]["response_evidence"],
                "probe": {
                    "prompt": artifacts["probe"][-1]["prompt"],
                    "targets": artifacts["probe"][-1]["targets"],
                    "selection": artifacts["probe"][-1]["selection"],
                },
                "teaching": None,
                "verification": None,
                "mastery_update": None,
                "execution": {
                    "connectivity": fixture["execution"]["connectivity"],
                    "cloud_calls": 0,
                },
                "trace_verified": session.store.verify(result.state.run_id),
                "links": {
                    "trace": f"/v1/runs/{result.state.run_id}/trace",
                    "replay": f"/v1/runs/{result.state.run_id}/replay",
                    "skill_report": "/v1/skills/report",
                    "respond": f"/v1/attempts/{result.state.run_id}/responses",
                },
            }
        finally:
            session.store.close()

    def continue_attempt_session(
        self,
        run_id: str,
        phase: str,
        expected_version: int,
        expected_state: str,
        response: str,
        confidence: float,
        response_time_seconds: float,
    ) -> dict[str, Any]:
        # One sidecar owns the SQLite writer. Serializing compare-version + append
        # makes optimistic concurrency fail closed even under simultaneous clicks.
        with self._continuation_lock:
            return self._continue_attempt_session_locked(
                run_id,
                phase,
                expected_version,
                expected_state,
                response,
                confidence,
                response_time_seconds,
            )

    def _continue_attempt_session_locked(
        self,
        run_id: str,
        phase: str,
        expected_version: int,
        expected_state: str,
        response: str,
        confidence: float,
        response_time_seconds: float,
    ) -> dict[str, Any]:
        if not _safe_identifier(run_id):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        if phase not in {"probe", "verification"}:
            raise ServiceError(400, "invalid_phase", "phase must be probe or verification")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise ServiceError(400, "invalid_version", "expected_version must be a positive integer")
        if expected_state not in {"awaiting_probe", "awaiting_verification"}:
            raise ServiceError(400, "invalid_state", "expected_state is not a writable attempt state")
        self._validate_attempt_evidence(response, confidence, response_time_seconds)
        store = EventStore(self.database)
        try:
            try:
                state = store.load_state(run_id)
            except KeyError:
                raise ServiceError(404, "run_not_found", "attempt session does not exist") from None
            fixture_id = state.context.get("fixture_id")
        finally:
            store.close()
        try:
            fixture = self._resolve_attempt_fixture(str(fixture_id))
        except KeyError:
            raise ServiceError(409, "fixture_unavailable", "session fixture is no longer in the catalog") from None
        try:
            session, result = continue_attempt(
                fixture,
                self.database,
                run_id,
                phase=phase,
                expected_version=expected_version,
                expected_state=expected_state,
                response=response,
                confidence=float(confidence),
                response_time_seconds=float(response_time_seconds),
            )
        except ContinuationError as exc:
            status = 404 if exc.code == "run_not_found" else 409
            raise ServiceError(status, exc.code, exc.message) from None
        try:
            artifacts = result.state.artifacts
            version = session.store.events(run_id)[-1].seq
            state_name = attempt_state_name(result.state)
            payload: dict[str, Any] = {
                "schema_version": "hermes.attempt-continuation-result.v1",
                "run_id": run_id,
                "accepted_phase": phase,
                "status": result.state.status.value,
                "state": state_name,
                "state_version": version,
                "steps": result.state.step_count,
                "trace_verified": session.store.verify(run_id),
                "links": {
                    "trace": f"/v1/runs/{run_id}/trace",
                    "replay": f"/v1/runs/{run_id}/replay",
                    "skill_report": "/v1/skills/report",
                    "respond": f"/v1/attempts/{run_id}/responses",
                },
            }
            if phase == "probe":
                teaching = artifacts["teach"][-1]
                payload.update(
                    {
                        "teaching": teaching,
                        "verification": {
                            "prompt": teaching["independent_verification_prompt"],
                            "response_mode": teaching["independent_verification_response_mode"],
                            "options": dict(
                                fixture.get("independent_verify", {})
                                .get("pass_condition", {})
                                .get("options", {})
                            ),
                            "status": "awaiting_learner_response",
                        },
                        "mastery_update": None,
                        "reflection": None,
                    }
                )
            else:
                verification = artifacts["verify"][-1]["verification"]
                payload.update(
                    {
                        "teaching": artifacts["teach"][-1],
                        "verification": verification,
                        "mastery_update": artifacts["update"][-1],
                        "reflection": artifacts["reflect"][-1],
                    }
                )
            return payload
        finally:
            session.store.close()

    @staticmethod
    def _validate_attempt_evidence(response: Any, confidence: Any, response_time_seconds: Any) -> None:
        if not isinstance(response, str) or not response.strip():
            raise ServiceError(400, "invalid_response", "response must be non-empty text")
        if len(response) > 20_000:
            raise ServiceError(413, "response_too_large", "response exceeds the 20000-character limit")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ServiceError(400, "invalid_confidence", "confidence must be a number in [0, 1]")
        if (
            isinstance(response_time_seconds, bool)
            or not isinstance(response_time_seconds, (int, float))
            or not 0 <= response_time_seconds <= 7200
        ):
            raise ServiceError(400, "invalid_response_time", "response_time_seconds must be a number in [0, 7200]")

    def _resolve_attempt_fixture(self, fixture_id: str) -> dict[str, Any]:
        try:
            return self.catalog.resolve(fixture_id)
        except KeyError:
            return self.lesson_catalog.resolve_fixture(fixture_id)

    def run_learning_loop(self, mode: str, run_id: str | None = None) -> dict[str, Any]:
        if mode not in SCENARIOS:
            raise ServiceError(400, "invalid_mode", "mode must be success, ambiguous, or offline")
        if run_id is not None and (not run_id or len(run_id) > 96 or not _safe_identifier(run_id)):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        try:
            session, result = run_scenario(mode, self.database, run_id=run_id)
        except ValueError as exc:
            if "already exists" in str(exc):
                raise ServiceError(409, "run_exists", "a run with this identifier already exists") from None
            raise ServiceError(422, "run_rejected", "the learning run could not be started") from None
        try:
            artifacts = result.state.artifacts
            return {
                "run_id": result.state.run_id,
                "mode": mode,
                "status": result.state.status.value,
                "steps": result.state.step_count,
                "summary": {
                    "diagnosis_decision": artifacts["diagnose"][-1]["decision"],
                    "verification_effective": artifacts["verify"][-1]["verification"]["effective"],
                    "mastery_delta": artifacts["update"][-1]["mastery_delta"],
                    "outcome": artifacts["reflect"][-1]["outcome"],
                },
                "trace_verified": session.store.verify(result.state.run_id),
                "links": {
                    "trace": f"/v1/runs/{result.state.run_id}/trace",
                    "replay": f"/v1/runs/{result.state.run_id}/replay",
                },
            }
        finally:
            session.store.close()

    def trace(self, run_id: str) -> dict[str, Any]:
        semantic_replay = self._practice_call(
            self.smart_practice.verify_semantic_replay,
            run_id,
        )
        events, verified = self._events(run_id)
        payload = {
            "run_id": run_id,
            "trace_verified": verified,
            "event_count": len(events),
            "events": [
                {
                    "seq": event.seq,
                    "occurred_at": event.occurred_at,
                    "kind": event.kind,
                    "event_hash": event.event_hash,
                    "previous_hash": event.previous_hash,
                    "payload": public_safe(event.payload),
                }
                for event in events
            ],
        }
        if semantic_replay is not None:
            payload["semantic_replay_verified"] = semantic_replay
        return payload

    def replay(self, run_id: str) -> dict[str, Any]:
        semantic_replay = self._practice_call(
            self.smart_practice.verify_semantic_replay,
            run_id,
        )
        store = EventStore(self.database)
        try:
            if not store.events(run_id):
                raise ServiceError(404, "run_not_found", "the requested run does not exist")
            frames = list(store.replay(run_id))
            payload = {
                "run_id": run_id,
                "trace_verified": True,
                "frame_count": len(frames),
                "frames": public_safe(frames),
            }
            if semantic_replay is not None:
                payload["semantic_replay_verified"] = semantic_replay
            return payload
        finally:
            store.close()

    def skill_report(self) -> dict[str, Any]:
        store = EventStore(self.database)
        try:
            aggregates: dict[str, dict[str, Any]] = defaultdict(
                lambda: {
                    "run_ids": [],
                    "deltas": [],
                    "verified_transfers": 0,
                    "failed_or_inconclusive": 0,
                    "latest_mastery": None,
                    "latest_uncertainty": None,
                    "latest_at": "",
                }
            )
            for run_id in store.run_ids():
                for event in store.events(run_id):
                    if event.kind != "phase_completed" or event.payload.get("phase") != "update":
                        continue
                    update = event.payload.get("output", {})
                    skill_id = update.get("skill_id")
                    if not isinstance(skill_id, str):
                        continue
                    row = aggregates[skill_id]
                    row["run_ids"].append(run_id)
                    row["deltas"].append(float(update["mastery_delta"]))
                    evidence = update.get("evidence", {})
                    effective = evidence.get("verification_effective") if isinstance(evidence, dict) else None
                    if effective is True:
                        row["verified_transfers"] += 1
                    else:
                        row["failed_or_inconclusive"] += 1
                    if event.occurred_at >= row["latest_at"]:
                        row["latest_at"] = event.occurred_at
                        row["latest_mastery"] = update.get("new_mastery")
                        row["latest_uncertainty"] = update.get("uncertainty")
            items = []
            for skill_id, row in sorted(aggregates.items()):
                deltas = row.pop("deltas")
                run_ids = row.pop("run_ids")
                items.append(
                    {
                        "skill_id": skill_id,
                        "run_count": len(set(run_ids)),
                        "average_mastery_delta": round(sum(deltas) / len(deltas), 12),
                        **row,
                    }
                )
            return {
                "policy": "trace-summary-v1",
                "note": "Latest mastery is per-run evidence, not a fabricated longitudinal merge.",
                "skill_count": len(items),
                "items": items,
            }
        finally:
            store.close()

    def _events(self, run_id: str) -> tuple[list[Any], bool]:
        if not _safe_identifier(run_id):
            raise ServiceError(400, "invalid_run_id", "run_id contains unsupported characters")
        store = EventStore(self.database)
        try:
            events = store.events(run_id)
            if not events:
                raise ServiceError(404, "run_not_found", "the requested run does not exist")
            return events, store.verify(run_id)
        finally:
            store.close()


def _safe_identifier(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in "-_.:" for char in value)


def public_safe(value: Any) -> Any:
    """Defense in depth: never serialize protected repository or bulk-data paths."""
    forbidden = ("shenlun-agent-platform", "/users/", "xingcetiku", "155gb")
    if isinstance(value, str):
        lowered = value.lower()
        if any(fragment in lowered for fragment in forbidden):
            return "[REDACTED_LOCAL_PATH]"
        return value
    if isinstance(value, dict):
        return {str(key): public_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_safe(item) for item in value]
    return value
