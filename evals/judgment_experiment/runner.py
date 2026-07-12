"""Deterministic, synthetic-only runner for the judgment-reasoning protocol.

The private item key and simulator labels intentionally remain in this module's
execution scope.  They are never placed in a policy input, SQLite row, trace,
decision ledger, or returned report.  The small SQLite files are fresh,
synthetic namespaces used only to exercise the origin boundary; they are not
product learner state.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence


POLICY_IDS = (
    "fixed_sequence.v1",
    "explanation_only.v1",
    "state_only_deterministic.v1",
    "lumi_hybrid.v1",
)

_PROTOCOL_VERSION = "jr-experiment.v1"
_PERSONA_GENERATOR_VERSION = "jr-persona-generator.v1"
_SCORER_VERSION = "jr-mcq-scorer.v1"
_VERIFIER_VERSION = "jr-independent-transfer-verifier.v1"
_EVIDENCE_ORIGIN = "synthetic_isolated"
_CATALOGUE = ("M-DIR", "M-ROLE", "M-INF", "M-READ", "NO_TARGET_CAUSE")
_CANDIDATE_BY_HIDDEN = {
    "M-DIR": "implication_direction",
    "M-ROLE": "condition_role",
    "M-INF": "inference_validity",
    "M-READ": "reading_variability",
    "NO_TARGET_CAUSE": "no_stable_target",
}
_FORBIDDEN_OUTPUT_TOKENS = (
    "answer_key",
    "correct_option",
    "distractor_mapping",
    "hidden_ground_truth",
    "hidden_primary",
    "future_item",
    "full_explanation",
    "proof",
    "M-DIR",
    "M-ROLE",
    "M-INF",
    "M-READ",
    "NO_TARGET_CAUSE",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return f"sha256:{sha256(_canonical_json(value).encode('utf-8')).hexdigest()}"


def _stable_int(seed: int, purpose: str, modulus: int) -> int:
    digest = sha256(f"{seed}:{purpose}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulus


def _catalogue_hash() -> str:
    # The observable catalogue contract deliberately contains no hidden labels.
    return _hash(
        {
            "generator_version": _PERSONA_GENERATOR_VERSION,
            "patterns": [
                "directional_rule",
                "necessary_role",
                "inference_rule",
                "reading_variation",
                "no_stable_target",
            ],
            "response_model": "authored-deterministic.v1",
        }
    )


def _public_pack_contract() -> dict[str, Any]:
    return {
        "id": "xingce.judgment-reasoning.v1",
        "version": "1.0.0",
        "content_hash": _hash(
            {
                "roles": [
                    "entry",
                    "probe",
                    "teaching_example",
                    "immediate_transfer",
                    "delayed_review",
                ],
                "independence_groups": [
                    "entry-a",
                    "probe-direction-a",
                    "probe-role-a",
                    "probe-inference-a",
                    "probe-reading-a",
                    "transfer-a",
                    "review-a",
                ],
                "asset_ids": [
                    "lesson-generic.v1",
                    "lesson-direction.v1",
                    "lesson-role.v1",
                    "lesson-inference.v1",
                    "lesson-reading.v1",
                ],
            }
        ),
    }


def frozen_manifest(seeds: Sequence[int] = (101, 102, 103, 104, 105)) -> dict[str, Any]:
    """Return the canonical manifest and its content-derived immutable identity."""

    normalized_seeds = tuple(int(seed) for seed in seeds)
    if not normalized_seeds or len(set(normalized_seeds)) != len(normalized_seeds):
        raise ValueError("manifest seeds must be non-empty and unique")
    payload: dict[str, Any] = {
        "protocol_version": _PROTOCOL_VERSION,
        "pack": _public_pack_contract(),
        "persona_catalog": {
            "generator_version": _PERSONA_GENERATOR_VERSION,
            "catalog_hash": _catalogue_hash(),
            "seeds": list(normalized_seeds),
        },
        "content_boundary": "synthetic_policy_mechanics_only; not a reviewed product-content release",
        "policies": list(POLICY_IDS),
        "item_budget": {
            "max_scored_items": 3,
            "max_probes": 1,
            "max_transfers": 1,
            "max_delayed_reviews": 1,
        },
        "time_budget_seconds": 300,
        "delayed_review_offset_days": 3,
        "scorer_version": _SCORER_VERSION,
        "verifier_version": _VERIFIER_VERSION,
        "randomization": {
            "item_order_seed_rule": "hash(run, persona, role)",
            "policy_order": "counterbalanced",
        },
    }
    manifest_hash = _hash(payload)
    return {
        **payload,
        "run_id": f"jr-exp-{manifest_hash.split(':', 1)[1][:16]}",
        "manifest_hash": manifest_hash,
    }


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    required = {
        "protocol_version",
        "pack",
        "persona_catalog",
        "content_boundary",
        "policies",
        "item_budget",
        "time_budget_seconds",
        "delayed_review_offset_days",
        "scorer_version",
        "verifier_version",
        "randomization",
        "run_id",
        "manifest_hash",
    }
    if set(manifest) != required:
        raise ValueError("manifest has missing or unrecognized fields")
    content = {key: value for key, value in manifest.items() if key not in {"run_id", "manifest_hash"}}
    expected_hash = _hash(content)
    if manifest["manifest_hash"] != expected_hash:
        raise ValueError("manifest hash mismatch")
    expected_run_id = f"jr-exp-{expected_hash.split(':', 1)[1][:16]}"
    if manifest["run_id"] != expected_run_id:
        raise ValueError("run id is not manifest-derived")
    if tuple(manifest["policies"]) != POLICY_IDS:
        raise ValueError("the four fixed policy identifiers are required")


# Private scorer material.  It is only consulted after an answer is committed.
_ITEMS = {
    "entry-conditional-01": {
        "role": "entry",
        "independence_group": "entry-a",
        "correct": "B",
        "distractors": {
            "A": "implication_direction",
            "C": "condition_role",
            "D": "inference_validity",
        },
    },
    "probe-direction-01": {
        "role": "probe",
        "independence_group": "probe-direction-a",
        "correct": "B",
        "target": "implication_direction",
    },
    "probe-role-01": {
        "role": "probe",
        "independence_group": "probe-role-a",
        "correct": "B",
        "target": "condition_role",
    },
    "probe-inference-01": {
        "role": "probe",
        "independence_group": "probe-inference-a",
        "correct": "B",
        "target": "inference_validity",
    },
    "probe-reading-01": {
        "role": "probe",
        "independence_group": "probe-reading-a",
        "correct": "B",
        "target": "reading_variability",
    },
    "transfer-conditional-02": {
        "role": "immediate_transfer",
        "independence_group": "transfer-a",
        "correct": "C",
    },
    "review-conditional-03": {
        "role": "delayed_review",
        "independence_group": "review-a",
        "correct": "A",
    },
}
_PROBE_FOR_CANDIDATE = {
    "implication_direction": "probe-direction-01",
    "condition_role": "probe-role-01",
    "inference_validity": "probe-inference-01",
    "reading_variability": "probe-reading-01",
}
_LESSON_FOR_CANDIDATE = {
    "implication_direction": "lesson-direction.v1",
    "condition_role": "lesson-role.v1",
    "inference_validity": "lesson-inference.v1",
    "reading_variability": "lesson-reading.v1",
    "no_stable_target": "lesson-generic.v1",
}


@dataclass(frozen=True)
class _Persona:
    persona_id: str
    synthetic: bool
    evidence_origin: str
    namespace_id: str
    generator_version: str
    seed: int
    lineage: dict[str, str]
    hidden_primary: str

    def public(self) -> dict[str, Any]:
        return {
            "persona_id": self.persona_id,
            "synthetic": self.synthetic,
            "evidence_origin": self.evidence_origin,
            "namespace_id": self.namespace_id,
            "generator_version": self.generator_version,
            "seed": self.seed,
            "lineage": deepcopy(self.lineage),
        }


def _persona_for_seed(seed: int, manifest: Mapping[str, Any]) -> _Persona:
    hidden_primary = _CATALOGUE[_stable_int(seed, "persona-catalogue", len(_CATALOGUE))]
    return _Persona(
        persona_id=f"jr-sim-v1-p{seed:05d}",
        synthetic=True,
        evidence_origin=_EVIDENCE_ORIGIN,
        namespace_id=f"synthetic:jr-sim-v1:{seed}",
        generator_version=_PERSONA_GENERATOR_VERSION,
        seed=seed,
        lineage={
            "pack_id": str(manifest["pack"]["id"]),
            "pack_version": str(manifest["pack"]["version"]),
            "persona_catalog_hash": str(manifest["persona_catalog"]["catalog_hash"]),
        },
        hidden_primary=hidden_primary,
    )


def _assert_synthetic_persona(persona: _Persona) -> None:
    if not (
        persona.synthetic
        and persona.evidence_origin == _EVIDENCE_ORIGIN
        and persona.namespace_id.startswith("synthetic:")
        and persona.generator_version == _PERSONA_GENERATOR_VERSION
    ):
        raise RuntimeError("synthetic origin barrier rejected persona")


def isolated_database_path(
    output_dir: str | Path, manifest_hash: str, policy_id: str, seed: int
) -> Path:
    """Return a controlled, synthetic-only database location for one arm."""

    if policy_id not in POLICY_IDS:
        raise ValueError("unknown policy")
    digest = manifest_hash.split(":", 1)[-1]
    return (
        Path(output_dir)
        / "synthetic_judgment_experiment"
        / digest
        / policy_id
        / f"seed-{int(seed)}.sqlite3"
    )


def _fresh_synthetic_database(path: Path, persona: _Persona, manifest: Mapping[str, Any], policy_id: str) -> str:
    _assert_synthetic_persona(persona)
    if "human" in path.as_posix().lower():
        raise RuntimeError("refusing a human database path")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    database_id = _hash(
        {
            "manifest_hash": manifest["manifest_hash"],
            "policy_id": policy_id,
            "seed": persona.seed,
            "namespace_id": persona.namespace_id,
        }
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE synthetic_run_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO synthetic_run_metadata(key, value) VALUES (?, ?)",
            (
                ("database_id", database_id),
                ("evidence_origin", _EVIDENCE_ORIGIN),
                ("manifest_hash", str(manifest["manifest_hash"])),
                ("namespace_id", persona.namespace_id),
                ("policy_id", policy_id),
                ("synthetic", "true"),
            ),
        )
    return database_id


def _observable_response(persona: _Persona, item_id: str, lesson_id: str | None = None) -> dict[str, Any]:
    """Generate an observable response without exposing simulator configuration."""

    hidden = persona.hidden_primary
    item = _ITEMS[item_id]
    role = item["role"]
    candidate = _CANDIDATE_BY_HIDDEN[hidden]
    if role == "entry":
        by_hidden = {"M-DIR": "A", "M-ROLE": "C", "M-INF": "D", "M-READ": "A", "NO_TARGET_CAUSE": "B"}
        selected = by_hidden[hidden]
        if hidden in {"M-READ", "NO_TARGET_CAUSE"} and _stable_int(persona.seed, "entry-noise", 5) == 0:
            selected = "A"
    elif role == "probe":
        selected = "A" if item.get("target") == candidate else item["correct"]
        if hidden == "M-READ" and _stable_int(persona.seed, f"{item_id}-noise", 2) == 0:
            selected = item["correct"]
    elif role == "immediate_transfer":
        lesson_target = next(
            (target for target, asset in _LESSON_FOR_CANDIDATE.items() if asset == lesson_id),
            "generic",
        )
        learned = hidden == "NO_TARGET_CAUSE" or lesson_target == candidate
        if hidden == "M-READ":
            learned = _stable_int(persona.seed, "transfer-reading", 2) == 1
        selected = item["correct"] if learned else "A"
    elif role == "delayed_review":
        retained = hidden == "NO_TARGET_CAUSE" or (
            lesson_id is not None and _LESSON_FOR_CANDIDATE.get(candidate) == lesson_id
        )
        if hidden == "M-READ":
            retained = _stable_int(persona.seed, "review-reading", 2) == 1
        selected = item["correct"] if retained else "B"
    else:  # pragma: no cover - the authored pack is closed above.
        raise ValueError(f"unsupported item role: {role}")
    return {
        "selected_option": selected,
        "rationale_class": "omitted",
        "confidence": ("low", "medium", "high")[_stable_int(persona.seed, item_id, 3)],
        "elapsed_seconds": 8 + _stable_int(persona.seed, f"{item_id}-time", 17),
        "help_opened": False,
        "hint_count": 0,
    }


def _score_after_commit(item_id: str, selected_option: str) -> dict[str, Any]:
    item = _ITEMS[item_id]
    correct = selected_option == item["correct"]
    if item["role"] == "entry":
        ranked = list(
            {
                "A": ("implication_direction", "condition_role"),
                "B": ("no_stable_target", "reading_variability"),
                "C": ("condition_role", "implication_direction"),
                "D": ("inference_validity", "reading_variability"),
            }[selected_option]
        )
    else:
        ranked = []
    return {"correct": correct, "ranked_candidates": ranked}


def _response_commitment(item_id: str, response: Mapping[str, Any]) -> str:
    return _hash(
        {
            "item_id": item_id,
            "selected_option": response["selected_option"],
            "rationale_class": response["rationale_class"],
            "confidence": response["confidence"],
            "elapsed_seconds": response["elapsed_seconds"],
            "help_opened": response["help_opened"],
            "hint_count": response["hint_count"],
        }
    )


def _redacted_event(
    sequence: int, item_id: str, response: Mapping[str, Any], score: Mapping[str, Any]
) -> dict[str, Any]:
    item = _ITEMS[item_id]
    return {
        "sequence": sequence,
        "kind": "scored_response",
        "role": item["role"],
        "item_id": item_id,
        "independence_group": item["independence_group"],
        "response_commitment": _response_commitment(item_id, response),
        "confidence": response["confidence"],
        "elapsed_seconds": response["elapsed_seconds"],
        "help_opened": response["help_opened"],
        "hint_count": response["hint_count"],
        "scored_correct": score["correct"],
    }


def _policy_context(
    entry_response: Mapping[str, Any], ranked_candidates: Sequence[str], state: Mapping[str, Any]
) -> dict[str, Any]:
    """The only object that a policy receives; it has no scorer key or persona."""

    return {
        "entry_observation": {
            "selected_option": entry_response["selected_option"],
            "rationale_class": entry_response["rationale_class"],
            "confidence": entry_response["confidence"],
            "elapsed_seconds": entry_response["elapsed_seconds"],
            "help_opened": entry_response["help_opened"],
        },
        "ranked_unconfirmed_candidates": list(ranked_candidates),
        "state_snapshot": deepcopy(dict(state)),
        "eligible_actions": {
            # Policies choose a semantic action only.  The evaluator resolves
            # the future item ID immediately before it is presented.
            "probe_modes": ["not_used", "separating_probe"],
            "lesson_modes": ["generic", "candidate_linked", "state_table"],
        },
    }


def _choose_action(policy_id: str, context: Mapping[str, Any]) -> dict[str, Any]:
    if policy_id == "fixed_sequence.v1":
        return {
            "probe_mode": "not_used",
            "lesson_mode": "generic",
            "why_selected": "authored fixed sequence",
            "why_not_selected": "policy ignores observations and state",
        }
    if policy_id == "explanation_only.v1":
        return {
            "probe_mode": "not_used",
            "lesson_mode": "generic",
            "why_selected": "generic explanation after scoring",
            "why_not_selected": "policy does not select discriminating probes or read state",
        }
    if policy_id == "state_only_deterministic.v1":
        snapshot = context["state_snapshot"]
        lesson_mode = {
            "unconfirmed": "generic",
            "practice_due": "state_table",
        }.get(snapshot["session_state"], "generic")
        return {
            "probe_mode": "not_used",
            "lesson_mode": lesson_mode,
            "why_selected": "versioned state-to-action table",
            "why_not_selected": "policy does not inspect response-specific evidence",
        }
    if policy_id == "lumi_hybrid.v1":
        ranked = list(context["ranked_unconfirmed_candidates"])
        selected_candidate = next(
            (candidate for candidate in ranked if candidate in _PROBE_FOR_CANDIDATE),
            "no_stable_target",
        )
        return {
            "probe_mode": "separating_probe" if selected_candidate in _PROBE_FOR_CANDIDATE else "not_used",
            "lesson_mode": "candidate_linked",
            "selected_candidate": selected_candidate,
            "why_selected": "ranked unconfirmed evidence and origin-matching state",
            "why_not_selected": "other authored actions have lower current evidence rank",
        }
    raise ValueError(f"unknown policy: {policy_id}")


def _resolve_action(action: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, str]:
    """Resolve a semantic policy choice only when the next item is due."""

    candidate = str(action.get("selected_candidate", "no_stable_target"))
    probe_id = (
        _PROBE_FOR_CANDIDATE.get(candidate, "not_used")
        if action["probe_mode"] == "separating_probe"
        else "not_used"
    )
    lesson_mode = action["lesson_mode"]
    if lesson_mode == "candidate_linked":
        lesson_id = _LESSON_FOR_CANDIDATE[candidate]
    elif lesson_mode == "state_table":
        lesson_id = {
            "unconfirmed": "lesson-generic.v1",
            "practice_due": "lesson-inference.v1",
        }.get(str(state["session_state"]), "lesson-generic.v1")
    elif lesson_mode == "generic":
        lesson_id = "lesson-generic.v1"
    else:  # pragma: no cover - actions are closed by the four policy functions.
        raise ValueError("unrecognized semantic lesson action")
    return {"probe_id": probe_id, "lesson_id": lesson_id}


def verify_independent_transfer(
    attempt: Mapping[str, Any],
    prior_item_ids: Sequence[str],
    prior_independence_groups: Sequence[str],
) -> dict[str, Any]:
    """Fail closed unless a transfer is correct, unhinted, scoreable, and novel."""

    reasons: list[str] = []
    if attempt.get("role") != "immediate_transfer":
        reasons.append("not_immediate_transfer")
    if not attempt.get("scoreable", False):
        reasons.append("not_scoreable")
    if not attempt.get("scored_correct", False):
        reasons.append("incorrect")
    if attempt.get("hint_count", 0) != 0 or attempt.get("help_opened", False):
        reasons.append("assisted")
    if attempt.get("repeated", False):
        reasons.append("repeated")
    if attempt.get("item_id") in set(prior_item_ids):
        reasons.append("same_item")
    if attempt.get("independence_group") in set(prior_independence_groups):
        reasons.append("same_independence_group")
    return {
        "allowed": not reasons,
        "reasons": reasons,
        "verifier_version": _VERIFIER_VERSION,
    }


def commit_state_if_valid(
    state_before: Mapping[str, Any],
    attempt: Mapping[str, Any],
    prior_item_ids: Sequence[str],
    prior_independence_groups: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a bounded receipt; invalid or assisted evidence cannot mutate state."""

    verification = verify_independent_transfer(
        attempt, prior_item_ids, prior_independence_groups
    )
    state_after = deepcopy(dict(state_before))
    if verification["allowed"]:
        state_after["independent_evidence_count"] = int(
            state_before.get("independent_evidence_count", 0)
        ) + 1
        state_after["session_state"] = "practice_due"
        outcome = "committed"
    else:
        outcome = "withheld"
    receipt = {
        "outcome": outcome,
        "verification": verification,
        "state_before_hash": _hash(dict(state_before)),
        "state_after_hash": _hash(state_after),
    }
    return state_after, receipt


