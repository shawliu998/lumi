from __future__ import annotations

from dataclasses import asdict, is_dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
import fcntl
import json
import threading
import uuid

from hermes_domains.practice_v2 import (
    TARGET_DIAGNOSTIC_UNIT_ID,
    load_practice_catalog,
    load_practice_package,
    safe_question_view,
    score_question_version,
)
from hermes_domains.practice_v3_common import (
    safe_question_view as safe_v3_question_view,
    score_question as score_v3_question,
)
from hermes_practice import (
    InvalidSubmission,
    InvalidTransition,
    PracticePolicyEngine,
    QuestionCandidate,
    QuestionRole,
    RecommendationAction,
    RecommendationDecision,
    SessionStatus,
)
from hermes_runtime.store import EventStore


PRACTICE_SCHEMA_VERSION = "lumi.practice-session.v2"
PRACTICE_POLICY_VERSION = "lumi.smart-practice-policy.v2.1.0"
SUPPORTED_PRACTICE_POLICY_VERSIONS = frozenset(
    {
        "lumi.smart-practice-policy.v2.0.0",
        PRACTICE_POLICY_VERSION,
    }
)
PRACTICE_TRACE_RUN_ID = "smart-practice-v2-local-learner"
PRACTICE_SNAPSHOT_FORMAT = "lumi.practice-state.canonical.v1"
V3_SCOPE_IDS = frozenset(
    {
        "xingce.verbal.core",
        "xingce.judgment.core",
        "xingce.quantitative.core",
        "xingce.data-analysis.core",
        "xingce.mixed.core",
    }
)

_PRACTICE_LOCKS_GUARD = threading.Lock()
_PRACTICE_LOCKS: dict[str, threading.RLock] = {}


