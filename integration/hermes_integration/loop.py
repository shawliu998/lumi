from __future__ import annotations

import json
import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from hermes_domains.adapters import score_attempt, score_verification_response
from hermes_domains.contract import validate_fixture
from hermes_kt.tool_api import HermesKTTool
from hermes_runtime.diff import state_diff
from hermes_runtime.machine import AgentRuntime, RunResult
from hermes_runtime.models import DeterministicProvider, ModelRouter
from hermes_runtime.state import AgentState, Phase, RunStatus
from hermes_runtime.store import EventStore, TraceVersionConflict
from hermes_runtime.tools import ToolContext, ToolRegistry, ToolSpec

from .learning_support import (
    assess_probe_response,
    assistance_events_for_prompt,
    fixture_content_hash,
    prompt_instance_id,
)


POLICY_VERSION = "integration-learning-policy-v1"
NO_ERROR_MODEL_VERSION = "deterministic-no-error-gate-v1"
MASTERY_MODEL_VERSION = "bkt-pfa-rasch-ensemble-v1"
VERIFY_MODEL_VERSION = "independent-transfer-check-v1"
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "domains" / "fixtures"


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    initial_response: str
    probe_response: str | None
    verification_response: str | None
    independently_answered: bool = True
    verification_hints: int = 0
    verification_evidence_weight: float = 1.0
    response_time_seconds: float = 60.0
    confidence: float = 0.65
    learner_history: Mapping[str, float] = field(default_factory=dict)
    execution_mode: str = "local"
    initial_observed_at: str = "2026-07-11T00:00:00+00:00"
    verification_observed_at: str = "2026-07-11T00:05:00+00:00"


SCENARIOS: dict[str, Scenario] = {
    "success": Scenario(
        name="success",
        initial_response="A",
        probe_response="增长率的分母应是基期量。",
        verification_response="C",
        confidence=0.82,
        learner_history={"denominator-current-base-confusion": 2.0},
    ),
    "ambiguous": Scenario(
        name="ambiguous",
        initial_response="X",
        probe_response="我不确定分母和是否减一。",
        verification_response="A",
        confidence=0.30,
        learner_history={},
    ),
    "offline": Scenario(
        name="offline",
        initial_response="D",
        probe_response="现期除以基期后还要减一。",
        verification_response="C",
        confidence=0.74,
        learner_history={"ratio-growth-confusion": 1.0},
        execution_mode="offline",
    ),
}


def load_fixture(relative_path: str = "xingce/data_analysis_growth.json") -> dict[str, Any]:
    path = (FIXTURE_ROOT / relative_path).resolve()
    if FIXTURE_ROOT.resolve() not in path.parents:
        raise ValueError("fixture must remain under domains/fixtures")
    fixture = json.loads(path.read_text(encoding="utf-8"))
    validate_fixture(fixture)
    return fixture


