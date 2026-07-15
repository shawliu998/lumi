from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from hermes_runtime.store import EventStore


PROFILE_SCHEMA_VERSION = "lumi.practice-profile.v1"
HISTORY_SCHEMA_VERSION = "lumi.practice-history.v1"
WRONG_BOOK_SCHEMA_VERSION = "lumi.wrong-question-book.v1"
SESSION_REPORT_SCHEMA_VERSION = "lumi.practice-session-report.v1"
OVERVIEW_SCHEMA_VERSION = "lumi.practice-overview.v1"

MODULE_ORDER = (
    "xingce.verbal.core",
    "xingce.judgment.core",
    "xingce.quantitative.core",
    "xingce.data-analysis.core",
)
MODULE_LABELS = {
    "xingce.verbal.core": "言语理解",
    "xingce.judgment.core": "判断推理",
    "xingce.quantitative.core": "数量关系",
    "xingce.data-analysis.core": "资料分析",
}
MIXED_SCOPE_ID = "xingce.mixed.core"


class PracticeLearningReadModel:
    """Rebuild learner-facing aggregates from verified practice traces.

    This is intentionally a read model, not another source of learner state.
    Every call first asks the existing practice coordinators to perform their
    hash and semantic replay checks, then derives views from that reconstructed
    state and the append-only answer commands.
    """

    def __init__(self, smart_practice: Any) -> None:
        self.smart_practice = smart_practice

    def session_report(self, session_id: str) -> dict[str, Any]:
        snapshot = self._snapshot()
        session = next(
            (item for item in snapshot["sessions"] if item["session_id"] == session_id),
            None,
        )
        if session is None:
            # Imported lazily to keep this read-model module free of a circular
            # import at module initialization time.
            from .practice_v2 import PracticeServiceError

            raise PracticeServiceError(
                404,
                "practice_session_not_found",
                "practice session does not exist",
            )
        attempts = [
            item for item in snapshot["attempts"] if item["session_id"] == session_id
        ]
        hypotheses = self._public_hypotheses(
            snapshot,
            attempt_ids={item["attempt_id"] for item in attempts},
        )
        report = {
            "schema_version": SESSION_REPORT_SCHEMA_VERSION,
            "session": self._session_item(session, attempts),
            "metrics": self._metrics(
                attempts,
                answered_count=session["answered_count"],
                scored_count=session["scored_count"],
            ),
            "module_breakdown": self._module_breakdown(attempts),
            "error_hypotheses": hypotheses,
            "recommendation": self._session_recommendation(session, attempts),
            "audit": self._audit(snapshot),
        }
        return report

    def history(
        self,
        *,
        limit: int,
        offset: int,
        scope_id: str | None,
        status: str | None,
    ) -> dict[str, Any]:
        snapshot = self._snapshot()
        attempts_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for attempt in snapshot["attempts"]:
            attempts_by_session[attempt["session_id"]].append(attempt)
        items = [
            self._session_item(
                session,
                attempts_by_session.get(session["session_id"], []),
            )
            for session in snapshot["sessions"]
            if (scope_id is None or session["scope_id"] == scope_id)
            and (status is None or session["status"] == status)
        ]
        items.sort(
            key=lambda item: (item["started_at"], item["session_id"]),
            reverse=True,
        )
        total = len(items)
        page = items[offset : offset + limit]
        return {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "total": total,
            "count": len(page),
            "offset": offset,
            "limit": limit,
            "items": page,
            "audit": self._audit(snapshot),
        }

    def wrong_questions(
        self,
        *,
        limit: int,
        offset: int,
        state: str,
        module_id: str | None,
    ) -> dict[str, Any]:
        snapshot = self._snapshot()
        projection = self._wrong_questions_from_snapshot(
            snapshot,
            limit=limit,
            offset=offset,
            state=state,
            module_id=module_id,
        )
        page = projection["items"]
        return {
            "schema_version": WRONG_BOOK_SCHEMA_VERSION,
            "state": state,
            "module_id": module_id,
            "total": projection["total"],
            "count": len(page),
            "offset": offset,
            "limit": limit,
            "items": page,
            "audit": self._audit(snapshot),
        }

    def profile(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            **self._profile_body(snapshot),
            "audit": self._audit(snapshot),
        }

    def overview(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        attempts_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for attempt in snapshot["attempts"]:
            attempts_by_session[attempt["session_id"]].append(attempt)
        recent_sessions = [
            self._session_item(
                session,
                attempts_by_session.get(session["session_id"], []),
            )
            for session in snapshot["sessions"]
        ]
        recent_sessions.sort(
            key=lambda item: (item["started_at"], item["session_id"]),
            reverse=True,
        )
        wrong_payload = self._wrong_questions_from_snapshot(
            snapshot,
            limit=5,
            offset=0,
            state="needs_review",
            module_id=None,
        )
        return {
            "schema_version": OVERVIEW_SCHEMA_VERSION,
            "profile": self._profile_body(snapshot),
            "recent_sessions": recent_sessions[:5],
            "wrong_question_preview": wrong_payload["items"],
            "recommendation": self._recommendation(snapshot, recent_sessions),
            "audit": self._audit(snapshot),
        }

    def recommendation_attempts(self) -> list[dict[str, Any]]:
        """Internal JSON-first evidence contract for the policy package."""

        snapshot = self._snapshot()
        fields = (
            "attempt_id",
            "session_id",
            "question_id",
            "question_version_id",
            "scope_id",
            "module_id",
            "diagnostic_unit_id",
            "evidence_family_id",
            "material_group_id",
            "correct",
            "independent_evidence",
            "answered_at",
            "response_time_seconds",
            "error_signature_id",
            "cause_candidates",
        )
        return [{field: item[field] for field in fields} for item in snapshot["attempts"]]

    def _wrong_questions_from_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        limit: int,
        offset: int,
        state: str,
        module_id: str | None,
    ) -> dict[str, Any]:
        # Reuse the one canonical projection without rebuilding or persisting a
        # second view. The temporary method replacement is avoided by keeping
        # the actual projection in a small local helper below.
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for attempt in snapshot["attempts"]:
            grouped[(attempt["question_id"], attempt["question_version_id"])].append(
                attempt
            )
        items: list[dict[str, Any]] = []
        for attempts in grouped.values():
            attempts.sort(key=lambda item: (item["answered_at"], item["attempt_id"]))
            wrong = [item for item in attempts if not item["correct"]]
            if not wrong:
                continue
            latest = attempts[-1]
            review_state = "resolved" if latest["correct"] else "needs_review"
            if state != "all" and state != review_state:
                continue
            if module_id is not None and latest["module_id"] != module_id:
                continue
            question = latest["_question"]
            safe_question = latest["_safe_question"]
            items.append(
                {
                    "question_ref": {
                        "question_id": latest["question_id"],
                        "question_version_id": latest["question_version_id"],
                    },
                    "module_id": latest["module_id"],
                    "module_label": latest["module_label"],
                    "diagnostic_unit_id": latest["diagnostic_unit_id"],
                    "review_state": review_state,
                    "question": {
                        "prompt": safe_question.get("prompt", ""),
                        "response_mode": safe_question.get(
                            "response_mode", "single_choice"
                        ),
                        "options": dict(safe_question.get("options", {})),
                    },
                    "answer_review": {
                        "correct_option": question["scoring"]["correct_option"],
                        "key_principle": question["feedback"].get(
                            "first_error_principle", ""
                        ),
                        "explanation": question["feedback"].get(
                            "full_explanation", ""
                        ),
                    },
                    "attempts": {
                        "total_count": len(attempts),
                        "wrong_count": len(wrong),
                        "independent_wrong_count": sum(
                            item["independent_evidence"] for item in wrong
                        ),
                        "last_selected_option": latest["selected_option"],
                        "last_wrong_at": wrong[-1]["answered_at"],
                        "last_attempt_at": latest["answered_at"],
                    },
                    "diagnosis_hypotheses": self._public_hypotheses(
                        snapshot,
                        attempt_ids={item["attempt_id"] for item in wrong},
                    ),
                }
            )
        items.sort(
            key=lambda item: (
                item["attempts"]["last_wrong_at"],
                item["question_ref"]["question_id"],
            ),
            reverse=True,
        )
        total = len(items)
        return {"total": total, "items": items[offset : offset + limit]}

    def _snapshot(self) -> dict[str, Any]:
        sessions: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        hypotheses: list[dict[str, Any]] = []
        traces: list[dict[str, Any]] = []
        probe_count = 0
        coordinators = [self.smart_practice.legacy]
        if self.smart_practice.v3 is not None:
            coordinators.append(self.smart_practice.v3)

        for coordinator in coordinators:
            engine = coordinator._rehydrate()
            store = EventStore(self.smart_practice.database)
            try:
                events = store.events(coordinator.trace_run_id)
                trace_verified = store.verify(coordinator.trace_run_id)
            finally:
                store.close()
            if events and not trace_verified:
                # _rehydrate already rejects this; retain a defensive assertion
                # so future coordinator implementations cannot bypass it.
                raise RuntimeError("practice trace became invalid during read-model rebuild")

            command_meta: dict[str, dict[str, Any]] = {}
            scope_by_session: dict[str, str | None] = {}
            for event in events:
                command = event.payload.get("command")
                for item in _flatten_commands(command):
                    operation = item.get("operation")
                    if operation == "session_started":
                        session_id = item.get("session_id")
                        if isinstance(session_id, str):
                            raw_scope = item.get("scope_id")
                            scope_by_session[session_id] = (
                                raw_scope if isinstance(raw_scope, str) else None
                            )
                    elif operation == "answer_submitted":
                        decision_id = item.get("decision_id")
                        if isinstance(decision_id, str):
                            command_meta[decision_id] = dict(item)
                    elif operation in {"probe_submitted", "probe_skipped"}:
                        probe_count += 1

            for session in engine.sessions.values():
                scope_id = scope_by_session.get(session.session_id)
                if scope_id is not None:
                    scope = coordinator.scopes.get(scope_id, {})
                    title = str(scope.get("title", coordinator.title))
                    module_label = str(
                        scope.get("module_label", coordinator.module_label)
                    )
                else:
                    title = coordinator.title
                    module_label = coordinator.module_label
                sessions.append(
                    {
                        "session_id": session.session_id,
                        "scope_id": scope_id,
                        "title": title,
                        "module_label": module_label,
                        "status": session.status.value,
                        "started_at": session.started_at.isoformat(),
                        "ended_at": (
                            session.ended_at.isoformat() if session.ended_at else None
                        ),
                        "end_reason": session.end_reason,
                        "target_count": session.target_count,
                        "answered_count": session.item_count,
                        "scored_count": session.graded_count,
                        "content": dict(coordinator.content_descriptor),
                        "trace_run_id": coordinator.trace_run_id,
                    }
                )

            for attempt in engine.attempts:
                question = coordinator.questions[attempt.question_id]
                meta = command_meta.get(attempt.source_decision_id, {})
                module_id = _question_module_id(question)
                attempts.append(
                    {
                        "attempt_id": attempt.attempt_id,
                        "session_id": attempt.session_id,
                        "source_decision_id": attempt.source_decision_id,
                        "question_id": attempt.question_id,
                        "question_version_id": str(
                            meta.get("question_version", question["version"])
                        ),
                        "scope_id": scope_by_session.get(attempt.session_id),
                        "module_id": module_id,
                        "module_label": str(
                            question.get(
                                "user_facing_type", MODULE_LABELS.get(module_id, "行测")
                            )
                        ),
                        "diagnostic_unit_id": attempt.diagnostic_unit_id,
                        "evidence_family_id": attempt.evidence_family_id,
                        "material_group_id": attempt.material_group_id,
                        "role": attempt.role.value,
                        "selected_option": attempt.answer,
                        "correct": attempt.correct,
                        "independent_evidence": attempt.independent_evidence,
                        "independent_ineligibility_reasons": list(
                            attempt.independent_ineligibility_reasons
                        ),
                        "answered_at": attempt.answered_at.isoformat(),
                        "response_time_seconds": meta.get("response_time_seconds"),
                        "error_signature_id": attempt.error_signature_id,
                        "cause_candidates": list(attempt.cause_candidates),
                        "validation_event_id": attempt.validation_event_id,
                        "_question": question,
                        "_safe_question": coordinator._safe_question(question),
                        "_trace_run_id": coordinator.trace_run_id,
                    }
                )

            attempt_by_id = {item["attempt_id"]: item for item in attempts}
            for hypothesis in engine.hypotheses.values():
                independent_support = [
                    attempt_id
                    for attempt_id in hypothesis.supporting_attempt_ids
                    if attempt_id in attempt_by_id
                    and attempt_by_id[attempt_id]["independent_evidence"]
                ]
                module_id = _diagnostic_module_id(hypothesis.diagnostic_unit_id)
                signature = coordinator.error_signatures.get(
                    hypothesis.error_signature_id, {}
                )
                causes = []
                for rank, cause_id in enumerate(hypothesis.cause_candidates, start=1):
                    cause = coordinator.cause_registry.get(cause_id, {})
                    causes.append(
                        {
                            "cause_id": cause_id,
                            "rank": rank,
                            "label": cause.get("label", "待继续验证的可能原因"),
                            "semantics": "reversible_hypothesis_not_fact",
                        }
                    )
                validation = [
                    engine.validation_events[event_id]
                    for event_id in hypothesis.validation_event_ids
                    if event_id in engine.validation_events
                ]
                hypotheses.append(
                    {
                        "hypothesis_id": hypothesis.hypothesis_id,
                        "module_id": module_id,
                        "diagnostic_unit_id": hypothesis.diagnostic_unit_id,
                        "error_signature_id": hypothesis.error_signature_id,
                        "signature_label": signature.get(
                            "label", "观察到的错误选项模式"
                        ),
                        "status": hypothesis.status.value,
                        "cause_candidates": causes,
                        "independent_attempt_refs": independent_support,
                        "independent_family_count": len(
                            {
                                attempt_by_id[attempt_id]["evidence_family_id"]
                                for attempt_id in independent_support
                            }
                        ),
                        "independent_material_count": len(
                            {
                                attempt_by_id[attempt_id]["material_group_id"]
                                for attempt_id in independent_support
                            }
                        ),
                        "validation": [
                            {
                                "validation_event_id": item.validation_event_id,
                                "kind": item.kind.value,
                                "status": item.status.value,
                                "outcome_attempt_id": item.outcome_attempt_id,
                            }
                            for item in validation
                        ],
                        "support_reason_codes": [
                            transition.reason for transition in hypothesis.transitions
                        ],
                        "_trace_run_id": coordinator.trace_run_id,
                    }
                )
            traces.append(
                {
                    "trace_run_id": coordinator.trace_run_id,
                    "event_count": len(events),
                    "last_event_at": events[-1].occurred_at if events else None,
                    "trace_verified": trace_verified,
                    "semantic_replay_verified": True,
                    "schema_versions": sorted(
                        {
                            str(event.payload["schema_version"])
                            for event in events
                            if isinstance(event.payload.get("schema_version"), str)
                        }
                    ),
                    "policy_versions": sorted(
                        {
                            str(event.payload["policy_version"])
                            for event in events
                            if isinstance(event.payload.get("policy_version"), str)
                        }
                    ),
                    "content": dict(coordinator.content_descriptor),
                }
            )

        sessions.sort(key=lambda item: (item["started_at"], item["session_id"]))
        attempts.sort(key=lambda item: (item["answered_at"], item["attempt_id"]))
        values = [item["started_at"] for item in sessions]
        values.extend(item["answered_at"] for item in attempts)
        values.extend(
            item["ended_at"] for item in sessions if item["ended_at"] is not None
        )
        values.extend(
            item["last_event_at"]
            for item in traces
            if item["last_event_at"] is not None
        )
        return {
            "sessions": sessions,
            "attempts": attempts,
            "hypotheses": hypotheses,
            "traces": traces,
            "probe_count": probe_count,
            "as_of": max(values) if values else None,
        }

    def _profile_body(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        attempts = snapshot["attempts"]
        modules = []
        for module_id in MODULE_ORDER:
            selected = [item for item in attempts if item["module_id"] == module_id]
            independent = [item for item in selected if item["independent_evidence"]]
            status, reason_codes = _evidence_status(independent)
            modules.append(
                {
                    "module_id": module_id,
                    "module_label": MODULE_LABELS[module_id],
                    "facts": self._attempt_facts(selected),
                    "independent_evidence": {
                        **self._attempt_facts(independent),
                        "distinct_family_count": len(
                            {item["evidence_family_id"] for item in independent}
                        ),
                        "verified_transfer_count": sum(
                            item["correct"]
                            and item["role"] in {"near_transfer", "delayed_validation"}
                            for item in independent
                        ),
                    },
                    "ignored_non_independent_count": len(selected) - len(independent),
                    "evidence_status": status,
                    "reason_codes": reason_codes,
                }
            )
        independent = [item for item in attempts if item["independent_evidence"]]
        overall_facts = self._attempt_facts(attempts)
        return {
            "as_of": snapshot["as_of"],
            "overall": {
                "session_count": len(snapshot["sessions"]),
                "completed_session_count": sum(
                    item["status"] == "completed" for item in snapshot["sessions"]
                ),
                "scored_attempt_count": overall_facts["attempt_count"],
                "correct_count": overall_facts["correct_count"],
                "incorrect_count": overall_facts["incorrect_count"],
                "accuracy": overall_facts["accuracy"],
                "independent_attempt_count": len(independent),
                "ignored_non_independent_attempt_count": len(attempts)
                - len(independent),
                "recorded_response_time_count": overall_facts[
                    "recorded_response_time_count"
                ],
                "average_response_time_seconds": overall_facts[
                    "average_response_time_seconds"
                ],
            },
            "modules": modules,
            "error_hypotheses": self._public_hypotheses(snapshot),
            "evidence_policy": {
                "id": "lumi.practice-profile-evidence.v1",
                "mastery_claimed": False,
                "independent_attempts_only_for_evidence_status": True,
                "excluded_probe_count": snapshot["probe_count"],
                "note": (
                    "正确率是作答事实；错误原因是可撤销假设。结构化探查、"
                    "重复暴露和其他非独立作答不计入模块证据状态。"
                ),
            },
        }

    def _public_hypotheses(
        self,
        snapshot: dict[str, Any],
        *,
        attempt_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        result = []
        for item in snapshot["hypotheses"]:
            refs = set(item["independent_attempt_refs"])
            if attempt_ids is not None and not refs.intersection(attempt_ids):
                continue
            public = {key: value for key, value in item.items() if not key.startswith("_")}
            level, basis = _hypothesis_confidence(item)
            public["confidence"] = {
                "level": level,
                "basis_codes": basis,
                "semantics": "ordinal_evidence_label_not_probability",
            }
            result.append(public)
        result.sort(
            key=lambda item: (
                -item["independent_family_count"],
                item["hypothesis_id"],
            )
        )
        return result

    def _session_item(
        self,
        session: Mapping[str, Any],
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        metrics = self._metrics(
            attempts,
            answered_count=session["answered_count"],
            scored_count=session["scored_count"],
        )
        return {
            "session_id": session["session_id"],
            "scope_id": session["scope_id"],
            "title": session["title"],
            "module_label": session["module_label"],
            "status": session["status"],
            "started_at": session["started_at"],
            "ended_at": session["ended_at"],
            "end_reason": session["end_reason"],
            "target_count": session["target_count"],
            "content": dict(session["content"]),
            **metrics,
            "links": {
                "session": f"/v1/practice-sessions/{session['session_id']}",
                "report": f"/v1/practice-sessions/{session['session_id']}/report",
            },
        }

    def _metrics(
        self,
        attempts: list[dict[str, Any]],
        *,
        answered_count: int,
        scored_count: int,
    ) -> dict[str, Any]:
        facts = self._attempt_facts(attempts)
        return {
            "answered_count": answered_count,
            "scored_count": scored_count,
            "question_attempt_count": facts["attempt_count"],
            "probe_or_skip_count": answered_count - facts["attempt_count"],
            "probe_scored_count": scored_count - facts["attempt_count"],
            "correct_count": facts["correct_count"],
            "incorrect_count": facts["incorrect_count"],
            "accuracy": facts["accuracy"],
            "recorded_response_time_count": facts["recorded_response_time_count"],
            "total_response_time_seconds": facts["total_response_time_seconds"],
            "average_response_time_seconds": facts["average_response_time_seconds"],
        }

    @staticmethod
    def _attempt_facts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
        correct = sum(item["correct"] for item in attempts)
        recorded_times = [
            float(item["response_time_seconds"])
            for item in attempts
            if item["response_time_seconds"] is not None
        ]
        total_time = round(sum(recorded_times), 3) if recorded_times else None
        return {
            "attempt_count": len(attempts),
            "correct_count": correct,
            "incorrect_count": len(attempts) - correct,
            "accuracy": _ratio(correct, len(attempts)),
            "recorded_response_time_count": len(recorded_times),
            "total_response_time_seconds": total_time,
            "average_response_time_seconds": (
                round(sum(recorded_times) / len(recorded_times), 3)
                if recorded_times
                else None
            ),
        }

    def _module_breakdown(
        self, attempts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        result = []
        present = {item["module_id"] for item in attempts}
        for module_id in MODULE_ORDER:
            if module_id not in present:
                continue
            result.append(
                {
                    "module_id": module_id,
                    "module_label": MODULE_LABELS[module_id],
                    **self._attempt_facts(
                        [item for item in attempts if item["module_id"] == module_id]
                    ),
                }
            )
        return result

    def _recommendation(
        self,
        snapshot: dict[str, Any],
        recent_sessions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        latest_scope_id = recent_sessions[0]["scope_id"] if recent_sessions else None
        current_scope_id = (
            latest_scope_id
            if latest_scope_id in {*MODULE_ORDER, MIXED_SCOPE_ID}
            else None
        )
        decided_at = snapshot["as_of"] or datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()
        attempts = self.recommendation_attempts_from_snapshot(snapshot)
        try:
            from hermes_practice import recommend_next_scope
        except ImportError:
            return _fallback_recommendation(
                attempts,
                current_scope_id=current_scope_id,
                decided_at=decided_at,
            )
        return recommend_next_scope(
            attempts=attempts,
            scopes=list(self.smart_practice.scope_records),
            current_scope_id=current_scope_id,
            mixed_scope_id=MIXED_SCOPE_ID,
            decided_at=decided_at,
            recent_question_limit=16,
        )

    @staticmethod
    def recommendation_attempts_from_snapshot(
        snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        fields = (
            "attempt_id",
            "session_id",
            "question_id",
            "question_version_id",
            "scope_id",
            "module_id",
            "diagnostic_unit_id",
            "evidence_family_id",
            "material_group_id",
            "correct",
            "independent_evidence",
            "answered_at",
            "response_time_seconds",
            "error_signature_id",
            "cause_candidates",
        )
        return [{field: item[field] for field in fields} for item in snapshot["attempts"]]

    @staticmethod
    def _session_recommendation(
        session: Mapping[str, Any],
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if session["status"] == "active":
            action = "resume_session"
            reason_codes = ["session_active"]
        elif any(not item["correct"] for item in attempts):
            action = "continue_with_error_evidence"
            reason_codes = ["incorrect_attempts_observed"]
        else:
            action = "continue_practice"
            reason_codes = ["session_closed"]
        return {
            "kind": action,
            "scope_id": session["scope_id"],
            "reason_codes": reason_codes,
            "evidence_refs": [
                item["attempt_id"] for item in attempts if not item["correct"]
            ],
            "semantics": "deterministic_summary_not_a_mastery_claim",
        }

    @staticmethod
    def _audit(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": "verified_append_only_practice_trace",
            "rebuildable": True,
            "trace_verified": all(
                item["trace_verified"] for item in snapshot["traces"]
            ),
            "semantic_replay_verified": all(
                item["semantic_replay_verified"] for item in snapshot["traces"]
            ),
            "traces": snapshot["traces"],
        }


def _flatten_commands(value: Any) -> Iterable[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return ()
    if value.get("operation") != "batch":
        return (value,)
    commands = value.get("commands")
    if not isinstance(commands, list):
        return ()
    return tuple(item for item in commands if isinstance(item, Mapping))


def _question_module_id(question: Mapping[str, Any]) -> str:
    value = question.get("module_id")
    if isinstance(value, str) and value in MODULE_LABELS:
        return value
    return _diagnostic_module_id(str(question.get("diagnostic_unit_id", "")))


def _diagnostic_module_id(diagnostic_unit_id: str) -> str:
    parts = diagnostic_unit_id.split(".")
    slug = parts[1] if len(parts) > 1 else ""
    aliases = {
        "verbal": "xingce.verbal.core",
        "judgment": "xingce.judgment.core",
        "quantitative": "xingce.quantitative.core",
        "data-analysis": "xingce.data-analysis.core",
    }
    return aliases.get(slug, "xingce.data-analysis.core")


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _evidence_status(
    attempts: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    if not attempts:
        return "no_evidence", ["no_independent_attempts"]
    if len(attempts) < 3:
        return "insufficient", ["fewer_than_three_independent_attempts"]
    accuracy = sum(item["correct"] for item in attempts) / len(attempts)
    if accuracy < 0.6:
        return "needs_attention", ["independent_accuracy_below_0_6"]
    if len(attempts) >= 5 and accuracy >= 0.8:
        return "consistent", ["at_least_five_independent_attempts", "accuracy_at_least_0_8"]
    return "developing", ["independent_evidence_mixed_or_limited"]


def _hypothesis_confidence(item: Mapping[str, Any]) -> tuple[str, list[str]]:
    if "optional_probe_supported_one_actionable_cause" in item[
        "support_reason_codes"
    ]:
        return "probe_supported", ["structured_probe_narrowed_candidates"]
    if item["independent_family_count"] >= 2:
        return "repeated_observation", ["multiple_independent_evidence_families"]
    return "provisional", ["insufficient_independent_repetition"]


def _fallback_recommendation(
    attempts: list[dict[str, Any]],
    *,
    current_scope_id: str | None,
    decided_at: str,
) -> dict[str, Any]:
    """Compatibility fallback used only while the replaceable policy is absent."""

    independent = [
        item
        for item in attempts
        if item["independent_evidence"] and item["module_id"] in MODULE_ORDER
    ]
    # A missing replaceable policy must fail conservatively. In particular, a
    # single failure can never substitute for the policy's cross-session and
    # cross-family support thresholds.
    recommended = current_scope_id or MIXED_SCOPE_ID
    reasons = ["policy_unavailable_insufficient_evidence"]
    evidence_refs: list[str] = []
    return {
        "schema_version": "lumi.next-scope-recommendation.v1",
        "decided_at": decided_at,
        "policy": {
            "id": "lumi.service-fallback-next-scope",
            "version": "1.0.0",
            "confidence_semantics": "ordinal_not_probability",
        },
        "decision": {
            "recommended_scope_id": recommended,
            "current_scope_id": current_scope_id,
            "practice_action": "start_or_resume_fixed_eight",
            "reason_codes": reasons,
            "evidence_refs": evidence_refs,
        },
        "module_summaries": [],
        "skill_weakness_summaries": [],
        "evidence_accounting": {
            "total_attempt_count": len(attempts),
            "independent_in_scope_count": len(independent),
            "non_independent_excluded_from_weakness_refs": [
                item["attempt_id"] for item in attempts if not item["independent_evidence"]
            ],
            "out_of_catalog_evidence_refs": [],
        },
        "serving_hints": {
            "soft_avoid_question_ids": [],
            "limit": 16,
            "reason_codes": ["replaceable_policy_unavailable"],
        },
    }