class PracticeServiceError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class _ScopePracticeCoordinator:
    """Content-bound adapter around the deterministic practice policy.

    The policy engine intentionally has no persistence dependency. This adapter
    records every mutating command in the existing append-only trace and rebuilds
    the engine by replaying those commands on every request. The package version
    is checked during replay so a mutable working file can never silently change
    an accepted decision.
    """

    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        bank: Mapping[str, Any] | None = None,
        scopes: Iterable[Mapping[str, Any]] | None = None,
    ) -> None:
        self.database = str(database)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.is_v3 = False
        self.scope_records: tuple[dict[str, Any], ...] = ()
        self.scopes: dict[str, dict[str, Any]] = {}
        if bank is None and scopes is None:
            catalog = load_practice_catalog()
            matches = [
                item
                for item in catalog
                if item.get("diagnostic_unit_id") == TARGET_DIAGNOSTIC_UNIT_ID
            ]
            if len(matches) != 1:
                raise RuntimeError("exactly one growth-rate practice package is required")
            self.package = load_practice_package(matches[0]["package_id"])
            self.package_id = str(self.package["package_id"])
            self.package_version = str(self.package["version"])
            self.content_descriptor = {
                "package_id": self.package_id,
                "version": self.package_version,
            }
            self.trace_run_id = PRACTICE_TRACE_RUN_ID
            self.title = "增长率 · 直接刷题"
            self.module_label = "资料分析"
            all_questions = tuple(self.package["questions"])
            # The v2 package carries spacing fillers, but the legacy entry is
            # explicitly the original growth-rate regression slice.
            questions = tuple(
                question
                for question in all_questions
                if question["diagnostic_unit_id"] == TARGET_DIAGNOSTIC_UNIT_ID
            )
            self._safe_question = safe_question_view
            self._score_question = score_question_version
            signature_registry = self.package.get("error_signatures", [])
            intervention_registry = self.package.get("interventions", {})
        elif bank is not None and scopes is not None:
            self.is_v3 = True
            self.package = bank
            self.package_id = str(bank["bank_id"])
            self.package_version = str(bank["version"])
            digest = bank.get("generated_sha256")
            if not isinstance(digest, str) or not digest:
                raise RuntimeError("practice bank must expose its manifest-pinned digest")
            self.content_descriptor = {
                "bank_id": self.package_id,
                "version": self.package_version,
                "generated_sha256": digest,
            }
            self.trace_run_id = "smart-practice-v3-core-320-local-learner"
            self.title = "行测核心题池 · 直接刷题"
            self.module_label = "行测"
            self.scope_records = tuple(dict(item) for item in scopes)
            self.scopes = {str(item["scope_id"]): item for item in self.scope_records}
            all_questions = tuple(_records(bank.get("questions", ())))
            questions = all_questions
            if not questions:
                raise RuntimeError("practice bank has no questions")
            self._safe_question = safe_v3_question_view
            self._score_question = score_v3_question
            signature_registry = bank.get("error_signatures", ())
            intervention_registry = bank.get("interventions", ())
        else:
            raise RuntimeError("bank and scopes must be supplied together")

        self.questions = {
            str(question["question_id"]): question
            for question in questions
        }
        self.candidates = tuple(self._candidate(question) for question in self.questions.values())
        self.error_signatures = {
            str(item["signature_id"]): item
            for item in _records(signature_registry)
        }
        self.cause_registry = {
            str(item["cause_id"]): item
            for item in _records(self.package.get("cause_candidates", ()))
            if isinstance(item.get("cause_id"), str)
        }
        self.interventions = tuple(_intervention_records(intervention_registry))

    def start(
        self,
        unit_id: str | None = None,
        *,
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        if unit_id is not None and (
            not isinstance(unit_id, str) or not unit_id.strip() or len(unit_id) > 200
        ):
            raise PracticeServiceError(400, "invalid_unit_id", "unit_id must be non-empty text")
        if scope_id is not None and (
            not isinstance(scope_id, str) or not scope_id.strip() or len(scope_id) > 200
        ):
            raise PracticeServiceError(400, "invalid_scope_id", "scope_id must be non-empty text")
        if self.is_v3:
            if unit_id is not None:
                raise PracticeServiceError(400, "invalid_unit_id", "unit_id cannot select a v3 scope")
            selected_scope = self.scopes.get(str(scope_id)) if scope_id is not None else None
            if selected_scope is None:
                raise PracticeServiceError(404, "scope_not_found", "scope_id is not in the versioned practice bank")
            allowed_unit_ids = tuple(str(item) for item in selected_scope["diagnostic_unit_ids"])
        else:
            if scope_id is not None:
                raise PracticeServiceError(400, "invalid_scope_id", "scope_id requires the v3 practice bank")
            selected_scope = None
            allowed_unit_ids = ()
        if not self.is_v3 and unit_id is not None and unit_id != TARGET_DIAGNOSTIC_UNIT_ID:
            raise PracticeServiceError(404, "unit_not_found", "unit_id is not available in the internal MVP")
        engine = self._rehydrate()
        active = engine.current_session
        if active is not None and active.status is SessionStatus.ACTIVE:
            if active.allowed_unit_ids != frozenset(allowed_unit_ids):
                raise PracticeServiceError(
                    409,
                    "active_practice_scope_conflict",
                    "end the active practice session before starting a different scope",
                )
            decision = self._pending_question(engine)
            if decision is None and not self._open_probe_ids(engine):
                decision = self._recommend_and_record(engine, self._now())
            return self._session_response(
                engine,
                active.session_id,
                decision=decision,
                resumed=True,
            )

        now = self._now()
        session_id = f"practice-{uuid.uuid4().hex}"
        engine.start_session(
            session_id,
            started_at=now,
            allowed_unit_ids=allowed_unit_ids,
        )
        self._append(
            engine,
            "practice_session_started",
            {
                "operation": "session_started",
                "session_id": session_id,
                "started_at": now.isoformat(),
                "allowed_unit_ids": list(allowed_unit_ids),
                "scope_id": selected_scope["scope_id"] if selected_scope is not None else None,
            },
        )
        decision = self._recommend_and_record(engine, now)
        return self._session_response(engine, session_id, decision=decision, resumed=False)

    def get(self, session_id: str) -> dict[str, Any]:
        engine = self._rehydrate()
        session = self._session(engine, session_id)
        decision = self._pending_question(engine)
        if (
            session.status is SessionStatus.ACTIVE
            and decision is None
            and not self._open_probe_ids(engine)
        ):
            decision = self._recommend_and_record(engine, self._now())
        return self._session_response(
            engine,
            session_id,
            decision=decision,
            resumed=True,
        )

    def submit_answer(
        self,
        session_id: str,
        question_id: Any,
        question_version_id: Any,
        answer: Any,
        response_time_seconds: Any = None,
    ) -> dict[str, Any]:
        engine = self._rehydrate()
        session = self._active_session(engine, session_id)
        decision = self._pending_question(engine)
        if decision is None or decision.session_id != session_id:
            raise PracticeServiceError(409, "no_pending_question", "the session has no answerable question")
        if not isinstance(question_id, str) or question_id != decision.question_id:
            raise PracticeServiceError(409, "question_mismatch", "question_id is not the presented question")
        question = self.questions.get(question_id)
        if question is None:
            raise PracticeServiceError(409, "question_unavailable", "the presented question version is unavailable")
        if not isinstance(question_version_id, str) or question_version_id != question["version"]:
            raise PracticeServiceError(409, "question_version_mismatch", "question_version_id is not current")
        if not isinstance(answer, str) or not answer.strip():
            raise PracticeServiceError(400, "invalid_answer", "answer is the only required learner input")
        response_time = self._response_time(response_time_seconds)
        try:
            scored = self._score_question(question, answer)
        except ValueError as exc:
            raise PracticeServiceError(400, "invalid_answer", str(exc)) from None

        cause_candidates = self._cause_candidates(scored)
        now = self._now()
        try:
            result = engine.submit_answer(
                decision.decision_id,
                answer=scored["selected_option"],
                is_correct=bool(scored["correct"]),
                error_signature_id=scored["observed_error_signature_id"],
                cause_candidates=cause_candidates,
                hints_used=0,
                at=now,
            )
        except (InvalidSubmission, InvalidTransition) as exc:
            raise PracticeServiceError(409, "answer_rejected", str(exc)) from None
        accepted_commands: list[dict[str, Any]] = [
            {
                "operation": "answer_submitted",
                "session_id": session_id,
                "decision_id": decision.decision_id,
                "question_id": question_id,
                "question_version": question["version"],
                "answer": scored["selected_option"],
                "is_correct": bool(scored["correct"]),
                "error_signature_id": scored["observed_error_signature_id"],
                "cause_candidates": list(cause_candidates),
                "hints_used": 0,
                "response_time_seconds": response_time,
                "at": now.isoformat(),
                "feedback_decision_id": result.feedback_decision.decision_id,
            }
        ]

        tutorial: Mapping[str, Any] | None = None
        probe: Mapping[str, Any] | None = None
        action = result.feedback_decision.action
        if action is RecommendationAction.SHOW_MICRO_TUTORIAL:
            tutorial = self._microtutorial(
                target_cause_id=result.feedback_decision.target_cause_id,
                signature_id=scored["observed_error_signature_id"],
            )
            if tutorial is None or result.hypothesis_id is None:
                raise PracticeServiceError(500, "missing_reviewed_intervention", "reviewed tutorial is unavailable")
            event = engine.record_tutorial_shown(
                result.hypothesis_id,
                asset_id=str(tutorial["asset_id"]),
                at=now,
            )
            accepted_commands.append(
                {
                    "operation": "tutorial_shown",
                    "session_id": session_id,
                    "hypothesis_id": result.hypothesis_id,
                    "asset_id": tutorial["asset_id"],
                    "validation_event_id": event.validation_event_id,
                    "at": now.isoformat(),
                }
            )
        elif action is RecommendationAction.SHOW_PROBE:
            if result.hypothesis_id is None:
                raise PracticeServiceError(500, "invalid_probe_state", "probe has no hypothesis reference")
            reviewed_probe = self._probe(result.hypothesis_id, engine)
            if reviewed_probe is None:
                raise PracticeServiceError(500, "missing_reviewed_probe", "reviewed optional probe is unavailable")
            # An error on slot eight may open an optional probe, but the probe
            # must consume a slot of a later fixed-eight session. Do not return
            # an unusable probe link against the just-completed session.
            if session.status is SessionStatus.ACTIVE:
                probe = reviewed_probe

        # Persist the accepted answer and any immediately scheduled tutorial as
        # one trace event. A crash can no longer leave an accepted answer whose
        # required intervention vanished between two SQLite appends.
        self._append_commands(
            engine,
            "practice_answer_processed",
            accepted_commands,
        )

        next_decision: RecommendationDecision | None = None
        if session.status is SessionStatus.ACTIVE and probe is None:
            next_decision = self._recommend_and_record(engine, now)
        feedback = self._feedback(
            question,
            scored,
            result.feedback_decision,
            tutorial=tutorial,
            probe=probe,
            hypothesis_id=result.hypothesis_id,
        )
        payload = {
            "schema_version": PRACTICE_SCHEMA_VERSION,
            "session": self._session_view(session),
            "result": {
                "correct": bool(scored["correct"]),
                "selected_option": scored["selected_option"],
                "correct_option": question["scoring"]["correct_option"],
                "feedback": feedback,
                "performance": {
                    "status": result.performance.status.value,
                    "reason_codes": list(result.performance.reason_codes),
                },
            },
            "audit": self._audit(result.feedback_decision),
            "links": self._links(session_id),
        }
        if next_decision is not None and next_decision.question_id is not None:
            payload["question"] = self._question_view(next_decision)
        if session.status is not SessionStatus.ACTIVE:
            payload["summary"] = self._summary(engine, session_id)
        return payload

    def submit_probe(self, session_id: str, hypothesis_id: Any, answer: Any) -> dict[str, Any]:
        engine = self._rehydrate()
        session = self._active_session(engine, session_id)
        open_ids = set(self._open_probe_ids(engine))
        if not isinstance(hypothesis_id, str) or hypothesis_id not in open_ids:
            raise PracticeServiceError(409, "probe_not_pending", "the optional probe is no longer pending")
        now = self._now()
        tutorial: Mapping[str, Any] | None = None
        if not isinstance(answer, str):
            raise PracticeServiceError(400, "invalid_probe_answer", "probe answer must be text")
        if not answer.strip() or answer == "__skip__":
            result = engine.skip_probe(hypothesis_id, at=now)
            accepted_commands: list[dict[str, Any]] = [
                {
                    "operation": "probe_skipped",
                    "session_id": session_id,
                    "hypothesis_id": hypothesis_id,
                    "at": now.isoformat(),
                }
            ]
        else:
            probe = self._probe(hypothesis_id, engine)
            if probe is None:
                raise PracticeServiceError(500, "missing_reviewed_probe", "reviewed optional probe is unavailable")
            outcomes = probe.get(
                "option_results",
                probe.get("outcomes", probe.get("option_outcomes", {})),
            )
            if answer not in probe.get("options", {}) or not isinstance(outcomes, Mapping):
                raise PracticeServiceError(400, "invalid_probe_answer", "probe answer is not an available option")
            supported = outcomes.get(answer)
            if isinstance(supported, Mapping):
                supported = supported.get("supported_cause_id")
            supported_cause_id = supported if isinstance(supported, str) and supported else None
            result = engine.submit_probe_answer(
                hypothesis_id,
                answer=answer,
                supported_cause_id=supported_cause_id,
                at=now,
            )
            accepted_commands = [
                {
                    "operation": "probe_submitted",
                    "session_id": session_id,
                    "hypothesis_id": hypothesis_id,
                    "answer": answer,
                    "supported_cause_id": supported_cause_id,
                    "at": now.isoformat(),
                }
            ]
            if result.decision.action is RecommendationAction.SHOW_MICRO_TUTORIAL:
                hypothesis = engine.hypotheses[hypothesis_id]
                target = result.decision.target_cause_id or supported_cause_id
                tutorial = self._microtutorial(
                    target_cause_id=target,
                    signature_id=hypothesis.error_signature_id,
                )
                if tutorial is None:
                    raise PracticeServiceError(500, "missing_reviewed_intervention", "reviewed tutorial is unavailable")
                event = engine.record_tutorial_shown(
                    hypothesis_id,
                    asset_id=str(tutorial["asset_id"]),
                    at=now,
                )
                accepted_commands.append(
                    {
                        "operation": "tutorial_shown",
                        "session_id": session_id,
                        "hypothesis_id": hypothesis_id,
                        "asset_id": tutorial["asset_id"],
                        "validation_event_id": event.validation_event_id,
                        "at": now.isoformat(),
                    }
                )

        self._append_commands(
            engine,
            "practice_probe_processed",
            accepted_commands,
        )

        next_decision: RecommendationDecision | None = None
        if session.status is SessionStatus.ACTIVE:
            next_decision = self._recommend_and_record(engine, now)
        payload: dict[str, Any] = {
            "schema_version": PRACTICE_SCHEMA_VERSION,
            "session": self._session_view(session),
            "probe_result": {
                "skipped": bool(result.skipped),
                "saved": not result.skipped,
                "microtutorial": self._safe_tutorial(tutorial) if tutorial else None,
            },
            "audit": self._audit(result.decision),
            "links": self._links(session_id),
        }
        if next_decision is not None and next_decision.question_id is not None:
            payload["question"] = self._question_view(next_decision)
        if session.status is not SessionStatus.ACTIVE:
            payload["summary"] = self._summary(engine, session_id)
        return payload

    def end(self, session_id: str, reason: str | None = None) -> dict[str, Any]:
        engine = self._rehydrate()
        session = self._active_session(engine, session_id)
        if reason is not None and (
            not isinstance(reason, str) or not reason.strip() or len(reason) > 120
        ):
            raise PracticeServiceError(400, "invalid_reason", "reason must contain 1 to 120 characters")
        now = self._now()
        end_reason = reason or "learner_ended_early"
        engine.end_session_early(at=now, reason=end_reason)
        self._append(
            engine,
            "practice_session_ended",
            {
                "operation": "session_ended",
                "session_id": session_id,
                "reason": end_reason,
                "at": now.isoformat(),
            },
        )
        return {
            "schema_version": PRACTICE_SCHEMA_VERSION,
            "session": self._session_view(session),
            "summary": self._summary(engine, session_id),
            "links": self._links(session_id),
        }

    def _rehydrate(self) -> PracticePolicyEngine:
        engine = PracticePolicyEngine()
        store = EventStore(self.database)
        try:
            events = store.events(self.trace_run_id)
            if events and not store.verify(self.trace_run_id):
                raise PracticeServiceError(500, "practice_trace_invalid", "practice trace verification failed")
        finally:
            store.close()
        for event in events:
            payload = event.payload
            expected_schema = "lumi.practice-command.v3" if self.is_v3 else "lumi.practice-command.v2"
            if payload.get("schema_version") != expected_schema:
                raise PracticeServiceError(409, "practice_schema_unavailable", "recorded practice schema is unavailable")
            if payload.get("policy_version") not in SUPPORTED_PRACTICE_POLICY_VERSIONS:
                raise PracticeServiceError(409, "policy_version_unavailable", "recorded practice policy is unavailable")
            content = payload.get("content", {})
            if content != self.content_descriptor:
                raise PracticeServiceError(409, "content_version_unavailable", "recorded practice content is unavailable")
            command = payload.get("command")
            if not isinstance(command, Mapping):
                raise PracticeServiceError(500, "invalid_practice_trace", "practice command is malformed")
            try:
                self._replay(engine, command)
            except PracticeServiceError:
                raise
            except (InvalidSubmission, InvalidTransition, KeyError, TypeError, ValueError):
                raise PracticeServiceError(
                    500,
                    "invalid_practice_trace",
                    "practice command cannot be replayed safely",
                ) from None
            if payload.get("snapshot_format") == PRACTICE_SNAPSHOT_FORMAT:
                recorded_snapshot = payload.get("state_after")
                if not isinstance(recorded_snapshot, Mapping):
                    raise PracticeServiceError(
                        500,
                        "invalid_practice_trace",
                        "canonical practice state snapshot is missing",
                    )
                self._same(
                    dict(recorded_snapshot),
                    self._snapshot(engine),
                    f"state_after_seq_{event.seq}",
                )
        return engine

    def _replay(self, engine: PracticePolicyEngine, command: Mapping[str, Any]) -> None:
        operation = command.get("operation")
        if operation == "batch":
            commands = command.get("commands")
            if not isinstance(commands, list) or not commands:
                raise PracticeServiceError(500, "invalid_practice_trace", "practice command batch is malformed")
            for item in commands:
                if not isinstance(item, Mapping) or item.get("operation") == "batch":
                    raise PracticeServiceError(500, "invalid_practice_trace", "nested practice command is malformed")
                self._replay(engine, item)
            return
        at = _parse_time(command.get("at") or command.get("started_at"))
        if operation == "session_started":
            recorded_scope_id = command.get("scope_id")
            raw_allowed = command.get("allowed_unit_ids", [])
            if not isinstance(raw_allowed, list) or any(
                not isinstance(item, str) or not item for item in raw_allowed
            ):
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded diagnostic units are malformed")
            allowed = tuple(raw_allowed)
            if self.is_v3:
                scope = self.scopes.get(recorded_scope_id)
                expected_allowed = (
                    tuple(str(item) for item in scope["diagnostic_unit_ids"])
                    if scope is not None
                    else None
                )
            else:
                scope = None
                expected_allowed = () if recorded_scope_id is None else None
            if expected_allowed is None or allowed != expected_allowed:
                raise PracticeServiceError(
                    409,
                    "practice_scope_unavailable",
                    "recorded scope does not match its fixed diagnostic units",
                )
            session_id = command.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded session_id is malformed")
            engine.start_session(
                session_id,
                started_at=at,
                allowed_unit_ids=allowed,
            )
            return
        if operation == "question_presented":
            decision = engine.recommend_next(self.candidates, at=at)
            self._same(RecommendationAction.SERVE_QUESTION, decision.action, "recommendation_action")
            self._same(command.get("session_id"), decision.session_id, "session_id")
            self._same(command.get("decision_id"), decision.decision_id, "decision_id")
            self._same(command.get("question_id"), decision.question_id, "question_id")
            question = self.questions.get(str(decision.question_id))
            if question is None:
                raise PracticeServiceError(409, "content_version_unavailable", "recorded question is unavailable")
            self._same(command.get("question_version"), question["version"], "question_version")
            self._same(command.get("reason_codes"), list(decision.reason_codes), "reason_codes")
            return
        if operation in {"probe_presented", "no_eligible_question"}:
            decision = engine.recommend_next(self.candidates, at=at)
            expected_action = (
                RecommendationAction.SHOW_PROBE
                if operation == "probe_presented"
                else RecommendationAction.NO_ELIGIBLE_QUESTION
            )
            self._same(expected_action, decision.action, "recommendation_action")
            self._same(command.get("session_id"), decision.session_id, "session_id")
            self._same(command.get("decision_id"), decision.decision_id, "decision_id")
            self._same(command.get("reason_codes"), list(decision.reason_codes), "reason_codes")
            if operation == "probe_presented":
                self._same(command.get("hypothesis_id"), decision.hypothesis_id, "hypothesis_id")
            return
        if operation == "answer_submitted":
            decision = engine.pending_question_decision
            if decision is None:
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded answer has no presented question")
            self._same(command.get("session_id"), decision.session_id, "session_id")
            self._same(command.get("decision_id"), decision.decision_id, "decision_id")
            self._same(command.get("question_id"), decision.question_id, "question_id")
            question = self.questions.get(str(decision.question_id))
            if question is None:
                raise PracticeServiceError(409, "content_version_unavailable", "recorded question is unavailable")
            self._same(command.get("question_version"), question["version"], "question_version")
            answer = command.get("answer")
            if not isinstance(answer, str):
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded answer is malformed")
            try:
                rescored = self._score_question(question, answer)
            except ValueError:
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded answer cannot be rescored") from None
            if not isinstance(command.get("is_correct"), bool):
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded correctness is malformed")
            self._same(answer, rescored["selected_option"], "selected_option")
            self._same(command.get("is_correct"), bool(rescored["correct"]), "is_correct")
            self._same(
                command.get("error_signature_id"),
                rescored["observed_error_signature_id"],
                "error_signature_id",
            )
            cause_candidates = self._cause_candidates(rescored)
            self._same(command.get("cause_candidates"), list(cause_candidates), "cause_candidates")
            try:
                self._response_time(command.get("response_time_seconds"))
            except PracticeServiceError:
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded response time is malformed") from None
            hints_used = command.get("hints_used", 0)
            if isinstance(hints_used, bool) or not isinstance(hints_used, int):
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded hints_used is malformed")
            result = engine.submit_answer(
                decision.decision_id,
                answer=answer,
                is_correct=bool(rescored["correct"]),
                error_signature_id=rescored["observed_error_signature_id"],
                cause_candidates=cause_candidates,
                hints_used=hints_used,
                at=at,
            )
            self._same(
                command.get("feedback_decision_id"),
                result.feedback_decision.decision_id,
                "feedback_decision_id",
            )
            return
        if operation == "tutorial_shown":
            current_session = engine.current_session
            self._same(
                command.get("session_id"),
                current_session.session_id if current_session else None,
                "session_id",
            )
            hypothesis_id = command.get("hypothesis_id")
            if not isinstance(hypothesis_id, str):
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded hypothesis_id is malformed")
            hypothesis = engine.hypotheses.get(hypothesis_id)
            if hypothesis is None:
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded tutorial hypothesis is unavailable")
            expected_tutorial = self._microtutorial(
                target_cause_id=(
                    hypothesis.cause_candidates[0]
                    if len(hypothesis.cause_candidates) == 1
                    else None
                ),
                signature_id=hypothesis.error_signature_id,
            )
            if expected_tutorial is None:
                raise PracticeServiceError(409, "content_version_unavailable", "recorded tutorial content is unavailable")
            self._same(command.get("asset_id"), expected_tutorial["asset_id"], "asset_id")
            event = engine.record_tutorial_shown(
                hypothesis_id,
                asset_id=str(expected_tutorial["asset_id"]),
                at=at,
            )
            self._same(command.get("validation_event_id"), event.validation_event_id, "validation_event_id")
            return
        if operation == "probe_submitted":
            current_session = engine.current_session
            self._same(
                command.get("session_id"),
                current_session.session_id if current_session else None,
                "session_id",
            )
            hypothesis_id = command.get("hypothesis_id")
            answer = command.get("answer")
            if not isinstance(hypothesis_id, str) or not isinstance(answer, str):
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded probe answer is malformed")
            probe = self._probe(hypothesis_id, engine)
            if probe is None or answer not in probe.get("options", {}):
                raise PracticeServiceError(409, "content_version_unavailable", "recorded probe content is unavailable")
            outcomes = probe.get(
                "option_results",
                probe.get("outcomes", probe.get("option_outcomes", {})),
            )
            if not isinstance(outcomes, Mapping):
                raise PracticeServiceError(409, "content_version_unavailable", "recorded probe outcomes are unavailable")
            supported = outcomes.get(answer)
            if isinstance(supported, Mapping):
                supported = supported.get("supported_cause_id")
            supported_cause_id = supported if isinstance(supported, str) and supported else None
            self._same(command.get("supported_cause_id"), supported_cause_id, "supported_cause_id")
            engine.submit_probe_answer(
                hypothesis_id,
                answer=answer,
                supported_cause_id=supported_cause_id,
                at=at,
            )
            return
        if operation == "probe_skipped":
            current_session = engine.current_session
            self._same(
                command.get("session_id"),
                current_session.session_id if current_session else None,
                "session_id",
            )
            hypothesis_id = command.get("hypothesis_id")
            if not isinstance(hypothesis_id, str):
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded hypothesis_id is malformed")
            engine.skip_probe(hypothesis_id, at=at)
            return
        if operation == "session_ended":
            session = engine.current_session
            self._same(command.get("session_id"), session.session_id if session else None, "session_id")
            reason = command.get("reason")
            if not isinstance(reason, str) or not reason:
                raise PracticeServiceError(500, "invalid_practice_trace", "recorded end reason is malformed")
            if (
                reason == "content_exhausted"
                and (not engine.decisions or engine.decisions[-1].action is not RecommendationAction.NO_ELIGIBLE_QUESTION)
            ):
                decision = engine.recommend_next(self.candidates, at=at)
                self._same(RecommendationAction.NO_ELIGIBLE_QUESTION, decision.action, "recommendation_action")
            engine.end_session_early(at=at, reason=reason)
            return
        raise PracticeServiceError(500, "invalid_practice_trace", "practice command operation is unsupported")

    def _append_commands(
        self,
        engine: PracticePolicyEngine,
        kind: str,
        commands: list[dict[str, Any]],
    ) -> None:
        if not commands:
            raise PracticeServiceError(500, "invalid_practice_trace", "cannot append an empty command batch")
        command: dict[str, Any]
        if len(commands) == 1:
            command = commands[0]
        else:
            command = {"operation": "batch", "commands": commands}
        self._append(engine, kind, command)

    def _append(self, engine: PracticePolicyEngine, kind: str, command: dict[str, Any]) -> None:
        store = EventStore(self.database)
        try:
            store.append(
                self.trace_run_id,
                kind,
                {
                    "schema_version": (
                        "lumi.practice-command.v3"
                        if self.is_v3
                        else "lumi.practice-command.v2"
                    ),
                    "policy_version": PRACTICE_POLICY_VERSION,
                    "content": self.content_descriptor,
                    "command": command,
                    "snapshot_format": PRACTICE_SNAPSHOT_FORMAT,
                    "state_after": self._snapshot(engine),
                },
            )
        finally:
            store.close()

    def _recommend_and_record(
        self,
        engine: PracticePolicyEngine,
        at: datetime,
    ) -> RecommendationDecision | None:
        decision = engine.recommend_next(self.candidates, at=at)
        if decision.action is RecommendationAction.NO_ELIGIBLE_QUESTION:
            self._append(
                engine,
                "practice_no_eligible_question",
                {
                    "operation": "no_eligible_question",
                    "session_id": decision.session_id,
                    "decision_id": decision.decision_id,
                    "reason_codes": list(decision.reason_codes),
                    "at": at.isoformat(),
                },
            )
            engine.end_session_early(at=at, reason="content_exhausted")
            self._append(
                engine,
                "practice_session_ended",
                {
                    "operation": "session_ended",
                    "session_id": engine.current_session_id,
                    "reason": "content_exhausted",
                    "at": at.isoformat(),
                },
            )
            return None
        if decision.action is RecommendationAction.SHOW_PROBE:
            if decision.hypothesis_id is None:
                raise PracticeServiceError(
                    500,
                    "invalid_probe_state",
                    "policy probe recommendation has no hypothesis reference",
                )
            self._append(
                engine,
                "practice_probe_presented",
                {
                    "operation": "probe_presented",
                    "session_id": decision.session_id,
                    "decision_id": decision.decision_id,
                    "hypothesis_id": decision.hypothesis_id,
                    "reason_codes": list(decision.reason_codes),
                    "at": at.isoformat(),
                },
            )
            return decision
        if decision.action is not RecommendationAction.SERVE_QUESTION or decision.question_id is None:
            raise PracticeServiceError(500, "invalid_recommendation", "policy did not return an answerable question")
        self._append(
            engine,
            "practice_question_presented",
            {
                "operation": "question_presented",
                "session_id": decision.session_id,
                "decision_id": decision.decision_id,
                "question_id": decision.question_id,
                "question_version": self.questions[decision.question_id]["version"],
                "reason_codes": list(decision.reason_codes),
                "at": at.isoformat(),
            },
        )
        return decision

    def _session_response(
        self,
        engine: PracticePolicyEngine,
        session_id: str,
        *,
        decision: RecommendationDecision | None = None,
        resumed: bool,
    ) -> dict[str, Any]:
        session = self._session(engine, session_id)
        scope = self._scope_for_session(session)
        decision = decision or self._pending_question(engine)
        payload: dict[str, Any] = {
            "schema_version": PRACTICE_SCHEMA_VERSION,
            "title": str(scope["title"]) if scope is not None else self.title,
            "module_label": str(scope["module_label"]) if scope is not None else self.module_label,
            "resumed": resumed,
            "session": self._session_view(session),
            "links": self._links(session_id),
        }
        if decision is not None and decision.session_id == session_id and decision.question_id is not None:
            payload["question"] = self._question_view(decision)
            payload["audit"] = self._audit(decision)
        elif session.status is SessionStatus.ACTIVE:
            open_ids = self._open_probe_ids(engine)
            if open_ids:
                probe = self._probe(open_ids[0], engine)
                if probe is not None:
                    payload["pending_probe"] = self._safe_probe(probe, open_ids[0])
        else:
            payload["summary"] = self._summary(engine, session_id)
        return payload

    def _question_view(self, decision: RecommendationDecision) -> dict[str, Any]:
        question = self.questions[str(decision.question_id)]
        projected = self._safe_question(question)
        projected["question_version_id"] = projected.pop("version")
        projected["ordinal"] = decision.slot
        projected["total"] = 8
        projected["eyebrow"] = (
            "资料分析 · 增长率"
            if not self.is_v3
            else f"{projected['user_facing_type']} · 连续刷题"
        )
        return projected

    def _session_view(self, session: Any) -> dict[str, Any]:
        result = {
            "session_id": session.session_id,
            "status": session.status.value,
            "answered_count": session.item_count,
            "scored_count": session.graded_count,
            "target_count": session.target_count,
            "can_end_early": session.status is SessionStatus.ACTIVE,
            "started_at": session.started_at.isoformat(),
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        }
        scope = self._scope_for_session(session)
        if scope is not None:
            result["scope_id"] = scope["scope_id"]
            result["content"] = dict(self.content_descriptor)
        return result

    def _scope_for_session(self, session: Any) -> Mapping[str, Any] | None:
        if not self.is_v3:
            return None
        allowed = frozenset(session.allowed_unit_ids)
        matches = [
            scope
            for scope in self.scope_records
            if frozenset(str(item) for item in scope["diagnostic_unit_ids"]) == allowed
        ]
        if len(matches) != 1:
            raise PracticeServiceError(
                409,
                "practice_scope_unavailable",
                "session diagnostic units do not resolve to exactly one recorded scope",
            )
        return matches[0]

    def _feedback(
        self,
        question: Mapping[str, Any],
        scored: Mapping[str, Any],
        decision: RecommendationDecision,
        *,
        tutorial: Mapping[str, Any] | None,
        probe: Mapping[str, Any] | None,
        hypothesis_id: str | None,
    ) -> dict[str, Any]:
        levels = {
            RecommendationAction.CONTINUE: "A",
            RecommendationAction.LIGHT_FEEDBACK: "B",
            RecommendationAction.SHOW_MICRO_TUTORIAL: "C",
            RecommendationAction.SHOW_PROBE: "D",
        }
        feedback = question["feedback"]
        result: dict[str, Any] = {
            "level": levels.get(decision.action, "B"),
            "key_principle": "" if scored["correct"] else feedback["first_error_principle"],
            "explanation": feedback["full_explanation"],
        }
        if tutorial is not None:
            result["microtutorial"] = self._safe_tutorial(tutorial)
        if probe is not None and hypothesis_id is not None:
            result["probe"] = self._safe_probe(probe, hypothesis_id)
        elif (
            decision.action is RecommendationAction.SHOW_PROBE
            and hypothesis_id is not None
        ):
            result["probe_deferred"] = True
            result["follow_up"] = "next_fixed_eight_session"
        return result

    def _summary(self, engine: PracticePolicyEngine, session_id: str) -> dict[str, Any]:
        session = engine.sessions[session_id]
        attempts = [item for item in engine.attempts if item.session_id == session_id]
        correct = sum(1 for item in attempts if item.correct)
        hypotheses = sorted(
            (
                item
                for item in engine.hypotheses.values()
                if any(attempt_id in {attempt.attempt_id for attempt in attempts} for attempt_id in item.supporting_attempt_ids)
            ),
            key=lambda item: (-len(item.supporting_family_ids), item.hypothesis_id),
        )
        patterns = []
        for hypothesis in hypotheses[:2]:
            signature = self.error_signatures.get(hypothesis.error_signature_id, {})
            patterns.append(
                {
                    "id": hypothesis.hypothesis_id,
                    "signature_id": hypothesis.error_signature_id,
                    "title": signature.get("label", "待继续核对的作答模式"),
                    "evidence": f"本组有 {len(hypothesis.supporting_family_ids)} 个独立题族提供观察；当前为可撤销假设。",
                    "status": hypothesis.status.value,
                }
            )
        pending = [
            event
            for event in engine.validation_events.values()
            if event.status.value in {"scheduled", "eligible", "presented"}
        ]
        return {
            "title": "本组练习完成",
            "message": "只汇总可观察作答；错误原因仍是可撤销假设。",
            "facts": [
                {"id": "answered", "label": "完成题数", "value": f"{session.item_count} / 8"},
                {"id": "correct", "label": "答对", "value": f"{correct} 题"},
                {"id": "pending", "label": "待自然验证", "value": f"{len(pending)} 项"},
            ],
            "possible_patterns": patterns,
        }

    def _candidate(self, question: Mapping[str, Any]) -> QuestionCandidate:
        role_map = {
            "regular_practice": QuestionRole.PRACTICE,
            "near_transfer": QuestionRole.NEAR_TRANSFER,
            "delayed_validation": QuestionRole.DELAYED_VALIDATION,
        }
        roles = frozenset(
            role
            for key, role in role_map.items()
            if question["role_eligibility"].get(key)
        )
        kwargs: dict[str, Any] = {
            "question_id": question["question_id"],
            "diagnostic_unit_id": question["diagnostic_unit_id"],
            "evidence_family_id": question["evidence_family_id"],
            "eligible_roles": roles,
        }
        if "material_group_id" in QuestionCandidate.__dataclass_fields__:
            kwargs["material_group_id"] = question["material_group_id"]
        return QuestionCandidate(**kwargs)

    def _microtutorial(
        self,
        *,
        target_cause_id: str | None,
        signature_id: str | None,
    ) -> Mapping[str, Any] | None:
        tutorials = [item for item in self.interventions if item.get("kind") == "microtutorial"]
        if target_cause_id:
            exact = [item for item in tutorials if item.get("target_cause_id") == target_cause_id]
            if exact:
                return exact[0]
        exact = [
            item
            for item in tutorials
            if signature_id in item.get("target_signature_ids", ())
            or item.get("signature_id") == signature_id
        ]
        return exact[0] if exact else None

    def _probe(self, hypothesis_id: str, engine: PracticePolicyEngine) -> Mapping[str, Any] | None:
        hypothesis = engine.hypotheses.get(hypothesis_id)
        if hypothesis is None:
            return None
        probes = [
            item
            for item in self.interventions
            if item.get("kind") in {"probe", "structured_probe"}
        ]
        exact = [
            item
            for item in probes
            if hypothesis.error_signature_id in item.get("trigger_signature_ids", ())
            or item.get("signature_id") == hypothesis.error_signature_id
        ]
        return exact[0] if exact else (probes[0] if probes else None)

    @staticmethod
    def _safe_tutorial(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return {
            "asset_id": value["asset_id"],
            "title": value.get("title", "针对性讲解"),
            "body": value.get(
                "body",
                value.get("content", value.get("principle", "")),
            ),
            "points": list(value.get("points", []))
            or [
                item
                for item in (value.get("worked_contrast"), value.get("return_action"))
                if isinstance(item, str) and item
            ],
        }

    @staticmethod
    def _safe_probe(value: Mapping[str, Any], hypothesis_id: str) -> dict[str, Any]:
        return {
            "probe_id": value["asset_id"],
            "hypothesis_id": hypothesis_id,
            "prompt": value["prompt"],
            "options": dict(value["options"]),
        }

    @staticmethod
    def _cause_candidates(mapping: Mapping[str, Any]) -> tuple[str, ...]:
        raw = mapping.get("cause_candidates", mapping.get("cause_candidate_ids", []))
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
            return ()
        return tuple(sorted({item for item in raw if isinstance(item, str) and item}))

    @staticmethod
    def _pending_question(engine: PracticePolicyEngine) -> RecommendationDecision | None:
        public = getattr(engine, "pending_question_decision", None)
        if public is not None:
            return public
        answered = {item.source_decision_id for item in engine.attempts}
        return next(
            (
                item
                for item in reversed(engine.decisions)
                if item.action is RecommendationAction.SERVE_QUESTION
                and item.decision_id not in answered
            ),
            None,
        )

    @staticmethod
    def _open_probe_ids(engine: PracticePolicyEngine) -> tuple[str, ...]:
        public = getattr(engine, "open_probe_hypothesis_ids", None)
        if public is not None:
            return tuple(public)
        return tuple(sorted(getattr(engine, "_open_probe_hypothesis_ids", set())))

    def _session(self, engine: PracticePolicyEngine, session_id: str) -> Any:
        if (
            not isinstance(session_id, str)
            or not session_id
            or len(session_id) > 96
            or not _safe_identifier(session_id)
        ):
            raise PracticeServiceError(400, "invalid_session_id", "session_id is invalid")
        session = engine.sessions.get(session_id)
        if session is None:
            raise PracticeServiceError(404, "practice_session_not_found", "practice session does not exist")
        return session

    def _active_session(self, engine: PracticePolicyEngine, session_id: str) -> Any:
        session = self._session(engine, session_id)
        if session.status is not SessionStatus.ACTIVE:
            raise PracticeServiceError(409, "practice_session_closed", "practice session is already closed")
        return session

    def _snapshot(self, engine: PracticePolicyEngine) -> dict[str, Any]:
        return _jsonable(
            {
                "current_session_id": engine.current_session_id,
                "global_graded_count": engine.global_graded_count,
                "sessions": engine.sessions,
                "decisions": engine.decisions,
                "attempts": engine.attempts,
                "hypotheses": engine.hypotheses,
                "validation_events": engine.validation_events,
                "pending_question_decision_id": (
                    self._pending_question(engine).decision_id
                    if self._pending_question(engine) is not None
                    else None
                ),
                "open_probe_hypothesis_ids": self._open_probe_ids(engine),
            }
        )

    def _audit(self, decision: RecommendationDecision) -> dict[str, Any]:
        return {
            "decision_id": decision.decision_id,
            "reason_codes": list(decision.reason_codes),
            "policy_version": PRACTICE_POLICY_VERSION,
            "content": dict(self.content_descriptor),
            "trace_verified": self._trace_verified(),
        }

    def _trace_verified(self) -> bool:
        store = EventStore(self.database)
        try:
            return store.verify(self.trace_run_id)
        finally:
            store.close()

    @staticmethod
    def _same(expected: Any, actual: Any, field: str) -> None:
        if expected != actual:
            raise PracticeServiceError(500, "practice_replay_diverged", f"practice replay diverged at {field}")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("practice clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _response_time(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 7200:
            raise PracticeServiceError(400, "invalid_response_time", "response_time_seconds must be in [0, 7200]")
        return float(value)

    def _links(self, session_id: str) -> dict[str, str]:
        return {
            "self": f"/v1/practice-sessions/{session_id}",
            "answer": f"/v1/practice-sessions/{session_id}/answers",
            "probe": f"/v1/practice-sessions/{session_id}/probes",
            "end": f"/v1/practice-sessions/{session_id}/end",
            "trace": f"/v1/runs/{self.trace_run_id}/trace",
        }


class SmartPracticeCoordinator:
    """Route legacy v2 and fixed-bank v3 sessions without mixing traces."""

    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = str(database)
        lock_key = (
            self.database
            if self.database == ":memory:"
            else str(Path(self.database).expanduser().resolve())
        )
        with _PRACTICE_LOCKS_GUARD:
            self._operation_lock = _PRACTICE_LOCKS.setdefault(
                lock_key,
                threading.RLock(),
            )
        self._lock_path = (
            None
            if self.database == ":memory:"
            else Path(f"{lock_key}.practice.lock")
        )
        self.legacy = _ScopePracticeCoordinator(database, clock=clock)
        self.package = self.legacy.package
        self.package_id = self.legacy.package_id
        self.package_version = self.legacy.package_version
        self.candidates = self.legacy.candidates
        self.bank: Mapping[str, Any] | None = _load_practice_bank_v3()
        self.bank_id: str | None = None
        self.bank_version: str | None = None
        self.v3: _ScopePracticeCoordinator | None = None
        self.scope_records: tuple[dict[str, Any], ...] = ()

        merged_questions = dict(self.legacy.questions)
        if self.bank is not None:
            self.bank_id = str(self.bank["bank_id"])
            self.bank_version = str(self.bank["version"])
            self.scope_records = _scope_records(self.bank)
            self.v3 = _ScopePracticeCoordinator(
                database,
                clock=clock,
                bank=self.bank,
                scopes=self.scope_records,
            )
            for question in _records(self.bank.get("questions", ())):
                question_id = str(question["question_id"])
                if question_id in merged_questions:
                    raise RuntimeError(f"duplicate practice question_id: {question_id}")
                merged_questions[question_id] = question
        self.questions = merged_questions

    def start(
        self,
        unit_id: str | None = None,
        *,
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        with self._exclusive_operation():
            return self._start_unlocked(unit_id, scope_id=scope_id)

    def _start_unlocked(
        self,
        unit_id: str | None = None,
        *,
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        if unit_id is not None and scope_id is not None:
            raise PracticeServiceError(
                400,
                "ambiguous_practice_scope",
                "unit_id and scope_id cannot be supplied together",
            )
        if scope_id is not None and self.v3 is None:
            raise PracticeServiceError(404, "scope_not_found", "scope_id is not in the versioned practice bank")
        target = self.legacy if scope_id is None else self.v3
        if target is None:
            raise PracticeServiceError(404, "scope_not_found", "scope_id is not in the versioned practice bank")
        other_coordinators = [
            item
            for item in (self.legacy, self.v3)
            if item is not None and item is not target
        ]
        for coordinator in other_coordinators:
            active = coordinator._rehydrate().current_session
            if active is not None and active.status is SessionStatus.ACTIVE:
                raise PracticeServiceError(
                    409,
                    "active_practice_mode_conflict",
                    "end the active practice session before opening another practice mode",
                )
        if target is self.legacy:
            return target.start(unit_id)
        return target.start(scope_id=scope_id)

    def get(self, session_id: str) -> dict[str, Any]:
        with self._exclusive_operation():
            coordinator = self._coordinator_for_session(session_id)
            return coordinator.get(session_id)

    def submit_answer(
        self,
        session_id: str,
        question_id: Any,
        question_version_id: Any,
        answer: Any,
        response_time_seconds: Any = None,
    ) -> dict[str, Any]:
        with self._exclusive_operation():
            coordinator = self._coordinator_for_session(session_id)
            return coordinator.submit_answer(
                session_id,
                question_id,
                question_version_id,
                answer,
                response_time_seconds,
            )

    def submit_probe(self, session_id: str, hypothesis_id: Any, answer: Any) -> dict[str, Any]:
        with self._exclusive_operation():
            coordinator = self._coordinator_for_session(session_id)
            return coordinator.submit_probe(session_id, hypothesis_id, answer)

    def end(self, session_id: str, reason: str | None = None) -> dict[str, Any]:
        with self._exclusive_operation():
            coordinator = self._coordinator_for_session(session_id)
            return coordinator.end(session_id, reason)

    @contextmanager
    def _exclusive_operation(self):
        """Serialize rehydrate-decide-append across app instances and processes."""

        with self._operation_lock:
            if self._lock_path is None:
                yield
                return
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock_path.open("a+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def bank_capability(self) -> dict[str, Any] | None:
        if self.bank is None or self.bank_id is None or self.bank_version is None:
            return None
        scope_items = []
        for scope in self.scope_records:
            allowed = set(scope["diagnostic_unit_ids"])
            question_count = sum(
                question.get("diagnostic_unit_id") in allowed
                for question in _records(self.bank.get("questions", ()))
            )
            scope_items.append(
                {
                    "scope_id": scope["scope_id"],
                    "title": scope["title"],
                    "module_label": scope["module_label"],
                    "question_count": question_count,
                }
            )
        question_count = len(tuple(_records(self.bank.get("questions", ()))))
        module_scopes = [item for item in scope_items if item["scope_id"] != "xingce.mixed.core"]
        return {
            "bank_id": self.bank_id,
            "version": self.bank_version,
            "generated_sha256": self.bank.get("generated_sha256"),
            "target_count": 8,
            "counts": {
                "questions": question_count,
                "module_scopes": len(module_scopes),
                "scopes": len(scope_items),
                "questions_per_module": (
                    module_scopes[0]["question_count"]
                    if module_scopes
                    and len({item["question_count"] for item in module_scopes}) == 1
                    else None
                ),
            },
            "scopes": scope_items,
        }

    def verify_semantic_replay(self, run_id: str) -> bool | None:
        """Recompute a practice trace; return None for non-practice run ids."""

        coordinators = [self.legacy]
        if self.v3 is not None:
            coordinators.append(self.v3)
        matches = [item for item in coordinators if item.trace_run_id == run_id]
        if not matches:
            return None
        with self._exclusive_operation():
            matches[0]._rehydrate()
        return True

    def practice_session_report(self, session_id: str) -> dict[str, Any]:
        from .learning_records import PracticeLearningReadModel

        with self._exclusive_operation():
            return PracticeLearningReadModel(self).session_report(session_id)

    def practice_history(
        self,
        *,
        limit: int,
        offset: int,
        scope_id: str | None,
        status: str | None,
    ) -> dict[str, Any]:
        from .learning_records import PracticeLearningReadModel

        with self._exclusive_operation():
            return PracticeLearningReadModel(self).history(
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
        from .learning_records import PracticeLearningReadModel

        with self._exclusive_operation():
            return PracticeLearningReadModel(self).wrong_questions(
                limit=limit,
                offset=offset,
                state=state,
                module_id=module_id,
            )

    def practice_profile(self) -> dict[str, Any]:
        from .learning_records import PracticeLearningReadModel

        with self._exclusive_operation():
            return PracticeLearningReadModel(self).profile()

    def practice_overview(self) -> dict[str, Any]:
        from .learning_records import PracticeLearningReadModel

        with self._exclusive_operation():
            return PracticeLearningReadModel(self).overview()

    def recommendation_attempts(self) -> list[dict[str, Any]]:
        """Return the internal, JSON-first attempt evidence policy consumes."""

        from .learning_records import PracticeLearningReadModel

        with self._exclusive_operation():
            return PracticeLearningReadModel(self).recommendation_attempts()

    def _coordinator_for_session(self, session_id: str) -> _ScopePracticeCoordinator:
        if (
            not isinstance(session_id, str)
            or not session_id
            or len(session_id) > 96
            or not _safe_identifier(session_id)
        ):
            raise PracticeServiceError(400, "invalid_session_id", "session_id is invalid")
        coordinators = (self.legacy,) if self.v3 is None else (self.legacy, self.v3)
        for coordinator in coordinators:
            engine = coordinator._rehydrate()
            if session_id in engine.sessions:
                return coordinator
        raise PracticeServiceError(404, "practice_session_not_found", "practice session does not exist")


def _load_practice_bank_v3() -> Mapping[str, Any] | None:
    try:
        from hermes_domains.practice_bank_v3 import load_practice_bank
    except ModuleNotFoundError as exc:
        if exc.name == "hermes_domains.practice_bank_v3":
            return None
        raise
    bank = load_practice_bank()
    if not isinstance(bank, Mapping):
        raise RuntimeError("practice_bank_v3.load_practice_bank() must return a mapping")
    return bank


def _records(value: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, Mapping):
        return tuple(item for item in value.values() if isinstance(item, Mapping))
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _scope_records(bank: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    raw = bank.get("scopes", ())
    result: list[dict[str, Any]] = []
    if isinstance(raw, Mapping):
        values = raw.items()
    elif isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
        values = ((None, item) for item in raw)
    else:
        raise RuntimeError("practice bank scopes must be a list or mapping")
    for key, value in values:
        if not isinstance(value, Mapping):
            raise RuntimeError("practice bank scope records must be mappings")
        item = dict(value)
        if key is not None:
            item.setdefault("scope_id", str(key))
        required = {"scope_id", "title", "module_label", "diagnostic_unit_ids"}
        if not required.issubset(item):
            raise RuntimeError("practice bank scope record is incomplete")
        for field in ("scope_id", "title", "module_label"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise RuntimeError(f"practice bank scope {field} must be non-empty text")
        if not isinstance(item["diagnostic_unit_ids"], (list, tuple)):
            raise RuntimeError("scope diagnostic_unit_ids must be a list")
        if not item["diagnostic_unit_ids"] or any(
            not isinstance(unit_id, str) or not unit_id.strip()
            for unit_id in item["diagnostic_unit_ids"]
        ):
            raise RuntimeError("scope diagnostic_unit_ids must contain non-empty identifiers")
        if len(set(item["diagnostic_unit_ids"])) != len(item["diagnostic_unit_ids"]):
            raise RuntimeError("scope diagnostic_unit_ids cannot contain duplicates")
        result.append(item)
    scope_ids = {item["scope_id"] for item in result}
    if scope_ids != V3_SCOPE_IDS:
        raise RuntimeError("practice bank must expose four module scopes and one mixed scope")
    units_by_scope = {
        item["scope_id"]: frozenset(str(unit_id) for unit_id in item["diagnostic_unit_ids"])
        for item in result
    }
    module_union = frozenset().union(
        *(units for scope_id, units in units_by_scope.items() if scope_id != "xingce.mixed.core")
    )
    module_sets = [
        units
        for scope_id, units in units_by_scope.items()
        if scope_id != "xingce.mixed.core"
    ]
    if any(
        left & right
        for index, left in enumerate(module_sets)
        for right in module_sets[index + 1 :]
    ):
        raise RuntimeError("module scopes must have disjoint diagnostic units")
    if not module_union or units_by_scope["xingce.mixed.core"] != module_union:
        raise RuntimeError("mixed scope must be the exact union of the four module scopes")
    return tuple(result)


def _intervention_records(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if "asset_id" in value and "kind" in value:
            yield value
            return
        for item in value.values():
            yield from _intervention_records(item)
        return
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _intervention_records(item)


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise PracticeServiceError(500, "invalid_practice_trace", "practice command time is missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise PracticeServiceError(500, "invalid_practice_trace", "practice command time is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PracticeServiceError(500, "invalid_practice_trace", "practice command time lacks timezone")
    return parsed


def _safe_identifier(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "-_.:" for character in value)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        items = [_jsonable(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