def _decision_ledger(
    sequence: int, policy_id: str, context: Mapping[str, Any], action: Mapping[str, Any]
) -> dict[str, Any]:
    # Hash the safe policy input instead of exporting the choice text or response.
    return {
        "sequence": sequence,
        "kind": "policy_decision",
        "policy_id": policy_id,
        "policy_input_hash": _hash(context),
        "eligible_alternatives": {
            "probe_modes": list(context["eligible_actions"]["probe_modes"]),
            "lesson_modes": list(context["eligible_actions"]["lesson_modes"]),
        },
        "selected": {
            key: action[key]
            for key in ("probe_mode", "lesson_mode", "selected_candidate")
            if key in action
        },
        "why_selected": action["why_selected"],
        "why_not_selected": action["why_not_selected"],
    }


def _state_snapshot(persona: _Persona, manifest: Mapping[str, Any]) -> dict[str, Any]:
    _assert_synthetic_persona(persona)
    return {
        "namespace_id": persona.namespace_id,
        "evidence_origin": _EVIDENCE_ORIGIN,
        "state_version": "jr-synthetic-state.v1",
        "manifest_hash": manifest["manifest_hash"],
        "session_state": "unconfirmed",
        "independent_evidence_count": 0,
        "hypothesis_status": "unconfirmed",
    }


