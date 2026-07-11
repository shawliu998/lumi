from __future__ import annotations

import json
import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from hermes_domains.adapters import score_attempt
from hermes_domains.contract import validate_fixture
from hermes_kt.tool_api import HermesKTTool
from hermes_runtime.diff import state_diff
from hermes_runtime.machine import AgentRuntime, RunResult
from hermes_runtime.models import DeterministicProvider, ModelRouter
from hermes_runtime.state import AgentState, Phase, RunStatus
from hermes_runtime.store import EventStore
from hermes_runtime.tools import ToolContext, ToolRegistry, ToolSpec


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
    response_time_seconds: float = 60.0
    confidence: float = 0.65
    learner_history: Mapping[str, float] = field(default_factory=dict)
    execution_mode: str = "local"


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
    ) -> None:
        validate_fixture(fixture)
        self.fixture = dict(fixture)
        self.scenario = scenario
        self.store = store
        self.learner_id = learner_id
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
            "scenario": self.scenario.name,
            "execution_mode": self.scenario.execution_mode,
            "network_opt_in": False,
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
        return {
            "prompt": self.fixture["teach"]["prompt"],
            "strategy": self.fixture["teach"].get("strategy", "targeted-explanation"),
            "independent_verification_prompt": self.fixture["independent_verify"]["prompt"],
            "independent_verification_response_mode": self.fixture["independent_verify"]["response_mode"],
            "based_on": {
                "probe_selection": probe["selection"],
                "top_hypothesis": probe["top_hypothesis"],
                "probe_response": probe["response"],
            },
            "policy_version": POLICY_VERSION,
        }

    def _verify(self, payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
        observe = payload["latest_artifacts"]["observe"]
        skill = self.fixture["skills"][0]
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
        initial_mastery = float(self._initial_state(verify["post_state"]["skill_id"])["mastery"])
        final_mastery = float(verify["post_state"]["mastery"])
        return {
            "skill_id": verify["post_state"]["skill_id"],
            "previous_mastery": initial_mastery,
            "new_mastery": final_mastery,
            "mastery_delta": round(final_mastery - initial_mastery, 12),
            "uncertainty": verify["post_state"]["uncertainty"],
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
            "item_id": self.fixture["fixture_id"],
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
            "observed_at": "2026-07-11T00:00:00+00:00",
            "cause_likelihoods": likelihoods,
            "evidence_features": {
                "domain_observations": score["observations"],
                "adapter_version": score["adapter_version"],
            },
        }

    def _verification_attempt(self, run_id: str) -> dict[str, Any]:
        assert self.scenario.verification_response is not None
        condition = self.fixture["independent_verify"]["pass_condition"]
        correct, scoring = _score_verification(self.scenario.verification_response, condition)
        return {
            "attempt_id": f"{run_id}:independent-verify",
            "learner_id": self.learner_id,
            "item_id": f"{self.fixture['fixture_id']}:independent-verify",
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
            "observed_at": "2026-07-11T00:05:00+00:00",
            "cause_likelihoods": {},
            "evidence_features": {
                "different_prompt": True,
                "scoring": scoring,
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
    session = IntegrationSession(load_fixture(fixture_path), scenario, store)
    return session, session.run(run_id=run_id)


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
    )
    store = EventStore(database)
    session = IntegrationSession(fixture, scenario, store, learner_id=learner_id)
    return session, session.runtime.run(session.new_state(run_id), interrupt_after=3)


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
    response: str,
    confidence: float,
    response_time_seconds: float,
) -> tuple[IntegrationSession, RunResult]:
    """Append a learner response and resume exactly one authorized segment."""
    if phase not in {"probe", "verification"}:
        raise ContinuationError("invalid_phase", "phase must be probe or verification")
    store = EventStore(database)
    events = store.events(run_id)
    if not events:
        store.close()
        raise ContinuationError("run_not_found", "attempt session does not exist")
    if expected_version != events[-1].seq:
        store.close()
        raise ContinuationError("stale_version", "expected_version does not match current trace version")
    state = store.load_state(run_id)
    actual_state = attempt_state_name(state)
    if expected_state != actual_state:
        store.close()
        raise ContinuationError("state_mismatch", "expected_state does not match current session state")
    required_state = "awaiting_probe" if phase == "probe" else "awaiting_verification"
    if actual_state != required_state:
        store.close()
        raise ContinuationError("out_of_order", f"{phase} response is not accepted in the current state")
    if not isinstance(response, str) or not response.strip():
        store.close()
        raise ContinuationError("invalid_response", "response must be non-empty text")
    scenario = Scenario(
        name="attempt_continuation",
        initial_response="unused",
        probe_response=response if phase == "probe" else None,
        verification_response=response if phase == "verification" else None,
        independently_answered=phase == "verification",
        verification_hints=0,
        response_time_seconds=response_time_seconds,
        confidence=confidence,
        learner_history={},
        execution_mode=fixture["execution"]["connectivity"],
    )
    session = IntegrationSession(fixture, scenario, store, learner_id=state.learner_id)
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
    after = state.to_dict()
    store.append(
        run_id,
        "learner_response_recorded",
        {
            "phase": phase,
            "expected_version": expected_version,
            "expected_state": expected_state,
            "response_evidence": evidence,
            "confidence": confidence,
            "response_time_seconds": response_time_seconds,
            "state_diff": state_diff(before, after),
            "state_after": after,
        },
    )
    resumed = session.runtime.resume(run_id)
    if phase == "probe":
        return session, session.runtime.run(resumed, interrupt_after=1)
    return session, session.runtime.run(resumed)


def attempt_state_name(state: AgentState) -> str:
    if state.status is RunStatus.INTERRUPTED and state.phase is Phase.TEACH:
        return "awaiting_probe"
    if state.status is RunStatus.INTERRUPTED and state.phase is Phase.VERIFY:
        return "awaiting_verification"
    if state.status is RunStatus.COMPLETED:
        return "completed"
    if state.status is RunStatus.FAILED:
        return "failed"
    return f"{state.status.value}:{state.phase.value}"


def _score_verification(response: str, condition: Mapping[str, Any]) -> tuple[bool, str]:
    if "correct_option" in condition:
        return (
            response.strip().upper() == str(condition["correct_option"]).upper(),
            "exact_option_comparison:v1",
        )
    if "required_concepts" in condition:
        matched = sum(str(concept).casefold() in response.casefold() for concept in condition["required_concepts"])
        return matched >= int(condition["minimum_points"]), "required_concept_match:v1"
    if "required_dimensions" in condition:
        aliases = {
            "safety": ("安全", "疏导", "秩序", "safety"),
            "restore": ("恢复", "维修", "技术", "restore"),
            "continuity": ("替代", "备用", "人工", "分流", "continuity"),
            "communication": ("沟通", "说明", "告知", "communication"),
            "followup": ("善后", "回访", "复盘", "followup"),
        }
        folded = response.casefold()
        matched = sum(
            any(term.casefold() in folded for term in aliases.get(str(dimension), (str(dimension),)))
            for dimension in condition["required_dimensions"]
        )
        return matched >= int(condition["minimum_dimensions"]), "required_dimension_alias_match:v1"
    raise ValueError("unsupported independent verification pass condition")


def sanitize_response(response: str) -> dict[str, Any]:
    redacted = response
    redactions: list[str] = []
    patterns = (
        ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[EMAIL]"),
        ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[PHONE]"),
        ("national_id", re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"), "[ID]"),
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
