"""Local, inspectable conditional-reasoning learning sessions.

This is an additive service core for the first Lumi application domain.  It
does not register a draft Domain Pack: construction requires the separate,
hash-bound reviewed-pack loader.  A session persists only learner observations,
policy decisions, public activity projections, and deterministic receipts.  It
never serializes answer keys, proofs, distractor mappings, or teaching-routing
metadata into a learner-facing response or replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import secrets
from pathlib import Path
from typing import Any, Callable, Mapping

from hermes_domains.judgment_policy import (
    EntryObservation,
    EntryPolicyDecision,
    HistoricalCandidateEvidence,
    JudgmentPolicyError,
    ProbeResolution,
    diagnose_entry,
    resolve_probe,
)
from hermes_domains.reasoning_pack import (
    ReasoningPackError,
    load_reviewed_reasoning_pack,
)
from hermes_runtime.learner_state import (
    LearnerStateError,
    LearnerStateStore,
    LearnerStateVersionConflict,
)
from hermes_runtime.store import EventStore, TraceEvent, TraceVersionConflict


JUDGMENT_SESSION_SCHEMA = "lumi.judgment-session.v1"
HUMAN_ORIGIN = "human_local_interactive"
_ORIGIN_PREFIX = {
    "human_local_interactive": "human:",
    "evaluation_fixture": "eval:",
    "synthetic_isolated": "synthetic:",
}
_PUBLIC_ASSESSMENT_FIELDS = frozenset(
    {"record_id", "role", "title", "prompt", "response_mode", "options"}
)
_PUBLIC_TEACHING_FIELDS = frozenset(
    {"record_id", "role", "title", "teaching_strategy", "teaching_content", "logic_rule"}
)
_LEARNER_VISIBLE_ENTRY_FACT_KINDS = frozenset(
    {"selected_option", "correctness", "confidence", "elapsed_seconds", "hint_count"}
)


class JudgmentSessionError(RuntimeError):
    """A local judgement-reasoning command could not be completed safely."""


class JudgmentContentUnavailable(JudgmentSessionError):
    """The configured pack is absent, draft, or lacks its human review record."""


class JudgmentSessionConflict(JudgmentSessionError):
    """A stale, out-of-order, or semantically different replay was rejected."""


@dataclass(frozen=True, slots=True)
class JudgmentSessionConfig:
    namespace_id: str = "human:local-lumi"
    evidence_origin: str = HUMAN_ORIGIN
    learner_id: str = "local-lumi"

    def __post_init__(self) -> None:
        expected = _ORIGIN_PREFIX.get(self.evidence_origin)
        if expected is None or not self.namespace_id.startswith(expected):
            raise ValueError("judgment session namespace must match evidence origin")
        if not self.learner_id.strip() or len(self.learner_id) > 240:
            raise ValueError("judgment session learner_id must be a short non-empty string")


def judgment_pack_status(pack_root: str | Path | None) -> dict[str, Any]:
    """Return a fail-closed availability projection without exposing draft text."""

    if pack_root is None:
        return {
            "available": False,
            "reason": "content_review_required",
            "message": "判断推理题包尚未通过逻辑与编辑/权属审核，不能开始学习记录。",
        }
    try:
        private = load_reviewed_reasoning_pack(Path(pack_root), projection="private")
    except (OSError, ReasoningPackError, ValueError):
        return {
            "available": False,
            "reason": "content_review_required",
            "message": "判断推理题包尚未通过逻辑与编辑/权属审核，不能开始学习记录。",
        }
    return {
        "available": True,
        "pack_id": private["pack_id"],
        "pack_version": private["pack_version"],
        "record_count": len(private["records"]),
    }


class JudgmentSessionService:
    """One local first-answer -> probe -> transfer session per opaque run id.

    EventStore remains the primary append-only replay ledger.  LearnerStateStore
    receives only origin-matching facts and the independent transfer receipt.
    The class deliberately leaves HTTP routing to the sidecar layer so its
    state-machine tests can remain deterministic and no test needs to pretend
    to be a human learner.
    """

    def __init__(
        self,
        database: str | Path,
        *,
        reviewed_pack_root: str | Path,
        config: JudgmentSessionConfig | None = None,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self.database = str(database)
        self.config = config or JudgmentSessionConfig()
        self._today_provider = today_provider or date.today
        try:
            pack = load_reviewed_reasoning_pack(Path(reviewed_pack_root), projection="private")
        except (OSError, ReasoningPackError, ValueError) as exc:
            raise JudgmentContentUnavailable(
                "content_review_required: a reviewed, hash-bound judgement pack is required"
            ) from exc
        self.pack_id = str(pack["pack_id"])
        self.pack_version = str(pack["pack_version"])
        self._records = tuple(dict(record) for record in pack["records"])
        self._record_index = {str(record["record_id"]): record for record in self._records}
        if len(self._record_index) != len(self._records):
            raise JudgmentContentUnavailable("reviewed judgement pack has duplicate record ids")

    def close(self) -> None:
        """Compatibility no-op; stores are opened per local command."""

    def workspace(self) -> dict[str, Any]:
        entries = [
            self._public_record(record)
            for record in self._records
            if record.get("role") in {"entry_diagnostic", "routing_diagnostic"}
        ]
        if not entries:
            raise JudgmentContentUnavailable("reviewed judgement pack has no entry diagnostic")
        learner_store = LearnerStateStore(self.database)
        try:
            decisions = learner_store.replay_policy_decisions(
                namespace_id=self.config.namespace_id,
                evidence_origin=self.config.evidence_origin,
                learner_id=self.config.learner_id,
            )
            review_plan = [
                dict(decision["review_task"])
                for decision in decisions
                if decision.get("decision_type") == "schedule_review"
                and isinstance(decision.get("review_task"), Mapping)
            ]
            return {
                "schema_version": JUDGMENT_SESSION_SCHEMA,
                "available": True,
                "pack": {"pack_id": self.pack_id, "pack_version": self.pack_version},
                "entry_items": entries,
                "review_plan": review_plan,
                "next_step": "answer_entry",
                "privacy": "local_only",
            }
        finally:
            learner_store.close()

    def start(
        self,
        *,
        entry_record_id: str,
        selected_option: str,
        confidence: str,
        elapsed_seconds: float,
        rationale: str | None = None,
        command_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        entry = self._entry_assessment_record(entry_record_id)
        rationale = _optional_rationale(rationale)
        observation = EntryObservation(
            selected_option=selected_option,
            correct_option=str(entry["correct_option"]),
            confidence=confidence,  # type: ignore[arg-type]
            elapsed_seconds=elapsed_seconds,
            hint_count=0,
        )
        # First answer is a durable write.  A public command id lets a lost
        # response retry the *same* observation rather than create another.
        normalized_command_id = _command_id(command_id) if command_id is not None else None
        run_id = (
            _entry_session_id(self.config.namespace_id, self.config.learner_id, normalized_command_id)
            if session_id is None and normalized_command_id is not None
            else (_new_session_id() if session_id is None else _session_id(session_id))
        )
        store = EventStore(self.database)
        learner_store = LearnerStateStore(self.database)
        try:
            existing = store.events(run_id)
            if existing:
                if normalized_command_id is None:
                    raise JudgmentSessionConflict("session_id already exists")
                return self._replay_entry_command(
                    existing, normalized_command_id, entry_record_id, observation, rationale
                )
            history = self._historical_context(learner_store, entry)
            try:
                decision = diagnose_entry(
                    self._records,
                    entry_record_id=entry_record_id,
                    observation=observation,
                    historical_context=history,
                )
            except JudgmentPolicyError as exc:
                raise JudgmentSessionError(str(exc)) from exc
            stage = _entry_stage(decision)
            public = self._entry_projection(run_id, 1, entry, observation, decision, stage)
            try:
                event = store.append_if_version(
                    run_id,
                    0,
                    "judgment_entry_submitted",
                {
                    "schema_version": JUDGMENT_SESSION_SCHEMA,
                    "namespace_id": self.config.namespace_id,
                    "evidence_origin": self.config.evidence_origin,
                    "learner_id": self.config.learner_id,
                    "stage_after": stage,
                    "command_id": normalized_command_id,
                    "entry_record_id": entry_record_id,
                    "selected_option": observation.selected_option,
                    "correct": observation.is_correct,
                    "confidence": observation.confidence,
                    "elapsed_seconds": observation.elapsed_seconds,
                    "rationale": rationale,
                    "public_result": public,
                    },
                )
            except TraceVersionConflict as exc:
                if normalized_command_id is not None:
                    return self._replay_entry_command(
                        self._owned_events(store, run_id),
                        normalized_command_id,
                        entry_record_id,
                        observation,
                        rationale,
                    )
                raise JudgmentSessionConflict(
                    f"session_id already exists: actual version {exc.actual_version}"
                ) from exc
            self._append_entry_evidence(learner_store, event, entry, observation)
            self._append_entry_hypotheses(learner_store, decision, event)
            return public
        finally:
            learner_store.close()
            store.close()

    def answer_probe(
        self,
        *,
        session_id: str,
        expected_version: int,
        expected_stage: str,
        selected_option: str,
        confidence: str,
        elapsed_seconds: float,
        command_id: str,
    ) -> dict[str, Any]:
        run_id = _session_id(session_id)
        command_id = _command_id(command_id)
        store = EventStore(self.database)
        learner_store = LearnerStateStore(self.database)
        try:
            events = self._owned_events(store, run_id)
            replayed = self._replay_probe_command(events, command_id, selected_option, confidence, elapsed_seconds)
            if replayed is not None:
                return replayed
            entry_event = _require_event(events, "judgment_entry_submitted")
            self._assert_state(events, expected_version, expected_stage, "awaiting_probe")
            entry = self._entry_assessment_record(str(entry_event.payload["entry_record_id"]))
            observation = EntryObservation(
                selected_option=str(entry_event.payload["selected_option"]),
                correct_option=str(entry["correct_option"]),
                confidence=str(entry_event.payload["confidence"]),  # type: ignore[arg-type]
                elapsed_seconds=float(entry_event.payload["elapsed_seconds"]),
                hint_count=0,
            )
            history = self._historical_context(learner_store, entry)
            try:
                decision = diagnose_entry(
                    self._records,
                    entry_record_id=str(entry["record_id"]),
                    observation=observation,
                    historical_context=history,
                )
            except JudgmentPolicyError as exc:
                raise JudgmentSessionError(str(exc)) from exc
            try:
                resolution = resolve_probe(
                    self._records, decision=decision, selected_option=selected_option
                )
            except JudgmentPolicyError as exc:
                raise JudgmentSessionError(str(exc)) from exc
            probe = self._assessment_record(resolution.probe_record_id, role="probe")
            transfer = self._assessment_record(
                _required_transfer_id(resolution), role="independent_transfer"
            )
            selected = _option(selected_option)
            public = self._probe_projection(
                run_id, expected_version + 1, resolution, probe, transfer, selected
            )
            try:
                event = store.append_if_version(
                    run_id,
                    expected_version,
                    "judgment_probe_submitted",
                    {
                        "schema_version": JUDGMENT_SESSION_SCHEMA,
                        "namespace_id": self.config.namespace_id,
                        "evidence_origin": self.config.evidence_origin,
                        "learner_id": self.config.learner_id,
                        "stage_after": "awaiting_transfer",
                        "command_id": command_id,
                        "probe_record_id": str(probe["record_id"]),
                        "selected_option": selected,
                        "confidence": _confidence(confidence),
                        "elapsed_seconds": _elapsed(elapsed_seconds),
                        "public_result": public,
                    },
                )
            except TraceVersionConflict as exc:
                raise JudgmentSessionConflict(
                    f"stale session version: expected {exc.expected_version}, actual {exc.actual_version}"
                ) from exc
            self._append_probe_evidence(learner_store, event, probe, selected_option)
            self._append_probe_hypotheses(learner_store, resolution, event)
            return public
        finally:
            learner_store.close()
            store.close()

    def answer_transfer(
        self,
        *,
        session_id: str,
        expected_version: int,
        expected_stage: str,
        selected_option: str,
        confidence: str,
        elapsed_seconds: float,
        command_id: str,
    ) -> dict[str, Any]:
        run_id = _session_id(session_id)
        command_id = _command_id(command_id)
        store = EventStore(self.database)
        learner_store = LearnerStateStore(self.database)
        try:
            events = self._owned_events(store, run_id)
            replayed = self._replay_transfer_command(events, command_id, selected_option, confidence, elapsed_seconds)
            if replayed is not None:
                self._persist_review_decision_from_result(learner_store, run_id, events, replayed)
                return replayed
            if (
                events[-1].kind == "judgment_transfer_observed"
                and events[-1].payload.get("stage_after") == "committing_transfer"
            ):
                return self._resume_transfer_commit(
                    learner_store,
                    store,
                    run_id=run_id,
                    events=events,
                    command_id=command_id,
                    selected_option=selected_option,
                    confidence=confidence,
                    elapsed_seconds=elapsed_seconds,
                )
            self._assert_state(events, expected_version, expected_stage, "awaiting_transfer")
            entry_event = _require_event(events, "judgment_entry_submitted")
            probe_event = _require_event(events, "judgment_probe_submitted")
            transfer = self._assessment_record(
                str(probe_event.payload["public_result"]["transfer"]["record_id"]),
                role="independent_transfer",
            )
            selected = _option(selected_option)
            correct = selected == str(transfer["correct_option"])
            try:
                transfer_event = store.append_if_version(
                    run_id,
                    expected_version,
                    "judgment_transfer_observed",
                    {
                        "schema_version": JUDGMENT_SESSION_SCHEMA,
                        "namespace_id": self.config.namespace_id,
                        "evidence_origin": self.config.evidence_origin,
                        "learner_id": self.config.learner_id,
                        "stage_after": "committing_transfer",
                        "command_id": command_id,
                        "transfer_record_id": str(transfer["record_id"]),
                        "selected_option": selected,
                        "confidence": _confidence(confidence),
                        "elapsed_seconds": _elapsed(elapsed_seconds),
                        "correct": correct,
                        "review_base_day": self._today_provider().isoformat(),
                    },
                )
            except TraceVersionConflict as exc:
                raise JudgmentSessionConflict(
                    f"stale session version: expected {exc.expected_version}, actual {exc.actual_version}"
                ) from exc
            return self._finalize_transfer_commit(
                learner_store,
                store,
                run_id=run_id,
                events=[*events, transfer_event],
                transfer_event=transfer_event,
                transfer=transfer,
                selected_option=selected,
                correct=correct,
                confidence=_confidence(confidence),
                elapsed_seconds=_elapsed(elapsed_seconds),
                command_id=command_id,
            )
        finally:
            learner_store.close()
            store.close()

    def replay(self, session_id: str) -> dict[str, Any]:
        run_id = _session_id(session_id)
        store = EventStore(self.database)
        try:
            events = self._owned_events(store, run_id)
            if not store.verify(run_id):
                raise JudgmentSessionError("session trace verification failed")
            return {
                "schema_version": JUDGMENT_SESSION_SCHEMA,
                "session_id": run_id,
                "trace_verified": True,
                "event_count": len(events),
                "timeline": [
                    {
                        "seq": event.seq,
                        "kind": event.kind,
                        "occurred_at": event.occurred_at,
                        "stage_after": event.payload.get("stage_after"),
                        "result": event.payload.get("public_result"),
                    }
                    for event in events
                ],
            }
        finally:
            store.close()

    def _entry_projection(
        self,
        run_id: str,
        state_version: int,
        entry: Mapping[str, Any],
        observation: EntryObservation,
        decision: EntryPolicyDecision,
        stage: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": JUDGMENT_SESSION_SCHEMA,
            "session_id": run_id,
            "state_version": state_version,
            "stage": stage,
            "entry": {
                **self._public_record(entry),
                "selected_option": observation.selected_option,
                "correct": observation.is_correct,
                "confidence": observation.confidence,
                "elapsed_seconds": observation.elapsed_seconds,
            },
            "observed_facts": [
                {"fact_id": fact.fact_id, "kind": fact.kind, "value": fact.value, "evidence": fact.evidence}
                for fact in decision.facts
                if fact.kind in _LEARNER_VISIBLE_ENTRY_FACT_KINDS
            ],
            "candidate_causes": [
                {
                    "cause_id": candidate.cause_id,
                    "status": candidate.status,
                    "rank": candidate.rank,
                    "rationale": candidate.rationale,
                    "prior_probe_observations": _public_prior_observations(
                        candidate.cause_id, decision.historical_context
                    ),
                    "is_ground_truth": False,
                }
                for candidate in decision.candidate_causes
            ],
            "policy": {
                "policy_id": decision.policy_id,
                "policy_version": decision.policy_version,
                "calibration_status": decision.calibration_status,
                "why_selected": decision.probe_plan.why_selected,
                "candidate_actions": [
                    {
                        "record_id": action.record_id,
                        "coverage": list(action.coverage),
                        "selected": action.selected,
                        "why_selected": action.why_selected,
                        "why_not_selected": action.why_not_selected,
                    }
                    for action in decision.probe_plan.candidate_actions
                ],
            },
            "next_step": "answer_probe" if stage == "awaiting_probe" else "review_or_stop",
        }
        if decision.probe_plan.selected_probe_id:
            result["probe"] = self._public_record(
                self._assessment_record(decision.probe_plan.selected_probe_id, role="probe")
            )
        return result

    def _probe_projection(
        self,
        run_id: str,
        state_version: int,
        resolution: ProbeResolution,
        probe: Mapping[str, Any],
        transfer: Mapping[str, Any],
        selected_option: str,
    ) -> dict[str, Any]:
        teaching = (
            self._public_record(self._record_index[resolution.teaching_plan.selected_asset_id])
            if resolution.teaching_plan.selected_asset_id
            else None
        )
        return {
            "schema_version": JUDGMENT_SESSION_SCHEMA,
            "session_id": run_id,
            "state_version": state_version,
            "stage": "awaiting_transfer",
            "probe": {
                **self._public_record(probe),
                "selected_option": selected_option,
                "correct": selected_option == str(probe["correct_option"]),
                "evidence_updates": [
                    {"cause_id": update.cause_id, "outcome": update.outcome, "status": update.status, "evidence": update.evidence}
                    for update in resolution.evidence_updates
                ],
            },
            "teaching": {
                "asset": teaching,
                "target_cause_id": resolution.teaching_plan.target_cause_id,
                "why_selected": resolution.teaching_plan.why_selected,
                "history_used_for_tie_break": resolution.teaching_plan.history_used_for_tie_break,
            },
            "transfer": self._public_record(transfer),
            "independence": {
                "requires_no_hints": True,
                "distinct_from": [str(probe["record_id"])],
            },
            "next_step": "answer_transfer",
        }

    def _append_entry_evidence(
        self, learner_store: LearnerStateStore, event: TraceEvent, record: Mapping[str, Any], observation: EntryObservation
    ) -> None:
        learner_store.append_evidence(
            self._evidence(
                event,
                event_id=f"evt_{event.run_id}_entry",
                kind="attempt",
                record=record,
                observed={
                    "selected_option": observation.selected_option,
                    "correct": observation.is_correct,
                    "confidence": observation.confidence,
                    "response_time_seconds": observation.elapsed_seconds,
                    "hint_count": 0,
                    "independently_answered": True,
                    "attempt_ordinal": 1,
                },
            )
        )

    def _historical_context(
        self, learner_store: LearnerStateStore, entry: Mapping[str, Any]
    ) -> tuple[HistoricalCandidateEvidence, ...]:
        """Summarise only this learner's earlier probe observations.

        The result is intentionally not a probability or an updated cause
        label.  It excludes other packs, other origins, unbound legacy rows,
        and current-entry hypotheses.  The policy may consume it only as a
        tie-break after current discriminating evidence supports alternatives.
        """

        targets = set(entry.get("candidate_misconception_ids", []))
        counts: dict[str, dict[str, int]] = {
            cause_id: {"supported": 0, "refuted": 0, "insufficient": 0}
            for cause_id in targets
            if isinstance(cause_id, str)
        }
        for hypothesis in learner_store.replay_hypotheses(
            namespace_id=self.config.namespace_id,
            evidence_origin=self.config.evidence_origin,
            learner_id=self.config.learner_id,
        ):
            if (
                hypothesis.get("pack_id") != self.pack_id
                or hypothesis.get("pack_version") != self.pack_version
            ):
                continue
            cause_id = hypothesis.get("cause_id")
            status = hypothesis.get("status")
            if cause_id not in counts or status not in counts[cause_id]:
                continue
            counts[cause_id][str(status)] += 1
        return tuple(
            HistoricalCandidateEvidence(
                cause_id=cause_id,
                supported_count=counts[cause_id]["supported"],
                refuted_count=counts[cause_id]["refuted"],
                insufficient_count=counts[cause_id]["insufficient"],
            )
            for cause_id in sorted(counts)
            if any(counts[cause_id].values())
        )

    def _append_entry_hypotheses(self, learner_store: LearnerStateStore, decision: EntryPolicyDecision, event: TraceEvent) -> None:
        for candidate in decision.candidate_causes:
            learner_store.append_hypothesis(
                {
                    "schema_version": "lumi.diagnosis-hypothesis.v1",
                    "hypothesis_id": f"dxh_{event.run_id}_{candidate.cause_id}_entry",
                    "namespace_id": self.config.namespace_id,
                    "evidence_origin": self.config.evidence_origin,
                    "episode_id": f"episode_{event.run_id}",
                    "skill_id": self._skill_for_cause(candidate.cause_id),
                    "learner_id": self.config.learner_id,
                    "pack_id": self.pack_id,
                    "pack_version": self.pack_version,
                    "cause_id": candidate.cause_id,
                    "status": "unconfirmed",
                    "evidence_refs": [f"evt_{event.run_id}_entry"],
                    "model": {"name": decision.policy_id, "version": decision.policy_version},
                }
            )

    def _append_probe_evidence(self, learner_store: LearnerStateStore, event: TraceEvent, record: Mapping[str, Any], selected_option: str) -> None:
        correct = _option(selected_option) == str(record["correct_option"])
        learner_store.append_evidence(
            self._evidence(
                event,
                event_id=f"evt_{event.run_id}_probe",
                kind="probe_response",
                record=record,
                observed={
                    "selected_option": _option(selected_option),
                    "correct": correct,
                    "hint_count": 0,
                    "independently_answered": True,
                    "attempt_ordinal": 2,
                },
            )
        )

    def _append_probe_hypotheses(self, learner_store: LearnerStateStore, resolution: ProbeResolution, event: TraceEvent) -> None:
        for update in resolution.evidence_updates:
            learner_store.append_hypothesis(
                {
                    "schema_version": "lumi.diagnosis-hypothesis.v1",
                    "hypothesis_id": f"dxh_{event.run_id}_{update.cause_id}_probe",
                    "namespace_id": self.config.namespace_id,
                    "evidence_origin": self.config.evidence_origin,
                    "episode_id": f"episode_{event.run_id}",
                    "skill_id": self._skill_for_cause(update.cause_id),
                    "learner_id": self.config.learner_id,
                    "pack_id": self.pack_id,
                    "pack_version": self.pack_version,
                    "cause_id": update.cause_id,
                    "status": "supported" if update.outcome == "support" else "refuted" if update.outcome == "refute" else "insufficient",
                    "evidence_refs": [f"evt_{event.run_id}_probe"],
                    "model": {"name": resolution.policy_id, "version": resolution.policy_version},
                }
            )

    def _resume_transfer_commit(
        self,
        learner_store: LearnerStateStore,
        store: EventStore,
        *,
        run_id: str,
        events: list[TraceEvent],
        command_id: str,
        selected_option: str,
        confidence: str,
        elapsed_seconds: float,
    ) -> dict[str, Any]:
        """Finish a transfer whose observation was durably appended before a crash."""

        transfer_event = events[-1]
        selected = _option(selected_option)
        normalized_confidence = _confidence(confidence)
        normalized_elapsed = _elapsed(elapsed_seconds)
        if (
            transfer_event.payload.get("command_id") != command_id
            or transfer_event.payload.get("selected_option") != selected
            or transfer_event.payload.get("confidence") != normalized_confidence
            or transfer_event.payload.get("elapsed_seconds") != normalized_elapsed
        ):
            raise JudgmentSessionConflict("committing transfer belongs to a different command")
        transfer = self._assessment_record(
            _short_public_id(transfer_event.payload.get("transfer_record_id"), "transfer record id"),
            role="independent_transfer",
        )
        correct = selected == str(transfer["correct_option"])
        if transfer_event.payload.get("correct") is not correct:
            raise JudgmentSessionError("committing transfer scorer outcome is inconsistent")
        return self._finalize_transfer_commit(
            learner_store,
            store,
            run_id=run_id,
            events=events,
            transfer_event=transfer_event,
            transfer=transfer,
            selected_option=selected,
            correct=correct,
            confidence=normalized_confidence,
            elapsed_seconds=normalized_elapsed,
            command_id=command_id,
        )

    def _finalize_transfer_commit(
        self,
        learner_store: LearnerStateStore,
        store: EventStore,
        *,
        run_id: str,
        events: list[TraceEvent],
        transfer_event: TraceEvent,
        transfer: Mapping[str, Any],
        selected_option: str,
        correct: bool,
        confidence: str,
        elapsed_seconds: float,
        command_id: str,
    ) -> dict[str, Any]:
        entry_event = _require_event(events, "judgment_entry_submitted")
        probe_event = _require_event(events, "judgment_probe_submitted")
        receipts = self._commit_transfer(
            learner_store,
            run_id=run_id,
            transfer_event=transfer_event,
            transfer=transfer,
            selected_option=selected_option,
            correct=correct,
            confidence=confidence,
            elapsed_seconds=elapsed_seconds,
            entry_event=entry_event,
            probe_event=probe_event,
        )
        review_task = self._review_task(
            run_id,
            transfer,
            "passed" if correct else "failed",
            receipts,
            base_day=_review_base_day(transfer_event.payload.get("review_base_day")),
        )
        public = {
            "schema_version": JUDGMENT_SESSION_SCHEMA,
            "session_id": run_id,
            "state_version": transfer_event.seq + 1,
            "stage": "completed",
            "transfer": {
                **self._public_record(transfer),
                "selected_option": selected_option,
                "correct": correct,
            },
            "state_receipts": receipts,
            "review_task": review_task,
            "next_step": "delayed_review" if correct else "independent_retry",
        }
        try:
            store.append_if_version(
                run_id,
                transfer_event.seq,
                "judgment_transfer_receipt",
                {
                    "schema_version": JUDGMENT_SESSION_SCHEMA,
                    "namespace_id": self.config.namespace_id,
                    "evidence_origin": self.config.evidence_origin,
                    "learner_id": self.config.learner_id,
                    "stage_after": "completed",
                    "command_id": command_id,
                    "transfer_record_id": str(transfer["record_id"]),
                    "selected_option": selected_option,
                    "confidence": confidence,
                    "elapsed_seconds": elapsed_seconds,
                    "correct": correct,
                    "public_result": public,
                },
            )
        except TraceVersionConflict as exc:
            replayed = self._replay_transfer_command(
                self._owned_events(store, run_id), command_id, selected_option, confidence, elapsed_seconds
            )
            if replayed is not None:
                self._persist_review_decision_from_result(
                    learner_store, run_id, self._owned_events(store, run_id), replayed
                )
                return replayed
            raise JudgmentSessionConflict(
                f"transfer receipt version conflict: expected {exc.expected_version}, actual {exc.actual_version}"
            ) from exc
        self._persist_review_decision(
            learner_store, run_id=run_id, transfer_event=transfer_event, review_task=review_task
        )
        return public

    def _commit_transfer(
        self,
        learner_store: LearnerStateStore,
        *,
        run_id: str,
        transfer_event: TraceEvent,
        transfer: Mapping[str, Any],
        selected_option: str,
        correct: bool,
        confidence: str,
        elapsed_seconds: float,
        entry_event: TraceEvent,
        probe_event: TraceEvent,
    ) -> list[dict[str, Any]]:
        event_id = f"evt_{run_id}_transfer"
        learner_store.append_evidence(
            self._evidence(
                transfer_event,
                event_id=event_id,
                kind="verification",
                record=transfer,
                observed={
                    "selected_option": selected_option,
                    "correct": correct,
                    "confidence": confidence,
                    "response_time_seconds": elapsed_seconds,
                    "hint_count": 0,
                    "independently_answered": True,
                    "attempt_ordinal": 3,
                },
            )
        )
        excluded = [
            _content_signature(self._entry_assessment_record(str(entry_event.payload["entry_record_id"]))),
            _content_signature(self._assessment_record(str(probe_event.payload["probe_record_id"]), role="probe")),
        ]
        receipts: list[dict[str, Any]] = []
        for ordinal, skill_id in enumerate(transfer["target_skill_ids"], start=1):
            verification_id = f"vr_{_digest(f'{run_id}:{skill_id}:{ordinal}') }"
            current = learner_store.current_snapshot(
                namespace_id=self.config.namespace_id,
                evidence_origin=self.config.evidence_origin,
                learner_id=self.config.learner_id,
                skill_id=str(skill_id),
            )
            try:
                receipt = learner_store.commit_verification(
                    namespace_id=self.config.namespace_id,
                    evidence_origin=self.config.evidence_origin,
                    learner_id=self.config.learner_id,
                    skill_id=str(skill_id),
                    verification_id=verification_id,
                    evidence_event_id=event_id,
                    expected_state_version=int(current["state_version"]) if current else 0,
                    outcome="passed" if correct else "failed",
                    unseen_from_content_signatures=excluded,
                )
            except (LearnerStateError, LearnerStateVersionConflict) as exc:
                raise JudgmentSessionError(f"learner-state commit rejected: {exc}") from exc
            receipts.append(_public_receipt(receipt))
        return receipts

    def _review_task(
        self,
        run_id: str,
        transfer: Mapping[str, Any],
        outcome: str,
        receipts: list[dict[str, Any]],
        *,
        base_day: date | None = None,
    ) -> dict[str, Any]:
        passed = outcome == "passed" and all(
            receipt["state_delta"]["commit_status"] == "committed" for receipt in receipts
        )
        review_record = self._review_record_for_transfer(str(transfer["record_id"]))
        offset = 3 if passed else 1
        task_kind = "delayed_retention" if passed else "independent_retry"
        return {
            "task_id": "jrt_" + _digest(f"{run_id}:{task_kind}"),
            "kind": task_kind,
            "due_on": ((base_day or self._today_provider()) + timedelta(days=offset)).isoformat(),
            "source_session_id": run_id,
            "evidence_origin": self.config.evidence_origin,
            "namespace_id": self.config.namespace_id,
            "item_selector": {
                "pack_id": self.pack_id,
                "role": "delayed_review",
                "record_id": str(review_record["record_id"]),
                "excludes_content_signatures": [_content_signature(transfer)],
            },
            "success_criterion": "无提示、独立、可确定评分的作答",
            "skip_consequence": "学习状态保持证据有限；不会自动提高掌握状态。",
            "policy": {"version": "judgment-review-policy.v1", "calibration_status": "engineering_unvalidated"},
        }

    def _persist_review_decision(
        self,
        learner_store: LearnerStateStore,
        *,
        run_id: str,
        transfer_event: TraceEvent,
        review_task: Mapping[str, Any],
    ) -> None:
        task_id = _short_public_id(review_task.get("task_id"), "review task id")
        learner_store.append_policy_decision(
            {
                "schema_version": "lumi.policy-decision.v1",
                "decision_id": "pd_review_" + _digest(f"{run_id}:{task_id}"),
                "namespace_id": self.config.namespace_id,
                "evidence_origin": self.config.evidence_origin,
                "learner_id": self.config.learner_id,
                "episode_id": f"episode_{run_id}",
                "decision_type": "schedule_review",
                "selected_action_id": task_id,
                "evidence_refs": [f"evt_{run_id}_transfer"],
                "review_task": dict(review_task),
                "policy": {"version": "judgment-review-policy.v1", "source_trace_seq": transfer_event.seq},
            }
        )

    def _persist_review_decision_from_result(
        self,
        learner_store: LearnerStateStore,
        run_id: str,
        events: list[TraceEvent],
        public_result: Mapping[str, Any],
    ) -> None:
        task = public_result.get("review_task")
        if not isinstance(task, Mapping):
            raise JudgmentSessionError("completed transfer replay has no review task")
        transfer_event = _require_event(events, "judgment_transfer_observed")
        self._persist_review_decision(
            learner_store,
            run_id=run_id,
            transfer_event=transfer_event,
            review_task=task,
        )

    def _review_record_for_transfer(self, transfer_id: str) -> Mapping[str, Any]:
        candidates = [
            record for record in self._records
            if record.get("role") == "delayed_review" and transfer_id in record.get("eligible_after_transfer_ids", [])
        ]
        if not candidates:
            raise JudgmentSessionError("reviewed pack has no delayed review bound to transfer")
        return sorted(candidates, key=lambda record: str(record["record_id"]))[0]

    def _evidence(self, event: TraceEvent, *, event_id: str, kind: str, record: Mapping[str, Any], observed: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "lumi.evidence-event.v1",
            "event_id": event_id,
            "namespace_id": self.config.namespace_id,
            "evidence_origin": self.config.evidence_origin,
            "run_id": event.run_id,
            "trace_ref": {"run_id": event.run_id, "seq": event.seq, "event_hash": event.event_hash},
            "kind": kind,
            "content_ref": {
                "pack_id": self.pack_id,
                "pack_version": self.pack_version,
                "item_id": str(record["record_id"]),
                "content_signature": _content_signature(record),
                "role": _evidence_role(record),
            },
            "observed": dict(observed),
            "producer": {"kind": "deterministic_scorer", "version": "judgment-mcq-v1"},
        }

    def _owned_events(self, store: EventStore, run_id: str) -> list[TraceEvent]:
        events = store.events(run_id)
        return self._owned_events_from(events)

    def _owned_events_from(self, events: list[TraceEvent]) -> list[TraceEvent]:
        if not events:
            raise JudgmentSessionError("judgment session is unavailable")
        for event in events:
            if event.payload.get("namespace_id") != self.config.namespace_id or event.payload.get("evidence_origin") != self.config.evidence_origin:
                raise JudgmentSessionError("session belongs to a different evidence namespace")
        return events

    def _assert_state(self, events: list[TraceEvent], expected_version: int, expected_stage: str, stage: str) -> None:
        if not isinstance(expected_version, int) or expected_version < 1:
            raise JudgmentSessionConflict("expected_version must be a positive integer")
        actual_version = events[-1].seq
        actual_stage = events[-1].payload.get("stage_after")
        if expected_version != actual_version or expected_stage != actual_stage or actual_stage != stage:
            raise JudgmentSessionConflict(
                f"stale or out-of-order session command: expected {expected_version}/{expected_stage}, actual {actual_version}/{actual_stage}"
            )

    def _replay_probe_command(self, events: list[TraceEvent], command_id: str, selected: str, confidence: str, elapsed: float) -> dict[str, Any] | None:
        return self._replay_command(events, "judgment_probe_submitted", command_id, selected, confidence, elapsed)

    def _replay_entry_command(
        self,
        events: list[TraceEvent],
        command_id: str,
        entry_record_id: str,
        observation: EntryObservation,
        rationale: str | None,
    ) -> dict[str, Any]:
        owned = self._owned_events_from(events)
        entry = _require_event(owned, "judgment_entry_submitted")
        if (
            entry.payload.get("command_id") != command_id
            or entry.payload.get("entry_record_id") != entry_record_id
            or entry.payload.get("selected_option") != observation.selected_option
            or entry.payload.get("confidence") != observation.confidence
            or entry.payload.get("elapsed_seconds") != observation.elapsed_seconds
            or entry.payload.get("rationale") != rationale
        ):
            raise JudgmentSessionConflict("command_id is already bound to a different first answer")
        result = entry.payload.get("public_result")
        if not isinstance(result, dict):
            raise JudgmentSessionError("idempotent first-answer command has no public receipt")
        return result

    def _replay_transfer_command(self, events: list[TraceEvent], command_id: str, selected: str, confidence: str, elapsed: float) -> dict[str, Any] | None:
        return self._replay_command(events, "judgment_transfer_receipt", command_id, selected, confidence, elapsed)

    def _replay_command(self, events: list[TraceEvent], kind: str, command_id: str, selected: str, confidence: str, elapsed: float) -> dict[str, Any] | None:
        for event in events:
            if event.kind != kind or event.payload.get("command_id") != command_id:
                continue
            if (
                event.payload.get("selected_option") != _option(selected)
                or event.payload.get("confidence") != _confidence(confidence)
                or event.payload.get("elapsed_seconds") != _elapsed(elapsed)
            ):
                raise JudgmentSessionConflict("command_id is already bound to a different response")
            result = event.payload.get("public_result")
            if not isinstance(result, dict):
                raise JudgmentSessionError("idempotent session command has no public receipt")
            return result
        return None

    def _assessment_record(self, record_id: str, *, role: str) -> Mapping[str, Any]:
        record = self._record_index.get(record_id)
        if record is None or record.get("role") != role:
            raise JudgmentSessionError(f"reviewed pack has no {role} record {record_id}")
        return record

    def _entry_assessment_record(self, record_id: str) -> Mapping[str, Any]:
        record = self._record_index.get(record_id)
        if record is None or record.get("role") not in {"entry_diagnostic", "routing_diagnostic"}:
            raise JudgmentSessionError(f"reviewed pack has no entry diagnostic {record_id}")
        return record

    def _public_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        allowed = _PUBLIC_TEACHING_FIELDS if record.get("role") == "teaching_asset" else _PUBLIC_ASSESSMENT_FIELDS
        projected = {key: record[key] for key in allowed if key in record}
        forbidden = {"correct_option", "answer_proof", "distractor_map", "selected_when", "formalization"}
        if forbidden.intersection(projected):
            raise JudgmentSessionError("unsafe public judgement record projection")
        return projected

    def _skill_for_cause(self, cause_id: str) -> str:
        mapping = {
            "M-DIR": "xingce.judgment.conditional.language_direction",
            "M-ROLE": "xingce.judgment.conditional.necessary_sufficient_role",
            "M-INF": "xingce.judgment.conditional.inference_validity",
            "M-READ": "xingce.judgment.conditional.language_direction",
        }
        return mapping.get(cause_id, "xingce.judgment.conditional.language_direction")


def _entry_stage(decision: EntryPolicyDecision) -> str:
    if decision.next_action == "probe":
        return "awaiting_probe"
    if decision.next_action == "retention_or_abstain":
        return "completed_no_error"
    return "blocked_insufficient_evidence"


def _public_prior_observations(
    cause_id: str, history: tuple[HistoricalCandidateEvidence, ...]
) -> dict[str, Any]:
    prior = next((item for item in history if item.cause_id == cause_id), None)
    if prior is None:
        return {
            "supported_count": 0,
            "refuted_count": 0,
            "insufficient_count": 0,
            "usage": "没有可用的既往探查观察；本轮只依据当前作答。",
        }
    return {
        "supported_count": prior.supported_count,
        "refuted_count": prior.refuted_count,
        "insufficient_count": prior.insufficient_count,
        "usage": "既往观察只可在当前探查也支持多个候选时排序微课；不能单独触发教学、确认错因或更新学习状态。",
    }


def _new_session_id() -> str:
    return "jr_" + secrets.token_hex(18)


def _entry_session_id(namespace_id: str, learner_id: str, command_id: str) -> str:
    scope = f"{namespace_id}\x1f{learner_id}\x1f{command_id}".encode("utf-8")
    return "jr_" + hashlib.sha256(scope).hexdigest()[:36]


def _session_id(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("jr_") or len(value) < 12 or len(value) > 100:
        raise JudgmentSessionError("session_id is invalid")
    return value


def _command_id(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("c_") or len(value) < 10 or len(value) > 160:
        raise JudgmentSessionError("command_id is invalid")
    return value


def _short_public_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 240:
        raise JudgmentSessionError(f"{label} is invalid")
    return value.strip()


def _review_base_day(value: Any) -> date:
    if not isinstance(value, str):
        raise JudgmentSessionError("committing transfer lacks its local review date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise JudgmentSessionError("committing transfer has an invalid local review date") from exc


def _option(value: str) -> str:
    if not isinstance(value, str) or value.strip().upper() not in {"A", "B", "C", "D"}:
        raise JudgmentSessionError("selected_option must be A, B, C, or D")
    return value.strip().upper()


def _confidence(value: str) -> str:
    if not isinstance(value, str) or value.strip().lower() not in {"low", "medium", "high"}:
        raise JudgmentSessionError("confidence must be low, medium, or high")
    return value.strip().lower()


def _elapsed(value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise JudgmentSessionError("elapsed_seconds must be non-negative")
    return float(value)


def _optional_rationale(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 1200:
        raise JudgmentSessionError("rationale must be a string up to 1200 characters")
    return value.strip() or None


def _content_signature(record: Mapping[str, Any]) -> str:
    return "sha256:" + str(record["record_sha256"])


def _evidence_role(record: Mapping[str, Any]) -> str:
    role = str(record["role"])
    return {
        "entry_diagnostic": "diagnostic_first",
        "routing_diagnostic": "diagnostic_first",
        "probe": "probe",
        "independent_transfer": "transfer",
        "delayed_review": "delayed_review",
    }.get(role, role)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _require_event(events: list[TraceEvent], kind: str) -> TraceEvent:
    for event in events:
        if event.kind == kind:
            return event
    raise JudgmentSessionError(f"judgment session is missing {kind}")


def _required_transfer_id(resolution: ProbeResolution) -> str:
    if resolution.transfer_plan.selected_transfer_id is None:
        raise JudgmentSessionError("policy abstained from transfer; session must not continue")
    return resolution.transfer_plan.selected_transfer_id


def _public_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "skill_id": receipt["skill_id"],
        "state_version": receipt["state_version"],
        "mastery": receipt["mastery"],
        "state_delta": receipt["state_delta"],
        "verification": {
            "outcome": receipt["verification"]["outcome"],
            "state_update_eligibility": receipt["verification"]["state_update_eligibility"],
            "withheld_reason": receipt["verification"]["withheld_reason"],
        },
    }