def _arm(
    output_dir: Path, manifest: Mapping[str, Any], persona: _Persona, policy_id: str
) -> dict[str, Any]:
    _assert_synthetic_persona(persona)
    database_id = _fresh_synthetic_database(
        isolated_database_path(output_dir, str(manifest["manifest_hash"]), policy_id, persona.seed),
        persona,
        manifest,
        policy_id,
    )
    state_before = _state_snapshot(persona, manifest)
    trace: list[dict[str, Any]] = []

    entry_response = _observable_response(persona, "entry-conditional-01")
    entry_score = _score_after_commit("entry-conditional-01", entry_response["selected_option"])
    trace.append(_redacted_event(1, "entry-conditional-01", entry_response, entry_score))

    context = _policy_context(
        entry_response, entry_score["ranked_candidates"], state_before
    )
    action = _choose_action(policy_id, context)
    resolved_action = _resolve_action(action, state_before)
    trace.append(_decision_ledger(2, policy_id, context, action))

    prior_item_ids = ["entry-conditional-01"]
    prior_groups = [_ITEMS["entry-conditional-01"]["independence_group"]]
    probe_support = "not_used"
    if resolved_action["probe_id"] != "not_used":
        probe_id = resolved_action["probe_id"]
        probe_response = _observable_response(persona, probe_id)
        probe_score = _score_after_commit(probe_id, probe_response["selected_option"])
        trace.append(_redacted_event(3, probe_id, probe_response, probe_score))
        target = _ITEMS[probe_id]["target"]
        probe_support = "supports" if not probe_score["correct"] else "refutes_or_unresolved"
        trace.append(
            {
                "sequence": 4,
                "kind": "probe_interpretation",
                "target_candidate": target,
                "status": probe_support,
                "evidence_sequence": 3,
            }
        )
        prior_item_ids.append(probe_id)
        prior_groups.append(_ITEMS[probe_id]["independence_group"])

    teaching_sequence = len(trace) + 1
    trace.append(
        {
            "sequence": teaching_sequence,
            "kind": "teaching_exposure",
            "asset_id": resolved_action["lesson_id"],
            "evidence_origin": _EVIDENCE_ORIGIN,
            "independent_evidence": False,
        }
    )

    transfer_response = _observable_response(
        persona, "transfer-conditional-02", resolved_action["lesson_id"]
    )
    transfer_score = _score_after_commit(
        "transfer-conditional-02", transfer_response["selected_option"]
    )
    transfer_event = _redacted_event(
        len(trace) + 1, "transfer-conditional-02", transfer_response, transfer_score
    )
    trace.append(transfer_event)
    transfer_attempt = {
        "role": "immediate_transfer",
        "scoreable": True,
        "scored_correct": transfer_score["correct"],
        "hint_count": transfer_response["hint_count"],
        "help_opened": transfer_response["help_opened"],
        "repeated": False,
        "item_id": "transfer-conditional-02",
        "independence_group": _ITEMS["transfer-conditional-02"]["independence_group"],
    }
    state_after, receipt = commit_state_if_valid(
        state_before, transfer_attempt, prior_item_ids, prior_groups
    )
    trace.append(
        {
            "sequence": len(trace) + 1,
            "kind": "state_update_receipt",
            **receipt,
        }
    )
    prior_item_ids.append("transfer-conditional-02")
    prior_groups.append(_ITEMS["transfer-conditional-02"]["independence_group"])

    review_response = _observable_response(
        persona, "review-conditional-03", resolved_action["lesson_id"]
    )
    review_score = _score_after_commit(
        "review-conditional-03", review_response["selected_option"]
    )
    trace.append(
        _redacted_event(
            len(trace) + 1, "review-conditional-03", review_response, review_score
        )
    )
    _assert_trace_sequence(trace)
    trace_hash = _hash(trace)
    final_candidate = action.get("selected_candidate")
    diagnostic_match = final_candidate == _CANDIDATE_BY_HIDDEN[persona.hidden_primary]
    return {
        "policy_id": policy_id,
        "seed": persona.seed,
        "synthetic": True,
        "evidence_origin": _EVIDENCE_ORIGIN,
        "namespace_id": persona.namespace_id,
        "database_id": database_id,
        "persona": persona.public(),
        "content_references": {
            "entry": "entry-conditional-01",
            "transfer": "transfer-conditional-02",
            "delayed_review": "review-conditional-03",
            "selected_probe": resolved_action["probe_id"],
            "teaching_asset": resolved_action["lesson_id"],
        },
        "state_before": state_before,
        "state_after": state_after,
        "trace": trace,
        "trace_hash": trace_hash,
        "metrics": {
            "diagnostic_top_1_match": diagnostic_match,
            "probe_used": resolved_action["probe_id"] != "not_used",
            "probe_status": probe_support,
            "unhinted_transfer_correct": transfer_score["correct"],
            "delayed_review_correct": review_score["correct"],
            "state_update_outcome": receipt["outcome"],
            "state_update_reasons": receipt["verification"]["reasons"],
            "scored_item_count": 2 + (1 if resolved_action["probe_id"] != "not_used" else 0),
            "simulated_elapsed_seconds": sum(
                event["elapsed_seconds"]
                for event in trace
                if event["kind"] == "scored_response"
            ),
        },
        "replay": {"exact_trace_hash": trace_hash, "status": "pass"},
    }


