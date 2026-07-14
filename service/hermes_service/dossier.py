from __future__ import annotations

from typing import Any, Mapping

from hermes_runtime.store import EventStore, TraceEvent


DOSSIER_PROJECTION_VERSION = "misconception-dossier-projection.v1"


def project_misconception_dossier(
    store: EventStore,
    run_id: str,
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    events = store.events(run_id)
    if not events:
        raise KeyError(run_id)
    if not store.verify(run_id):
        raise ValueError("trace hash verification failed")
    state = store.load_state(run_id)
    observe_event = _phase_event(events, "observe")
    diagnose_event = _phase_event(events, "diagnose")
    probe_event = _latest_kind(events, "probe_assessed")
    verify_event = _phase_event(events, "verify")
    update_event = _phase_event(events, "update")
    reflect_event = _phase_event(events, "reflect")

    observe = observe_event.payload.get("output", {}) if observe_event else {}
    diagnosis = diagnose_event.payload.get("output", {}) if diagnose_event else {}
    score = observe.get("score", {})
    direct_by_cause = {
        str(item.get("cause_id")): item
        for item in score.get("cause_candidates", [])
        if isinstance(item, dict) and isinstance(item.get("cause_id"), str)
    }
    assessed_by_cause = {
        str(item.get("cause_id")): item
        for item in (probe_event.payload.get("assessments", []) if probe_event else [])
        if isinstance(item, dict) and isinstance(item.get("cause_id"), str)
    }
    authored_causes = {
        str(item["cause_id"]): item for item in fixture["diagnosis"]["candidate_causes"]
    }
    ranked = diagnosis.get("diagnosis", {}).get("hypotheses", [])
    hypotheses = []
    for rank, hypothesis in enumerate(ranked, start=1):
        cause_id = str(hypothesis["cause_id"])
        authored = authored_causes.get(cause_id, {})
        direct = direct_by_cause.get(cause_id)
        assessment = assessed_by_cause.get(cause_id)
        supporting: list[dict[str, Any]] = []
        refuting: list[dict[str, Any]] = []
        direct_evidence_ids = list(direct.get("evidence_ids", [])) if direct else []
        specific_evidence_ids = [
            evidence_id
            for evidence_id in direct_evidence_ids
            if evidence_id != "answer_incorrect"
        ]
        if specific_evidence_ids and observe_event:
            supporting.append(
                {
                    "kind": "initial_response_pattern",
                    "evidence_ids": specific_evidence_ids,
                    "event": _event_ref(observe_event),
                    "semantics": "supports ranking only; does not confirm cause",
                }
            )
        claim_status = "unconfirmed_hypothesis"
        if assessment:
            claim_status = str(assessment.get("claim_status", claim_status))
            evidence_ref = {
                "kind": "targeted_probe_assessment",
                "diagnostic_evidence_weight": assessment.get("diagnostic_evidence_weight"),
                "source_response_event": assessment.get("source_response_event"),
                "assessment_event": _event_ref(probe_event),
                "semantics": "authored deterministic probe evidence; not causal ground truth",
            }
            if assessment.get("evidence_direction") == "supports":
                supporting.append(evidence_ref)
            elif assessment.get("evidence_direction") == "refutes":
                refuting.append(evidence_ref)
        hypotheses.append(
            {
                "rank": rank,
                "cause_id": cause_id,
                "label": authored.get("label", cause_id),
                "claim_status": claim_status,
                "ranking_probability": hypothesis.get("probability"),
                "probability_semantics": "relative_hypothesis_rank_not_population_error_rate",
                "supporting_evidence": supporting,
                "refuting_evidence": refuting,
                "ranking_factors": list(hypothesis.get("evidence", [])),
                "prior": {
                    "kind": "engineering_prior",
                    "source_version": fixture["provenance"].get("prior_source", "unknown"),
                    "sample_size": 0,
                    "population_calibrated": False,
                },
            }
        )

    verification = verify_event.payload.get("output", {}).get("verification") if verify_event else None
    learning_status = _learning_status(state, verification)
    if score.get("passed") is True and not ranked and verification is None:
        learning_status = "no_misconception_observed"
    assistance = [
        {
            "phase": event.payload.get("phase"),
            "prompt_instance_id": event.payload.get("prompt_instance_id"),
            "ordinal": event.payload.get("ordinal"),
            "action": event.payload.get("action"),
            "title": event.payload.get("title"),
            "diagnostic_evidence_weight": event.payload.get("diagnostic_evidence_weight"),
            "policy_version": event.payload.get("policy_version"),
            "event": _event_ref(event),
        }
        for event in events
        if event.kind == "assistance_delivered"
    ]
    return {
        "schema_version": "hermes.misconception-dossier.v1",
        "projection_version": DOSSIER_PROJECTION_VERSION,
        "dossier_id": run_id,
        "run_id": run_id,
        "fixture_id": fixture["fixture_id"],
        "domain": fixture["domain"],
        "module": fixture["module"],
        "skills": list(fixture["skills"]),
        "state": _attempt_state_name(state),
        "learning_status": learning_status,
        "observations": {
            "score": {
                "score": score.get("score"),
                "max_score": score.get("max_score"),
                "passed": score.get("passed"),
            },
            "items": list(score.get("observations", [])),
            "event": _event_ref(observe_event),
        },
        "hypothesis_semantics": "ranked_candidates_never_causal_ground_truth",
        "hypotheses": hypotheses,
        "uncertainty": diagnosis.get("diagnosis", {}).get("uncertainty"),
        "probe": {
            "prompt": fixture["probe"]["prompt"],
            "targets": list(fixture["probe"].get("targets", [])),
            "assessment_status": (
                "assessed" if probe_event and probe_event.payload.get("authored_rubric_available") else "not_assessed"
            ),
            "event": _event_ref(probe_event),
        },
        "assistance_history": assistance,
        "resolution": {
            "status": learning_status,
            "independently_verified": verification.get("independently_verified") if verification else False,
            "effective": verification.get("effective") if verification else None,
            "verification_event": _event_ref(verify_event),
            "update_event": _event_ref(update_event),
            "reflection_event": _event_ref(reflect_event),
            "note": "Learning resolution does not retroactively confirm the original cause.",
        },
        "next_action": _next_action(state, reflect_event),
        "cohort_evidence": {
            "status": "unavailable",
            "sample_size": 0,
            "reason": "No consented cohort evidence passed the privacy and minimum-sample gate.",
            "display_policy": "Do not show peer error rates or 'most learners' claims.",
        },
        "provenance": {
            "trace_verified": True,
            "source_trace_version": events[-1].seq,
            "source_event_hash": events[-1].event_hash,
            "fixture_content_sha256": state.context.get("fixture_content_sha256"),
        },
        "links": {
            "trace": f"/v1/runs/{run_id}/trace",
            "replay": f"/v1/runs/{run_id}/replay",
        },
    }


def _phase_event(events: list[TraceEvent], phase: str) -> TraceEvent | None:
    return next(
        (
            event
            for event in reversed(events)
            if event.kind == "phase_completed" and event.payload.get("phase") == phase
        ),
        None,
    )


def _latest_kind(events: list[TraceEvent], kind: str) -> TraceEvent | None:
    return next((event for event in reversed(events) if event.kind == kind), None)


def _event_ref(event: TraceEvent | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {"seq": event.seq, "kind": event.kind, "event_hash": event.event_hash}


def _attempt_state_name(state: Any) -> str:
    if state.status.value == "interrupted" and state.phase.value == "teach":
        if f"{state.run_id}:probe:1" in state.context.get("consumed_prompt_instances", []):
            return "processing_probe"
        return "awaiting_probe"
    if state.status.value == "interrupted" and state.phase.value == "verify":
        if f"{state.run_id}:verification:1" in state.context.get(
            "consumed_prompt_instances", []
        ):
            return "processing_verification"
        return "awaiting_verification"
    return state.status.value if state.status.value != "completed" else "completed"


def _learning_status(state: Any, verification: Mapping[str, Any] | None) -> str:
    state_name = _attempt_state_name(state)
    if state_name == "processing_probe":
        return "processing_probe_response"
    if state_name == "processing_verification":
        return "processing_verification_response"
    if not verification:
        return "awaiting_probe" if state.phase.value == "teach" else "awaiting_independent_verification"
    if verification.get("effective") is True:
        return "remediated_by_independent_transfer"
    if verification.get("effective") is False:
        return "needs_targeted_retry"
    return "inconclusive_needs_fresh_independent_verification"


def _next_action(state: Any, reflect_event: TraceEvent | None) -> dict[str, Any]:
    if reflect_event:
        output = reflect_event.payload.get("output", {})
        return {"action": output.get("next_action"), "event": _event_ref(reflect_event)}
    state_name = _attempt_state_name(state)
    if state_name == "processing_probe":
        return {
            "action": "restart_attempt_after_processing_failure",
            "target": "/v1/attempts",
            "reason": "The prior probe response was consumed but processing did not finish.",
        }
    if state_name == "processing_verification":
        return {
            "action": "restart_attempt_for_fresh_independent_verification",
            "target": "/v1/attempts",
            "reason": "The prior verification response was consumed but processing did not finish.",
        }
    if state.phase.value == "teach":
        return {"action": "answer_targeted_probe", "prompt_instance_id": f"{state.run_id}:probe:1"}
    if state.phase.value == "verify":
        return {"action": "answer_independent_verification", "prompt_instance_id": f"{state.run_id}:verification:1"}
    return {"action": "review_completed_attempt"}