class IntegrationSession:
    """Build a real one-cycle learning run from existing package interfaces."""

    def __init__(
        self,
        fixture: Mapping[str, Any],
        scenario: Scenario,
        store: EventStore,
        *,
        learner_id: str = "integration-learner",
        evidence_origin: str = "evaluation_fixture",
    ) -> None:
        validate_fixture(fixture)
        self.fixture = dict(fixture)
        self.scenario = scenario
        self.store = store
        stored_hash = self.store.put_content_snapshot("domain_fixture", self.fixture)
        if stored_hash != fixture_content_hash(self.fixture):
            raise ValueError("stored fixture snapshot hash mismatch")
        self.learner_id = learner_id
        if evidence_origin not in {
            "human_local_interactive",
            "evaluation_fixture",
            "synthetic_isolated",
        }:
            raise ValueError("unsupported evidence origin")
        self.evidence_origin = evidence_origin
        self.kt = HermesKTTool()
        self.registry = self._registry()
        # The runtime requires a replaceable router boundary. This integration
        # never calls it: all current scoring and KT operations are deterministic.
        self.runtime = AgentRuntime(
            registry=self.registry,
            store=store,
            router=ModelRouter(DeterministicProvider()),
        )

    def run(self, run_id: str | None = None) -> RunResult:
        return self.runtime.run(self.new_state(run_id))

    def new_state(self, run_id: str | None = None) -> AgentState:
        context = {
            "fixture_id": self.fixture["fixture_id"],
            "fixture_content_sha256": fixture_content_hash(self.fixture),
            "scenario": self.scenario.name,
            "execution_mode": self.scenario.execution_mode,
            "network_opt_in": False,
            "evidence_origin": self.evidence_origin,
        }
        return AgentState(
            run_id=run_id or AgentState("placeholder", "placeholder", "placeholder").run_id,
            learner_id=self.learner_id,
            domain=self.fixture["domain"],
            goal=f"complete verified learning loop for {self.fixture['module']}",
            max_cycles=1,
            context=context,
        )

    def _registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        handlers = {
            Phase.OBSERVE: self._observe,
            Phase.DIAGNOSE: self._diagnose,
            Phase.PROBE: self._probe,
            Phase.TEACH: self._teach,
            Phase.VERIFY: self._verify,
            Phase.UPDATE: self._update,
            Phase.REFLECT: self._reflect,
        }
        required_outputs = {
            Phase.OBSERVE: ["score", "attempt", "adapter_version"],
            Phase.DIAGNOSE: ["diagnosis", "decision", "model_version", "policy_version"],
            Phase.PROBE: ["prompt", "selection", "response", "policy_version"],
            Phase.TEACH: ["prompt", "strategy", "policy_version"],
            Phase.VERIFY: ["verification", "post_state", "initial_update_state"],
            Phase.UPDATE: ["skill_id", "mastery_delta", "evidence", "model_version", "policy_version"],
            Phase.REFLECT: ["continue", "outcome", "policy_version"],
        }
        for phase, handler in handlers.items():
            registry.register(
                ToolSpec(
                    name=f"learning.{phase.value}",
                    description=f"Integration adapter for {phase.value}",
                    input_schema={
                        "type": "object",
                        "required": ["run_id", "learner_id", "phase", "latest_artifacts"],
                    },
                    output_schema={"type": "object", "required": required_outputs[phase]},
                    handler=handler,
                    phases=frozenset({phase}),
                    version="integration-tool-v1",
                )
            )
        return registry

    def _observe(self, payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
        score = score_attempt(self.fixture, self.scenario.initial_response)
        score_dict = _sanitized_score(score.to_dict(), self.scenario.initial_response)
        attempt = self._attempt_from_score(
            score_dict,
            attempt_id=f"{payload['run_id']}:initial",
            response=self.scenario.initial_response,
            independent=True,
            hints=0,
        )
        return {
            "fixture_id": self.fixture["fixture_id"],
            "score": score_dict,
            "attempt": attempt,
            "adapter_version": score.adapter_version,
            "evidence": score_dict["observations"],
            "response_evidence": sanitize_response(self.scenario.initial_response),
        }

    def _diagnose(self, payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
        observe = payload["latest_artifacts"]["observe"]
        attempt = observe["attempt"]
        candidates = observe["score"]["cause_candidates"]
        if candidates:
            diagnosis = self.kt.diagnose(
                {
                    "attempt": attempt,
                    "priors": self._priors(),
                    "history": {
                        "counts": dict(self.scenario.learner_history),
                        "exposure_count": int(sum(self.scenario.learner_history.values())),
                        "source_version": "integration-scenario-history-v1",
                    },
                }
            )
            for hypothesis in diagnosis["hypotheses"]:
                hypothesis["status"] = "unconfirmed_hypothesis"
            model_version = diagnosis["model_version"]
        else:
            diagnosis = {
                "attempt_id": attempt["attempt_id"],
                "hypotheses": [],
                "uncertainty": 0.0,
                "provenance": {"gate": "deterministic correct score; no error cause inferred"},
                "model_version": NO_ERROR_MODEL_VERSION,
            }
            model_version = NO_ERROR_MODEL_VERSION
        uncertainty = float(diagnosis["uncertainty"])
        if not diagnosis["hypotheses"]:
            decision = "retention_probe"
        elif uncertainty >= 0.80:
            decision = "disambiguate_hypotheses"
        else:
            decision = "confirm_top_hypothesis"
        return {
            "diagnosis": diagnosis,
            "decision": decision,
            "model_version": model_version,
            "policy_version": POLICY_VERSION,
            "engine_tool": {"name": self.kt.name, "version": self.kt.version},
        }

    def _probe(self, payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
        diagnosis = payload["latest_artifacts"]["diagnose"]
        hypotheses = diagnosis["diagnosis"]["hypotheses"]
        return {
            "prompt_instance_id": prompt_instance_id(str(payload["run_id"]), "probe"),
            "prompt": self.fixture["probe"]["prompt"],
            "targets": list(self.fixture["probe"].get("targets", [])),
            "selection": diagnosis["decision"],
            "top_hypothesis": hypotheses[0]["cause_id"] if hypotheses else None,
            "response": self.scenario.probe_response,
            "response_status": "observed" if self.scenario.probe_response is not None else "pending",
            "policy_version": POLICY_VERSION,
        }

    def _teach(self, payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
        probe = payload["latest_artifacts"]["probe"]
        diagnosis = payload["latest_artifacts"]["diagnose"]["diagnosis"]
        selection = _select_teaching_variant(
            self.fixture,
            diagnosis.get("hypotheses", []),
            probe.get("assessment"),
        )
        verification_condition = self.fixture["independent_verify"]["pass_condition"]
        verification_item = {
            "item_id": self.fixture["independent_verify"].get(
                "item_id", f"{self.fixture['fixture_id']}:independent-verify"
            ),
            "content_signature": self.fixture["independent_verify"].get("content_signature"),
            "novelty_status": self.fixture["independent_verify"].get(
                "novelty_status", "different_authored_prompt"
            ),
        }
        if verification_condition.get("scorer") == "exact_option_v1":
            verification_item["options"] = dict(verification_condition["options"])
        return {
            "prompt": selection["prompt"],
            "strategy": selection["strategy"],
            "independent_verification_prompt": self.fixture["independent_verify"]["prompt"],
            "independent_verification_prompt_instance_id": prompt_instance_id(
                str(payload["run_id"]), "verification"
            ),
            "independent_verification_response_mode": self.fixture["independent_verify"]["response_mode"],
            # Safe learner-facing projection: the correct option remains only
            # inside the scorer contract and is never copied into this item.
            "independent_verification_item": verification_item,
            "based_on": {
                "probe_selection": probe["selection"],
                "top_hypothesis": selection["instructional_focus"],
                "original_top_hypothesis": probe["top_hypothesis"],
                "instructional_focus": selection["instructional_focus"],
                "focus_claim_status": selection["focus_claim_status"],
                "refuted_hypotheses": selection["refuted_hypotheses"],
                "probe_response": probe["response"],
                "probe_assessment": probe.get("assessment"),
                "selection_policy_version": "probe-evidence-teaching-selection.v1",
                "semantics": "hypothesis_guided_instruction_not_causal_confirmation",
            },
            "policy_version": POLICY_VERSION,
        }

    def _verify(self, payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
        observe = payload["latest_artifacts"]["observe"]
        target_skill_id = self.fixture.get("kt_target_skill_id")
        skill = next(
            (
                item
                for item in self.fixture["skills"]
                if target_skill_id is not None and item["skill_id"] == target_skill_id
            ),
            self.fixture["skills"][0],
        )
        if target_skill_id is not None and skill["skill_id"] != target_skill_id:
            raise ValueError("kt_target_skill_id is not present in fixture skills")
        initial_state = self._initial_state(skill["skill_id"])
        parameters = self._parameters(skill["skill_id"])
        initial_update = self.kt.update_mastery(
            {
                "state": initial_state,
                "attempt": observe["attempt"],
                "parameters": parameters,
                "skill_weight": float(skill["weight"]),
                "item_difficulty": 0.0,
            }
        )
        if self.scenario.verification_response is None:
            verification = {
                "intervention_id": f"{payload['run_id']}:teach",
                "pre_mastery": initial_update["mastery"],
                "post_mastery": initial_update["mastery"],
                "mastery_gain": 0.0,
                "independently_verified": False,
                "effective": None,
                "reason": "inconclusive: independent verification response is pending",
                "provenance": {
                    "verification_attempt": None,
                    "minimum_gain": 0.02,
                    "model_version": VERIFY_MODEL_VERSION,
                    "status": "pending_learner_response",
                },
            }
            return {
                "prompt": self.fixture["independent_verify"]["prompt"],
                "response": None,
                "verification_attempt": None,
                "initial_update_state": initial_update,
                "post_state": initial_update,
                "verification": verification,
                "engine_tool": {"name": self.kt.name, "version": self.kt.version},
            }
        verify_attempt = self._verification_attempt(payload["run_id"])
        verified = self.kt.verify_intervention(
            {
                "intervention_id": f"{payload['run_id']}:teach",
                "pre_state": initial_update,
                "verification_attempt": verify_attempt,
                "parameters": parameters,
                "item_difficulty": 0.0,
                "minimum_gain": 0.02,
                "evidence_weight": self.scenario.verification_evidence_weight,
            }
        )
        return {
            "prompt": self.fixture["independent_verify"]["prompt"],
            "response": sanitize_response(self.scenario.verification_response)["redacted_text"],
            "response_evidence": sanitize_response(self.scenario.verification_response),
            "verification_attempt": verify_attempt,
            "initial_update_state": initial_update,
            "post_state": verified["post_state"],
            "verification": verified["verification"],
            "engine_tool": {"name": self.kt.name, "version": self.kt.version},
        }

    def _update(self, payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
        observe = payload["latest_artifacts"]["observe"]
        verify = payload["latest_artifacts"]["verify"]
        initial = self._initial_state(verify["post_state"]["skill_id"])
        initial_mastery = float(initial["mastery"])
        committed = bool(verify["verification"]["independently_verified"])
        final_mastery = float(verify["post_state"]["mastery"]) if committed else initial_mastery
        return {
            "skill_id": verify["post_state"]["skill_id"],
            "previous_mastery": initial_mastery,
            "new_mastery": final_mastery,
            "mastery_delta": round(final_mastery - initial_mastery, 12),
            "uncertainty": verify["post_state"]["uncertainty"] if committed else initial["uncertainty"],
            "commit_status": "committed" if committed else "withheld_assisted_verification",
            "evidence": {
                "initial_attempt_id": observe["attempt"]["attempt_id"],
                "verification_attempt_id": (
                    verify["verification_attempt"]["attempt_id"]
                    if isinstance(verify.get("verification_attempt"), dict)
                    else None
                ),
                "independently_verified": verify["verification"]["independently_verified"],
                "verification_effective": verify["verification"]["effective"],
                "engine_provenance": verify["post_state"]["provenance"],
            },
            "model_version": {
                "mastery": MASTERY_MODEL_VERSION,
                "verification": VERIFY_MODEL_VERSION,
                "engine_tool": self.kt.version,
            },
            "policy_version": POLICY_VERSION,
        }

    def _reflect(self, payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
        update = payload["latest_artifacts"]["update"]
        verification = payload["latest_artifacts"]["verify"]["verification"]
        effective = verification["effective"]
        if effective is True:
            outcome = "verified_transfer"
        elif effective is None:
            outcome = "inconclusive_needs_independent_retry"
        else:
            outcome = "not_yet_mastered"
        return {
            "continue": False,
            "outcome": outcome,
            "mastery_delta": update["mastery_delta"],
            "next_action": "schedule_delayed_retention" if effective else "schedule_targeted_retry",
            "policy_version": POLICY_VERSION,
        }

    def _attempt_from_score(
        self,
        score: Mapping[str, Any],
        *,
        attempt_id: str,
        response: str,
        independent: bool,
        hints: int,
    ) -> dict[str, Any]:
        candidates = score["cause_candidates"]
        likelihoods = {
            item["cause_id"]: max(1e-6, float(item["probability"]) / max(float(item["prior"]), 1e-6))
            for item in candidates
        }
        return {
            "attempt_id": attempt_id,
            "learner_id": self.learner_id,
            "item_id": self.fixture.get("task", {}).get("item_id", self.fixture["fixture_id"]),
            "item_type": self.fixture["module"],
            "correct": bool(score["passed"]),
            "response_time_seconds": self.scenario.response_time_seconds,
            "confidence": self.scenario.confidence,
            "selected_option": (
                sanitize_response(response)["redacted_text"]
                if self.fixture["task"]["response_mode"] == "single_choice"
                else None
            ),
            "hints_used": hints,
            "independently_answered": independent,
            "observed_at": self.scenario.initial_observed_at,
            "cause_likelihoods": likelihoods,
            "evidence_features": {
                "domain_observations": score["observations"],
                "adapter_version": score["adapter_version"],
                "content_signature": self.fixture.get("task", {}).get("content_signature"),
            },
        }

    def _verification_attempt(self, run_id: str) -> dict[str, Any]:
        assert self.scenario.verification_response is not None
        correct, scoring = score_verification_response(
            self.fixture, self.scenario.verification_response
        )
        return {
            "attempt_id": f"{run_id}:independent-verify",
            "learner_id": self.learner_id,
            "item_id": self.fixture["independent_verify"].get(
                "item_id", f"{self.fixture['fixture_id']}:independent-verify"
            ),
            "item_type": self.fixture["module"],
            "correct": correct,
            "response_time_seconds": self.scenario.response_time_seconds,
            "confidence": self.scenario.confidence,
            "selected_option": (
                sanitize_response(self.scenario.verification_response)["redacted_text"]
                if self.fixture["independent_verify"]["response_mode"] == "single_choice"
                else None
            ),
            "hints_used": self.scenario.verification_hints,
            "independently_answered": self.scenario.independently_answered,
            "observed_at": self.scenario.verification_observed_at,
            "cause_likelihoods": {},
            "evidence_features": {
                "different_prompt": True,
                "novelty_status": self.fixture["independent_verify"].get(
                    "novelty_status", "different_authored_prompt"
                ),
                "content_signature": self.fixture["independent_verify"].get("content_signature"),
                "source_item_id": self.fixture.get("task", {}).get(
                    "item_id", self.fixture["fixture_id"]
                ),
                "scoring": scoring,
                "assistance": {
                    "hints_used": self.scenario.verification_hints,
                    "evidence_weight": self.scenario.verification_evidence_weight,
                    "policy_version": "assistance-evidence-policy.v1",
                },
            },
        }

    def _priors(self) -> list[dict[str, Any]]:
        return [
            {
                "cause_id": item["cause_id"],
                "probability": float(item["synthetic_prior"]),
                "cohort_id": "synthetic-fixture-cold-start",
                "sample_size": 0,
                "source_version": self.fixture["provenance"].get("prior_source", "unknown"),
            }
            for item in self.fixture["diagnosis"]["candidate_causes"]
        ]

    def _initial_state(self, skill_id: str) -> dict[str, Any]:
        return {
            "learner_id": self.learner_id,
            "skill_id": skill_id,
            "bkt_mastery": 0.30,
            "successes": 0.0,
            "failures": 0.0,
            "irt_theta": 0.0,
            "evidence_count": 0,
            "mastery": 0.30,
            "uncertainty": 1.0,
            "last_updated_at": None,
            "provenance": (),
        }

    @staticmethod
    def _parameters(skill_id: str) -> dict[str, Any]:
        return {
            "skill_id": skill_id,
            "bkt_learn": 0.12,
            "bkt_guess": 0.20,
            "bkt_slip": 0.10,
            "pfa_intercept": -0.7,
            "pfa_success_weight": 0.35,
            "pfa_failure_weight": -0.25,
            "ensemble_weights": (0.50, 0.30, 0.20),
        }


def run_scenario(
    scenario_name: str,
    database: str | Path,
    *,
    fixture_path: str = "xingce/data_analysis_growth.json",
    run_id: str | None = None,
) -> tuple[IntegrationSession, RunResult]:
    try:
        scenario = SCENARIOS[scenario_name]
    except KeyError as exc:
        raise ValueError(f"unknown scenario: {scenario_name}") from exc
    store = EventStore(database)
    transfer_store = False
    try:
        session = IntegrationSession(load_fixture(fixture_path), scenario, store)
        result = session.run(run_id=run_id)
        transfer_store = True
        return session, result
    finally:
        if not transfer_store:
            store.close()


def run_attempt(
    fixture: Mapping[str, Any],
    response: str,
    confidence: float,
    response_time_seconds: float,
    database: str | Path,
    *,
    run_id: str | None = None,
    learner_id: str = "local-learner",
) -> tuple[IntegrationSession, RunResult]:
    """Start one real learner session and interrupt after issuing the probe.

    The response is scored in memory. Only a redacted evidence projection and a
    one-way digest enter the append-only trace. Later responses must arrive via
    :func:`continue_attempt`; none are invented.
    """
    validate_fixture(fixture)
    if not isinstance(response, str) or not response.strip():
        raise ValueError("response must be non-empty text")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be in [0, 1]")
    if response_time_seconds < 0:
        raise ValueError("response_time_seconds cannot be negative")
    scenario = Scenario(
        name="attempt",
        initial_response=response,
        probe_response=None,
        verification_response=None,
        independently_answered=False,
        response_time_seconds=response_time_seconds,
        confidence=confidence,
        learner_history={},
        execution_mode=fixture["execution"]["connectivity"],
        initial_observed_at=_utc_now(),
        verification_observed_at=_utc_now(),
    )
    store = EventStore(database)
    transfer_store = False
    try:
        session = IntegrationSession(
            fixture,
            scenario,
            store,
            learner_id=learner_id,
            evidence_origin="human_local_interactive",
        )
        result = session.runtime.run(session.new_state(run_id), interrupt_after=3)
        transfer_store = True
        return session, result
    finally:
        if not transfer_store:
            store.close()


class ContinuationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def continue_attempt(
    fixture: Mapping[str, Any],
    database: str | Path,
    run_id: str,
    *,
    phase: str,
    expected_version: int,
    expected_state: str,
    prompt_instance: str,
    response: str,
    confidence: float,
    response_time_seconds: float,
) -> tuple[IntegrationSession, RunResult]:
    """Append a learner response and resume exactly one authorized segment."""
    if phase not in {"probe", "verification"}:
        raise ContinuationError("invalid_phase", "phase must be probe or verification")
    store = EventStore(database)
    transfer_store = False
    try:
        events = store.events(run_id)
        if not events:
            raise ContinuationError("run_not_found", "attempt session does not exist")
        if expected_version != events[-1].seq:
            raise ContinuationError(
                "stale_version", "expected_version does not match current trace version"
            )
        state = store.load_state(run_id)
        persisted_fixture_hash = state.context.get("fixture_content_sha256")
        if (
            not isinstance(persisted_fixture_hash, str)
            or fixture_content_hash(fixture) != persisted_fixture_hash
        ):
            raise ContinuationError(
                "fixture_version_mismatch",
                "fixture content does not match the immutable attempt binding",
            )
        actual_state = attempt_state_name(state)
        if expected_state != actual_state:
            latest_version = store.events(run_id)[-1].seq
            if latest_version != expected_version:
                raise ContinuationError(
                    "stale_version", "expected_version does not match current trace version"
                )
            raise ContinuationError(
                "state_mismatch", "expected_state does not match current session state"
            )
        required_state = "awaiting_probe" if phase == "probe" else "awaiting_verification"
        if actual_state != required_state:
            raise ContinuationError(
                "out_of_order", f"{phase} response is not accepted in the current state"
            )
        required_prompt = prompt_instance_id(run_id, phase)
        if prompt_instance != required_prompt:
            raise ContinuationError(
                "prompt_mismatch", "prompt_instance_id does not match the current writable prompt"
            )
        if not isinstance(response, str) or not response.strip():
            raise ContinuationError("invalid_response", "response must be non-empty text")
        verification_assistance = assistance_events_for_prompt(events, required_prompt)
        verification_weight = min(
            (
                float(event.payload.get("diagnostic_evidence_weight", 0.0))
                for event in verification_assistance
            ),
            default=1.0,
        )
        scenario = Scenario(
            name="attempt_continuation",
            initial_response="unused",
            probe_response=response if phase == "probe" else None,
            verification_response=response if phase == "verification" else None,
            independently_answered=phase == "verification" and not verification_assistance,
            verification_hints=len(verification_assistance),
            verification_evidence_weight=verification_weight,
            response_time_seconds=response_time_seconds,
            confidence=confidence,
            learner_history={},
            execution_mode=fixture["execution"]["connectivity"],
            initial_observed_at=_utc_now(),
            verification_observed_at=_utc_now(),
        )
        session = IntegrationSession(
            fixture,
            scenario,
            store,
            learner_id=state.learner_id,
            evidence_origin=str(
                state.context.get("evidence_origin", "evaluation_fixture")
            ),
        )
        before = deepcopy(state.to_dict())
        evidence = sanitize_response(response)
        if phase == "probe":
            probe = state.artifacts["probe"][-1]
            probe["response"] = evidence["redacted_text"]
            probe["response_status"] = "observed"
            probe["learner_response_evidence"] = {
                **evidence,
                "confidence": confidence,
                "response_time_seconds": response_time_seconds,
            }
        consumed_prompts = list(state.context.get("consumed_prompt_instances", []))
        if prompt_instance not in consumed_prompts:
            consumed_prompts.append(prompt_instance)
        state.context["consumed_prompt_instances"] = consumed_prompts
        after = state.to_dict()
        try:
            response_event = store.append_if_version(
                run_id,
                expected_version,
                "learner_response_recorded",
                {
                    "phase": phase,
                    "expected_version": expected_version,
                    "expected_state": expected_state,
                    "prompt_instance_id": prompt_instance,
                    "response_evidence": evidence,
                    "confidence": confidence,
                    "response_time_seconds": response_time_seconds,
                    "state_diff": state_diff(before, after),
                    "state_after": after,
                },
            )
        except TraceVersionConflict:
            raise ContinuationError(
                "stale_version", "expected_version does not match current trace version"
            ) from None
        if phase == "probe":
            probe_assistance = assistance_events_for_prompt(events, required_prompt)
            evidence_weight = min(
                (
                    float(event.payload.get("diagnostic_evidence_weight", 0.0))
                    for event in probe_assistance
                ),
                default=1.0,
            )
            assessment = assess_probe_response(
                fixture,
                evidence["redacted_text"],
                response_event_seq=response_event.seq,
                response_event_hash=response_event.event_hash,
                diagnostic_evidence_weight=evidence_weight,
            )
            state.artifacts["probe"][-1]["assessment"] = assessment
            assessed_state = state.to_dict()
            store.append_if_version(
                run_id,
                response_event.seq,
                "probe_assessed",
                {
                    **assessment,
                    "prompt_instance_id": prompt_instance,
                    "state_diff": state_diff(after, assessed_state),
                    "state_after": assessed_state,
                },
            )
        resumed = session.runtime.resume(run_id)
        result = (
            session.runtime.run(resumed, interrupt_after=1)
            if phase == "probe"
            else session.runtime.run(resumed)
        )
        transfer_store = True
        return session, result
    finally:
        if not transfer_store:
            store.close()


def attempt_state_name(state: AgentState) -> str:
    if state.status is RunStatus.INTERRUPTED and state.phase is Phase.TEACH:
        if prompt_instance_id(state.run_id, "probe") in state.context.get(
            "consumed_prompt_instances", []
        ):
            return "processing_probe"
        return "awaiting_probe"
    if state.status is RunStatus.INTERRUPTED and state.phase is Phase.VERIFY:
        if prompt_instance_id(state.run_id, "verification") in state.context.get(
            "consumed_prompt_instances", []
        ):
            return "processing_verification"
        return "awaiting_verification"
    if state.status is RunStatus.COMPLETED:
        return "completed"
    if state.status is RunStatus.FAILED:
        return "failed"
    return f"{state.status.value}:{state.phase.value}"


def _select_teaching_variant(
    fixture: Mapping[str, Any],
    hypotheses: list[Mapping[str, Any]],
    assessment: Any,
) -> dict[str, Any]:
    """Choose instruction from probe evidence without confirming a cause."""

    statuses = {
        str(item.get("cause_id")): str(item.get("claim_status"))
        for item in (
            assessment.get("assessments", [])
            if isinstance(assessment, Mapping)
            else []
        )
        if isinstance(item, Mapping)
    }
    supported = [
        item
        for item in hypotheses
        if statuses.get(str(item.get("cause_id"))) == "supported_hypothesis"
    ]
    eligible = supported or [
        item
        for item in hypotheses
        if statuses.get(str(item.get("cause_id"))) != "refuted_hypothesis"
    ]
    focus = str(eligible[0]["cause_id"]) if eligible else None
    variants = {
        str(item["cause_id"]): item
        for item in fixture.get("teach", {}).get("variants", [])
        if isinstance(item, Mapping) and item.get("cause_id")
    }
    if focus is not None:
        variant = variants.get(focus)
        if variant is None:
            raise ValueError(f"missing authored teaching variant for cause: {focus}")
        prompt = str(variant["prompt"])
        strategy = str(variant.get("strategy", "targeted-explanation"))
        focus_status = statuses.get(focus, "unconfirmed_hypothesis")
    else:
        prompt = str(fixture["teach"]["prompt"])
        strategy = str(fixture["teach"].get("strategy", "targeted-explanation"))
        focus_status = "all_candidates_refuted" if hypotheses else "no_error_candidate"
    return {
        "prompt": prompt,
        "strategy": strategy,
        "instructional_focus": focus,
        "focus_claim_status": focus_status,
        "refuted_hypotheses": sorted(
            cause_id
            for cause_id, status in statuses.items()
            if status == "refuted_hypothesis"
        ),
    }


def sanitize_response(response: str) -> dict[str, Any]:
    redacted = response
    redactions: list[str] = []
    patterns = (
        ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[EMAIL]"),
        ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[PHONE]"),
        ("national_id", re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"), "[ID]"),
        ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[SECRET]"),
        ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[SECRET]"),
        (
            "bearer_token",
            re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"),
            "[SECRET]",
        ),
        (
            "private_key",
            re.compile(
                r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
                r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                re.DOTALL,
            ),
            "[SECRET]",
        ),
    )
    for label, pattern, replacement in patterns:
        redacted, count = pattern.subn(replacement, redacted)
        if count:
            redactions.extend([label] * count)
    return {
        "redacted_text": redacted,
        "sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
        "original_length": len(response),
        "redactions": redactions,
        "policy_version": "attempt-response-redaction-v1",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitized_score(score: Mapping[str, Any], response: str) -> dict[str, Any]:
    result = dict(score)
    observations = []
    for observation in score["observations"]:
        item = dict(observation)
        if item.get("kind") == "response":
            item["value"] = sanitize_response(response)["redacted_text"]
        observations.append(item)
    result["observations"] = observations
    return result