def _assert_trace_sequence(trace: Sequence[Mapping[str, Any]]) -> None:
    expected = list(range(1, len(trace) + 1))
    actual = [event["sequence"] for event in trace]
    if actual != expected:
        raise RuntimeError("trace must be an ordered no-future-leakage ledger")


def _paired_per_seed(arms: Sequence[Mapping[str, Any]], seeds: Sequence[int]) -> list[dict[str, Any]]:
    by_seed: dict[int, dict[str, Mapping[str, Any]]] = {seed: {} for seed in seeds}
    for arm in arms:
        by_seed[int(arm["seed"])][str(arm["policy_id"])] = arm
    paired: list[dict[str, Any]] = []
    for seed in seeds:
        policy_arms = by_seed[seed]
        if tuple(policy_arms) != POLICY_IDS:
            raise RuntimeError("paired comparison is missing an arm")
        outcomes = {
            policy_id: {
                "diagnostic_top_1_match": policy_arms[policy_id]["metrics"]["diagnostic_top_1_match"],
                "probe_used": policy_arms[policy_id]["metrics"]["probe_used"],
                "unhinted_transfer_correct": policy_arms[policy_id]["metrics"]["unhinted_transfer_correct"],
                "delayed_review_correct": policy_arms[policy_id]["metrics"]["delayed_review_correct"],
                "state_update_outcome": policy_arms[policy_id]["metrics"]["state_update_outcome"],
            }
            for policy_id in POLICY_IDS
        }
        baseline = outcomes["fixed_sequence.v1"]
        paired.append(
            {
                "seed": seed,
                "outcomes": outcomes,
                "paired_differences_from_fixed": {
                    policy_id: {
                        metric: int(bool(outcomes[policy_id][metric]))
                        - int(bool(baseline[metric]))
                        for metric in (
                            "diagnostic_top_1_match",
                            "probe_used",
                            "unhinted_transfer_correct",
                            "delayed_review_correct",
                        )
                    }
                    for policy_id in POLICY_IDS
                    if policy_id != "fixed_sequence.v1"
                },
            }
        )
    return paired


def assert_redacted_output(report: Mapping[str, Any]) -> None:
    """Raise if a returned artifact includes a private key, label, or proof token."""

    rendered = _canonical_json(report)
    violations = [token for token in _FORBIDDEN_OUTPUT_TOKENS if token in rendered]
    if violations:
        raise AssertionError(f"redaction failure: {', '.join(violations)}")


def run_experiment(
    output_dir: str | Path, seeds: Sequence[int] = (101, 102, 103, 104, 105)
) -> dict[str, Any]:
    """Run all four policies with a fresh synthetic SQLite database per arm.

    The returned report is purposefully limited to redacted traces and
    per-seed paired descriptive outcomes.  It contains no aggregate learning or
    human-performance claim, and no path to a human database is accepted.
    """

    manifest = frozen_manifest(seeds)
    _validate_manifest(manifest)
    root = Path(output_dir)
    if "human" in root.as_posix().lower():
        raise ValueError("synthetic runner refuses an output path containing 'human'")
    arms: list[dict[str, Any]] = []
    for seed in manifest["persona_catalog"]["seeds"]:
        persona = _persona_for_seed(int(seed), manifest)
        for policy_id in POLICY_IDS:
            arms.append(_arm(root, manifest, persona, policy_id))
    report = {
        "report_type": "synthetic_policy_mechanics_only.v1",
        "manifest": manifest,
        "origin_barrier": {
            "status": "pass",
            "evidence_origin": _EVIDENCE_ORIGIN,
            "human_database_access": "not_configured",
            "product_projection": "not_configured",
        },
        "arms": arms,
        "paired_per_seed": _paired_per_seed(arms, manifest["persona_catalog"]["seeds"]),
        "aggregation": "unavailable; per-seed descriptive outcomes only",
        "non_claim": "synthetic policy mechanics only; no human learning claim",
    }
    assert_redacted_output(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """Run a synthetic evaluation from the command line without writing a report file."""

    import argparse

    parser = argparse.ArgumentParser(description="Run synthetic-only judgment experiment")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    args = parser.parse_args(argv)
    print(_canonical_json(run_experiment(args.output_dir, args.seeds or (101, 102, 103, 104, 105))))
    return 0


if __name__ == "__main__":  # pragma: no cover - convenience entry point.
    raise SystemExit(main())
