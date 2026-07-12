"""Validation for the unregistered Lumi conditional-reasoning draft pack.

The pack is intentionally self-contained and stays outside the product catalog.
This module performs deterministic structural, logic-metadata, review-gate, and
checksum checks; it does not publish content or mutate learner state.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from .contract import ContractError


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAFT_PACK_ROOT = DOMAIN_ROOT / "content" / "judgment" / "lumi-conditional-reasoning-v0"

PACK_ID = "lumi-conditional-reasoning-v0"
PACK_VERSION = "0.1.0-draft"
REVIEW_STATUS = "draft_unreviewed"
CONTENT_ORIGIN = "original_lumi"
CONTENT_LICENSE = "CC-BY-4.0"

REQUIRED_ARTIFACTS = {
    "LICENSE-CONTENT.md",
    "README.md",
    "skill-graph.json",
    "misconception-taxonomy.json",
    "records.json",
}
REQUIRED_SKILL_IDS = {
    "xingce.judgment.conditional.language_direction",
    "xingce.judgment.conditional.necessary_sufficient_role",
    "xingce.judgment.conditional.inference_validity",
}
REQUIRED_MISCONCEPTION_IDS = {"M-DIR", "M-ROLE", "M-INF", "M-READ"}
EXPECTED_RECORD_IDS = {
    "D01", "D02", "P01", "P02", "P03", "T01", "T02", "T03", "V01", "V02", "R01", "R02",
}
EXPECTED_ROLE_COUNTS = {
    "entry_diagnostic": 1,
    "routing_diagnostic": 1,
    "probe": 3,
    "teaching_asset": 3,
    "independent_transfer": 2,
    "delayed_review": 2,
}
_SHA256_HEX_LENGTH = 64

# A release is deliberately a different contract from the authored draft above.
# In particular, it is never enough to flip a draft's ``status`` field: a
# release must carry two independently attributable attestations that bind the
# exact reviewed payload.  This module intentionally does not register a
# reviewed pack with a runtime catalog; it only makes a reviewed pack safe to
# load by a future registration layer.
RELEASE_STATUS = "release_ready"
RELEASE_RUNTIME_REGISTRATION = "allowed_after_human_review"
RELEASE_DISTRIBUTION = "release_distribution_allowed"
REVIEW_KINDS = frozenset({"logic", "editorial_rights"})
_RELEASE_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "pack_id",
        "pack_version",
        "status",
        "release_ready",
        "runtime_registration",
        "purpose",
        "scope",
        "rights",
        "human_review_gate",
        "checksum_policy",
        "artifacts",
    }
)
_RELEASE_RIGHTS_KEYS = frozenset(
    {
        "content_origin",
        "external_source_materials",
        "license",
        "license_url",
        "copyright_notice",
        "distribution",
        "prohibited_materials",
    }
)
_RELEASE_GATE_KEYS = frozenset({"required", "production_load_allowed", "policy", "review_attestations"})
_RELEASE_ATTESTATION_KEYS = frozenset(
    {
        "review_kind",
        "status",
        "reviewer_id",
        "reviewed_at",
        "checklist",
        "manifest_sha256",
        "artifact_hashes",
        "record_hashes",
    }
)
_ARTIFACT_KEYS = frozenset({"path", "sha256"})
_RELEASE_RECORD_DOCUMENT_KEYS = frozenset(
    {"schema_version", "pack_id", "pack_version", "review_status", "records"}
)
_COMMON_RECORD_KEYS = frozenset(
    {
        "record_id",
        "role",
        "title",
        "target_skill_ids",
        "candidate_misconception_ids",
        "independence_group",
        "content_origin",
        "review_status",
        "record_sha256",
    }
)
_ASSESSMENT_RECORD_KEYS = _COMMON_RECORD_KEYS | frozenset(
    {"prompt", "response_mode", "options", "correct_option", "formalization", "answer_proof", "distractor_map"}
)
_TEACHING_RECORD_KEYS = _COMMON_RECORD_KEYS | frozenset(
    {"teaching_strategy", "teaching_content", "logic_rule", "selected_when"}
)
_ROLE_OPTIONAL_KEYS = {
    "entry_diagnostic": frozenset(),
    "routing_diagnostic": frozenset(),
    "probe": frozenset({"discriminates"}),
    "independent_transfer": frozenset({"requires_no_hints"}),
    "delayed_review": frozenset({"eligible_after_transfer_ids", "scheduled_after", "requires_no_hints"}),
}
_PUBLIC_ASSESSMENT_KEYS = frozenset({"record_id", "role", "title", "prompt", "response_mode", "options"})
_PUBLIC_TEACHING_KEYS = frozenset({"record_id", "role", "title", "teaching_strategy", "teaching_content", "logic_rule"})


class ReasoningPackError(ContractError):
    """The draft-only conditional-reasoning pack violated its contract."""


def canonical_json_sha256(value: Any) -> str:
    """Hash JSON semantic content independently of JSON indentation or key order."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def record_sha256(record: Mapping[str, Any]) -> str:
    """Hash an individual record without its derived integrity field."""

    content = copy.deepcopy(dict(record))
    content.pop("record_sha256", None)
    return canonical_json_sha256(content)


def reviewed_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash the reviewed manifest payload without recursive attestations.

    An attestation cannot include the byte hash of a manifest that embeds the
    attestation itself.  The signed/reviewed payload is therefore the canonical
    manifest with only ``human_review_gate.review_attestations`` removed.  It
    still binds every release policy, identity, artifact checksum, and content
    declaration.  Attestations are independently schema-checked below.
    """

    content = copy.deepcopy(dict(manifest))
    gate = content.get("human_review_gate")
    if isinstance(gate, dict):
        gate.pop("review_attestations", None)
    return canonical_json_sha256(content)


def _require_exact_keys(mapping: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    actual = set(mapping)
    unknown = sorted(actual - allowed)
    missing = sorted(allowed - actual)
    if unknown:
        raise ReasoningPackError(f"{label} contains unknown fields: {', '.join(unknown)}")
    if missing:
        raise ReasoningPackError(f"{label} is missing required fields: {', '.join(missing)}")


def _validate_lower_sha256(value: Any, label: str) -> str:
    digest = _nonempty(value, label)
    if len(digest) != _SHA256_HEX_LENGTH or any(char not in "0123456789abcdef" for char in digest):
        raise ReasoningPackError(f"{label} must be lower-case SHA-256")
    return digest


def _validate_reviewed_timestamp(value: Any) -> str:
    timestamp = _nonempty(value, "attestation reviewed_at")
    if not timestamp.endswith("Z"):
        raise ReasoningPackError("attestation reviewed_at must be UTC RFC3339 ending in Z")
    try:
        parsed = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as exc:
        raise ReasoningPackError("attestation reviewed_at must be UTC RFC3339") from exc
    if parsed.tzinfo != timezone.utc:
        raise ReasoningPackError("attestation reviewed_at must be UTC")
    # ``isoformat`` permits a few values RFC3339 does not (for example a date
    # without time), so require a time separator as well.
    if "T" not in timestamp:
        raise ReasoningPackError("attestation reviewed_at must include a time")
    return timestamp


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReasoningPackError(f"{label} is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ReasoningPackError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReasoningPackError(f"{label} must be a JSON object")
    return value


def _require(mapping: Mapping[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    value = mapping.get(key)
    if not isinstance(value, kind):
        raise ReasoningPackError(f"missing or invalid {key}")
    return value


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReasoningPackError(f"{label} must be a non-empty string")
    return value


def _artifact_path(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts or relative_path not in REQUIRED_ARTIFACTS:
        raise ReasoningPackError(f"invalid artifact path: {relative_path}")
    return root / candidate


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack_checksums(root: Path = DEFAULT_DRAFT_PACK_ROOT) -> dict[str, str]:
    """Return deterministic byte-level checksums, including the manifest itself."""

    root = Path(root)
    manifest = _read_json(root / "manifest.json", "manifest")
    result = {"manifest.json": _file_sha256(root / "manifest.json")}
    for artifact in _require(manifest, "artifacts", list):
        if not isinstance(artifact, Mapping):
            raise ReasoningPackError("artifact must be an object")
        relative_path = _nonempty(artifact.get("path"), "artifact path")
        result[relative_path] = _file_sha256(_artifact_path(root, relative_path))
    return dict(sorted(result.items()))


def _validate_manifest(manifest: Mapping[str, Any], root: Path) -> None:
    if manifest.get("schema_version") != "lumi.reasoning-domain-pack.v0":
        raise ReasoningPackError("unsupported reasoning-pack schema")
    if manifest.get("pack_id") != PACK_ID or manifest.get("pack_version") != PACK_VERSION:
        raise ReasoningPackError("unexpected pack identity")
    if manifest.get("status") != REVIEW_STATUS:
        raise ReasoningPackError("draft pack must remain draft_unreviewed")
    if manifest.get("release_ready") is not False:
        raise ReasoningPackError("draft pack must not be release_ready")
    if manifest.get("runtime_registration") != "forbidden_until_human_review":
        raise ReasoningPackError("draft pack must forbid runtime registration")

    rights = _require(manifest, "rights", dict)
    if rights.get("content_origin") != CONTENT_ORIGIN or rights.get("external_source_materials") != "none":
        raise ReasoningPackError("draft content must be original and source-free")
    if rights.get("license") != CONTENT_LICENSE:
        raise ReasoningPackError("draft content must declare CC-BY-4.0")
    if rights.get("distribution") != "draft_no_distribution":
        raise ReasoningPackError("draft content must not be distributed")

    gate = _require(manifest, "human_review_gate", dict)
    if gate.get("required") is not True or gate.get("production_load_allowed") is not False:
        raise ReasoningPackError("human review gate must block production loading")
    reviews = _require(gate, "required_reviews", list)
    kinds = set()
    for review in reviews:
        if not isinstance(review, Mapping):
            raise ReasoningPackError("review gate record must be an object")
        kind = _nonempty(review.get("review_kind"), "review kind")
        kinds.add(kind)
        if review.get("status") != "pending":
            raise ReasoningPackError("unreviewed pack cannot contain an approved review")
        checks = _require(review, "required_checks", list)
        if not checks or any(not isinstance(check, str) or not check.strip() for check in checks):
            raise ReasoningPackError("review gate requires named checks")
    if kinds != {"logic", "editorial_rights"}:
        raise ReasoningPackError("draft requires logic and editorial_rights review gates")

    artifacts = _require(manifest, "artifacts", list)
    artifact_map: dict[str, str] = {}
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise ReasoningPackError("artifact must be an object")
        relative_path = _nonempty(artifact.get("path"), "artifact path")
        expected = _nonempty(artifact.get("sha256"), "artifact sha256")
        if len(expected) != _SHA256_HEX_LENGTH or any(char not in "0123456789abcdef" for char in expected):
            raise ReasoningPackError("artifact sha256 must be lower-case SHA-256")
        if relative_path in artifact_map:
            raise ReasoningPackError("duplicate artifact path")
        artifact_map[relative_path] = expected
    if set(artifact_map) != REQUIRED_ARTIFACTS:
        raise ReasoningPackError("manifest artifact set is incomplete or unexpected")
    for relative_path, expected in artifact_map.items():
        actual = _file_sha256(_artifact_path(root, relative_path))
        if actual != expected:
            raise ReasoningPackError(f"artifact checksum mismatch: {relative_path}")


def _validate_skill_graph(document: Mapping[str, Any]) -> set[str]:
    if document.get("schema_version") != "lumi.reasoning-skill-graph.v0":
        raise ReasoningPackError("unsupported skill graph schema")
    if document.get("pack_id") != PACK_ID or document.get("pack_version") != PACK_VERSION:
        raise ReasoningPackError("skill graph pack identity mismatch")
    if document.get("review_status") != REVIEW_STATUS:
        raise ReasoningPackError("skill graph must remain draft_unreviewed")
    skills = _require(document, "skills", list)
    indexed: dict[str, Mapping[str, Any]] = {}
    for skill in skills:
        if not isinstance(skill, Mapping):
            raise ReasoningPackError("skill must be an object")
        skill_id = _nonempty(skill.get("skill_id"), "skill id")
        if skill_id in indexed:
            raise ReasoningPackError("duplicate skill id")
        indexed[skill_id] = skill
        for key in ("label", "description", "mastery_claim"):
            _nonempty(skill.get(key), f"skill {key}")
        prerequisites = _require(skill, "prerequisite_skill_ids", list)
        if len(prerequisites) != len(set(prerequisites)):
            raise ReasoningPackError("duplicate skill prerequisite")
    if set(indexed) != REQUIRED_SKILL_IDS:
        raise ReasoningPackError("skill graph does not match conditional v0 scope")
    for skill_id, skill in indexed.items():
        prerequisites = set(skill["prerequisite_skill_ids"])
        if not prerequisites.issubset(indexed) or skill_id in prerequisites:
            raise ReasoningPackError("invalid skill prerequisite")
    return set(indexed)


def _validate_taxonomy(document: Mapping[str, Any], skill_ids: set[str]) -> set[str]:
    if document.get("schema_version") != "lumi.reasoning-misconception-taxonomy.v0":
        raise ReasoningPackError("unsupported misconception taxonomy schema")
    if document.get("pack_id") != PACK_ID or document.get("pack_version") != PACK_VERSION:
        raise ReasoningPackError("taxonomy pack identity mismatch")
    if document.get("review_status") != REVIEW_STATUS:
        raise ReasoningPackError("taxonomy must remain draft_unreviewed")
    candidates = _require(document, "candidate_misconceptions", list)
    indexed: dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ReasoningPackError("misconception must be an object")
        candidate_id = _nonempty(candidate.get("misconception_id"), "misconception id")
        if candidate_id in indexed:
            raise ReasoningPackError("duplicate misconception id")
        indexed[candidate_id] = candidate
        if candidate.get("candidate_only") is not True:
            raise ReasoningPackError("misconceptions must remain candidate-only")
        for key in ("label", "description", "minimum_discriminating_evidence"):
            _nonempty(candidate.get(key), f"misconception {key}")
        signals = _require(candidate, "observable_signals", list)
        if not signals or any(not isinstance(signal, str) or not signal.strip() for signal in signals):
            raise ReasoningPackError("misconception requires observable signals")
    if set(indexed) != REQUIRED_MISCONCEPTION_IDS:
        raise ReasoningPackError("taxonomy does not match conditional v0 scope")
    if skill_ids != REQUIRED_SKILL_IDS:
        raise ReasoningPackError("taxonomy validation requires complete skill graph")
    return set(indexed)


def _validate_assessment(record: Mapping[str, Any]) -> None:
    for key in ("prompt", "formalization", "answer_proof"):
        _nonempty(record.get(key), f"assessment {key}")
    if record.get("response_mode") != "single_choice":
        raise ReasoningPackError("assessment records must use deterministic single_choice")
    options = _require(record, "options", dict)
    if set(options) != {"A", "B", "C", "D"}:
        raise ReasoningPackError("assessment records require exactly A-D options")
    if any(not isinstance(text, str) or not text.strip() for text in options.values()):
        raise ReasoningPackError("assessment option text must be non-empty")
    correct_option = _nonempty(record.get("correct_option"), "correct option")
    if correct_option not in options:
        raise ReasoningPackError("correct option must be present")
    distractor_map = _require(record, "distractor_map", dict)
    if set(distractor_map) != set(options) - {correct_option}:
        raise ReasoningPackError("every and only distractors must be mapped")
    if any(not isinstance(reason, str) or not reason.strip() for reason in distractor_map.values()):
        raise ReasoningPackError("distractor reason must be non-empty")


def _validate_teaching_asset(record: Mapping[str, Any]) -> None:
    for key in ("teaching_strategy", "teaching_content", "logic_rule", "selected_when"):
        _nonempty(record.get(key), f"teaching asset {key}")
    forbidden = {"prompt", "options", "correct_option", "answer_proof", "distractor_map"}
    if forbidden.intersection(record):
        raise ReasoningPackError("teaching asset must not masquerade as a scored item")


def _validate_records(
    document: Mapping[str, Any],
    skill_ids: set[str],
    misconception_ids: set[str],
) -> list[Mapping[str, Any]]:
    if document.get("schema_version") != "lumi.reasoning-domain-records.v0":
        raise ReasoningPackError("unsupported records schema")
    if document.get("pack_id") != PACK_ID or document.get("pack_version") != PACK_VERSION:
        raise ReasoningPackError("records pack identity mismatch")
    if document.get("review_status") != REVIEW_STATUS:
        raise ReasoningPackError("records document must remain draft_unreviewed")
    records = _require(document, "records", list)
    if len(records) != len(EXPECTED_RECORD_IDS):
        raise ReasoningPackError("conditional v0 must contain exactly twelve compact records")

    indexed: dict[str, Mapping[str, Any]] = {}
    groups: set[str] = set()
    role_counts: dict[str, int] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ReasoningPackError("record must be an object")
        record_id = _nonempty(record.get("record_id"), "record id")
        if record_id in indexed:
            raise ReasoningPackError("duplicate record id")
        indexed[record_id] = record
        role = _nonempty(record.get("role"), "record role")
        role_counts[role] = role_counts.get(role, 0) + 1
        _nonempty(record.get("title"), "record title")
        if record.get("content_origin") != CONTENT_ORIGIN:
            raise ReasoningPackError("record must declare original_lumi content")
        if record.get("review_status") != REVIEW_STATUS:
            raise ReasoningPackError("every record must remain draft_unreviewed")
        expected_hash = _nonempty(record.get("record_sha256"), "record sha256")
        if len(expected_hash) != _SHA256_HEX_LENGTH or any(char not in "0123456789abcdef" for char in expected_hash):
            raise ReasoningPackError("record sha256 must be lower-case SHA-256")
        if record_sha256(record) != expected_hash:
            raise ReasoningPackError(f"record checksum mismatch: {record_id}")

        target_skill_ids = _require(record, "target_skill_ids", list)
        if not target_skill_ids or len(target_skill_ids) != len(set(target_skill_ids)):
            raise ReasoningPackError("record must have unique target skills")
        if not set(target_skill_ids).issubset(skill_ids):
            raise ReasoningPackError("record references unknown target skill")
        targets = _require(record, "candidate_misconception_ids", list)
        if not targets or len(targets) != len(set(targets)):
            raise ReasoningPackError("record must have unique candidate misconceptions")
        if not set(targets).issubset(misconception_ids):
            raise ReasoningPackError("record references unknown misconception")

        group = _nonempty(record.get("independence_group"), "independence group")
        if group in groups:
            raise ReasoningPackError("each compact record needs a distinct independence group")
        groups.add(group)

        if role == "teaching_asset":
            _validate_teaching_asset(record)
        elif role in EXPECTED_ROLE_COUNTS:
            _validate_assessment(record)
        else:
            raise ReasoningPackError("unsupported record role")

        if role == "probe":
            discriminates = _require(record, "discriminates", list)
            if len(discriminates) < 2:
                raise ReasoningPackError(
                    "probe must distinguish at least two candidate explanations"
                )
            if set(discriminates) != set(targets):
                raise ReasoningPackError("probe must explicitly discriminate all its candidate targets")
        if role in {"independent_transfer", "delayed_review"}:
            if record.get("requires_no_hints") is not True:
                raise ReasoningPackError("transfer and delayed review must require no hints")

    if set(indexed) != EXPECTED_RECORD_IDS:
        raise ReasoningPackError("records do not match the approved draft inventory")
    if role_counts != EXPECTED_ROLE_COUNTS:
        raise ReasoningPackError("records do not provide the required diagnostic-to-review roles")

    transfer_ids = {record_id for record_id, record in indexed.items() if record["role"] == "independent_transfer"}
    for record in indexed.values():
        if record["role"] != "delayed_review":
            continue
        eligible = _require(record, "eligible_after_transfer_ids", list)
        if not eligible or not set(eligible).issubset(transfer_ids):
            raise ReasoningPackError("delayed review must bind to an independent transfer")
        if record.get("scheduled_after") != "P3D":
            raise ReasoningPackError("draft delayed reviews must use the authored P3D interval")
    return list(indexed.values())


def _release_artifact_path(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or relative_path == "manifest.json"
        or ".." in candidate.parts
        or candidate.name in {"", "."}
    ):
        raise ReasoningPackError(f"invalid release artifact path: {relative_path}")
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ReasoningPackError(f"release artifact escapes pack root: {relative_path}") from exc
    if not resolved.is_file():
        raise ReasoningPackError(f"release artifact is missing: {relative_path}")
    return resolved


def _validate_release_artifacts(manifest: Mapping[str, Any], root: Path) -> dict[str, str]:
    artifacts = _require(manifest, "artifacts", list)
    if not artifacts:
        raise ReasoningPackError("release manifest needs artifacts")
    expected_hashes: dict[str, str] = {}
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise ReasoningPackError("release artifact must be an object")
        _require_exact_keys(artifact, _ARTIFACT_KEYS, "release artifact")
        relative_path = _nonempty(artifact.get("path"), "release artifact path")
        if relative_path in expected_hashes:
            raise ReasoningPackError("duplicate release artifact path")
        expected_hashes[relative_path] = _validate_lower_sha256(artifact.get("sha256"), "release artifact sha256")

    required = {"skill-graph.json", "misconception-taxonomy.json", "records.json"}
    if not required.issubset(expected_hashes):
        raise ReasoningPackError("release manifest lacks required reasoning artifacts")
    for relative_path, expected in expected_hashes.items():
        actual = _file_sha256(_release_artifact_path(root, relative_path))
        if actual != expected:
            raise ReasoningPackError(f"release artifact checksum mismatch: {relative_path}")
    return dict(sorted(expected_hashes.items()))


def _validate_release_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ReasoningPackError(f"{label} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ReasoningPackError(f"{label} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ReasoningPackError(f"{label} must not contain duplicates")
    return list(value)


def _validate_release_manifest(manifest: Mapping[str, Any], root: Path) -> dict[str, str]:
    _require_exact_keys(manifest, _RELEASE_MANIFEST_KEYS, "release manifest")
    if manifest.get("schema_version") != "lumi.reasoning-domain-pack.v0":
        raise ReasoningPackError("unsupported release reasoning-pack schema")
    _nonempty(manifest.get("pack_id"), "release pack id")
    _nonempty(manifest.get("pack_version"), "release pack version")
    if manifest.get("status") != RELEASE_STATUS or manifest.get("release_ready") is not True:
        raise ReasoningPackError("reviewed loader only accepts release_ready packs")
    if manifest.get("runtime_registration") != RELEASE_RUNTIME_REGISTRATION:
        raise ReasoningPackError("release pack must allow registration only after human review")
    _nonempty(manifest.get("purpose"), "release pack purpose")

    scope = _require(manifest, "scope", dict)
    _require_exact_keys(scope, frozenset({"included", "excluded"}), "release scope")
    _validate_release_list(scope.get("included"), "release scope included")
    if not isinstance(scope.get("excluded"), list) or any(
        not isinstance(item, str) or not item.strip() for item in scope["excluded"]
    ):
        raise ReasoningPackError("release scope excluded must contain non-empty strings")

    rights = _require(manifest, "rights", dict)
    _require_exact_keys(rights, _RELEASE_RIGHTS_KEYS, "release rights")
    for key in ("content_origin", "external_source_materials", "license", "license_url", "copyright_notice"):
        _nonempty(rights.get(key), f"release rights {key}")
    if rights.get("distribution") != RELEASE_DISTRIBUTION:
        raise ReasoningPackError("release rights must explicitly allow reviewed distribution")
    _validate_release_list(rights.get("prohibited_materials"), "release prohibited materials")

    policy = _require(manifest, "checksum_policy", dict)
    _require_exact_keys(
        policy,
        frozenset({"artifact_algorithm", "record_algorithm", "canonical_json"}),
        "release checksum policy",
    )
    for key in policy:
        _nonempty(policy.get(key), f"release checksum policy {key}")

    return _validate_release_artifacts(manifest, root)


def _validate_release_skill_graph(document: Mapping[str, Any], manifest: Mapping[str, Any]) -> set[str]:
    _require_exact_keys(
        document,
        frozenset({"schema_version", "pack_id", "pack_version", "review_status", "skills"}),
        "release skill graph",
    )
    if document.get("schema_version") != "lumi.reasoning-skill-graph.v0":
        raise ReasoningPackError("unsupported release skill graph schema")
    if document.get("pack_id") != manifest["pack_id"] or document.get("pack_version") != manifest["pack_version"]:
        raise ReasoningPackError("release skill graph identity mismatch")
    if document.get("review_status") != RELEASE_STATUS:
        raise ReasoningPackError("release skill graph must be release_ready")
    skills = _require(document, "skills", list)
    if not skills:
        raise ReasoningPackError("release skill graph must contain skills")
    indexed: dict[str, Mapping[str, Any]] = {}
    allowed = frozenset({"skill_id", "label", "description", "mastery_claim", "prerequisite_skill_ids"})
    for skill in skills:
        if not isinstance(skill, Mapping):
            raise ReasoningPackError("release skill must be an object")
        _require_exact_keys(skill, allowed, "release skill")
        skill_id = _nonempty(skill.get("skill_id"), "release skill id")
        if skill_id in indexed:
            raise ReasoningPackError("duplicate release skill id")
        indexed[skill_id] = skill
        for key in ("label", "description", "mastery_claim"):
            _nonempty(skill.get(key), f"release skill {key}")
        prerequisites = _require(skill, "prerequisite_skill_ids", list)
        if len(prerequisites) != len(set(prerequisites)) or any(
            not isinstance(item, str) or not item.strip() for item in prerequisites
        ):
            raise ReasoningPackError("release skill prerequisites are invalid")
    for skill_id, skill in indexed.items():
        prerequisites = set(skill["prerequisite_skill_ids"])
        if not prerequisites.issubset(indexed) or skill_id in prerequisites:
            raise ReasoningPackError("release skill prerequisite references an invalid skill")
    return set(indexed)


def _validate_release_taxonomy(
    document: Mapping[str, Any], manifest: Mapping[str, Any], skill_ids: set[str]
) -> set[str]:
    _require_exact_keys(
        document,
        frozenset({"schema_version", "pack_id", "pack_version", "review_status", "candidate_misconceptions"}),
        "release misconception taxonomy",
    )
    if document.get("schema_version") != "lumi.reasoning-misconception-taxonomy.v0":
        raise ReasoningPackError("unsupported release misconception taxonomy schema")
    if document.get("pack_id") != manifest["pack_id"] or document.get("pack_version") != manifest["pack_version"]:
        raise ReasoningPackError("release misconception taxonomy identity mismatch")
    if document.get("review_status") != RELEASE_STATUS:
        raise ReasoningPackError("release misconception taxonomy must be release_ready")
    candidates = _require(document, "candidate_misconceptions", list)
    if not candidates:
        raise ReasoningPackError("release misconception taxonomy must contain candidates")
    allowed = frozenset(
        {
            "misconception_id",
            "label",
            "candidate_only",
            "description",
            "observable_signals",
            "minimum_discriminating_evidence",
            "preferred_teaching_asset_id",
        }
    )
    indexed: dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ReasoningPackError("release misconception must be an object")
        _require_exact_keys(candidate, allowed, "release misconception")
        candidate_id = _nonempty(candidate.get("misconception_id"), "release misconception id")
        if candidate_id in indexed:
            raise ReasoningPackError("duplicate release misconception id")
        indexed[candidate_id] = candidate
        if candidate.get("candidate_only") is not True:
            raise ReasoningPackError("release misconceptions must remain candidate-only")
        for key in ("label", "description", "minimum_discriminating_evidence"):
            _nonempty(candidate.get(key), f"release misconception {key}")
        preferred_asset = candidate.get("preferred_teaching_asset_id")
        if preferred_asset is not None and (not isinstance(preferred_asset, str) or not preferred_asset.strip()):
            raise ReasoningPackError("release misconception preferred_teaching_asset_id must be a non-empty string or null")
        _validate_release_list(candidate.get("observable_signals"), "release misconception signals")
    if not skill_ids:
        raise ReasoningPackError("release taxonomy requires a skill graph")
    return set(indexed)


def _validate_release_record(
    record: Mapping[str, Any],
    *,
    content_origin: str,
    skill_ids: set[str],
    misconception_ids: set[str],
) -> None:
    role = _nonempty(record.get("role"), "release record role")
    if role == "teaching_asset":
        allowed = _TEACHING_RECORD_KEYS
    elif role in _ROLE_OPTIONAL_KEYS:
        allowed = _ASSESSMENT_RECORD_KEYS | _ROLE_OPTIONAL_KEYS[role]
    else:
        raise ReasoningPackError("unsupported release record role")
    _require_exact_keys(record, allowed, f"release record {record.get('record_id', '<unknown>')}")
    for key in ("record_id", "title", "independence_group"):
        _nonempty(record.get(key), f"release record {key}")
    if record.get("content_origin") != content_origin:
        raise ReasoningPackError("release record content origin mismatch")
    if record.get("review_status") != RELEASE_STATUS:
        raise ReasoningPackError("release record must be release_ready")
    expected_hash = _validate_lower_sha256(record.get("record_sha256"), "release record sha256")
    if record_sha256(record) != expected_hash:
        raise ReasoningPackError(f"release record checksum mismatch: {record['record_id']}")
    target_skill_ids = _validate_release_list(record.get("target_skill_ids"), "release record target skills")
    if not set(target_skill_ids).issubset(skill_ids):
        raise ReasoningPackError("release record references unknown target skill")
    targets = _validate_release_list(record.get("candidate_misconception_ids"), "release record candidate misconceptions")
    if not set(targets).issubset(misconception_ids):
        raise ReasoningPackError("release record references unknown misconception")

    if role == "teaching_asset":
        _validate_teaching_asset(record)
        return
    _validate_assessment(record)
    if role == "probe":
        discriminates = _validate_release_list(record.get("discriminates"), "release probe discriminates")
        if len(discriminates) < 2:
            raise ReasoningPackError(
                "release probe must distinguish at least two candidate explanations"
            )
        if set(discriminates) != set(targets):
            raise ReasoningPackError("release probe must discriminate all candidate targets")
    if role in {"independent_transfer", "delayed_review"} and record.get("requires_no_hints") is not True:
        raise ReasoningPackError("release transfer and delayed review must require no hints")
    if role == "delayed_review":
        _validate_release_list(record.get("eligible_after_transfer_ids"), "release delayed review eligible transfers")
        _nonempty(record.get("scheduled_after"), "release delayed review schedule")


def _validate_release_records(
    document: Mapping[str, Any],
    manifest: Mapping[str, Any],
    skill_ids: set[str],
    misconception_ids: set[str],
) -> list[Mapping[str, Any]]:
    _require_exact_keys(document, _RELEASE_RECORD_DOCUMENT_KEYS, "release records document")
    if document.get("schema_version") != "lumi.reasoning-domain-records.v0":
        raise ReasoningPackError("unsupported release records schema")
    if document.get("pack_id") != manifest["pack_id"] or document.get("pack_version") != manifest["pack_version"]:
        raise ReasoningPackError("release records identity mismatch")
    if document.get("review_status") != RELEASE_STATUS:
        raise ReasoningPackError("release records document must be release_ready")
    records = _require(document, "records", list)
    if not records:
        raise ReasoningPackError("release records document must contain records")
    indexed: set[str] = set()
    groups: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ReasoningPackError("release record must be an object")
        _validate_release_record(
            record,
            content_origin=manifest["rights"]["content_origin"],
            skill_ids=skill_ids,
            misconception_ids=misconception_ids,
        )
        record_id = record["record_id"]
        group = record["independence_group"]
        if record_id in indexed:
            raise ReasoningPackError("duplicate release record id")
        if group in groups:
            raise ReasoningPackError("duplicate release independence group")
        indexed.add(record_id)
        groups.add(group)
    transfer_ids = {record["record_id"] for record in records if record["role"] == "independent_transfer"}
    for record in records:
        if record["role"] == "delayed_review" and not set(record["eligible_after_transfer_ids"]).issubset(transfer_ids):
            raise ReasoningPackError("release delayed review references an unknown transfer")
    return list(records)


def _validate_review_attestations(
    manifest: Mapping[str, Any], artifact_hashes: Mapping[str, str], records: list[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    gate = _require(manifest, "human_review_gate", dict)
    _require_exact_keys(gate, _RELEASE_GATE_KEYS, "release human review gate")
    if gate.get("required") is not True or gate.get("production_load_allowed") is not True:
        raise ReasoningPackError("reviewed release must require and allow completed human review")
    _nonempty(gate.get("policy"), "release review policy")
    attestations = _require(gate, "review_attestations", list)
    if len(attestations) != len(REVIEW_KINDS):
        raise ReasoningPackError("reviewed release requires exactly logic and editorial_rights attestations")
    expected_manifest_hash = reviewed_manifest_sha256(manifest)
    expected_record_hashes = {record["record_id"]: record["record_sha256"] for record in records}
    seen_kinds: set[str] = set()
    reviewer_ids: set[str] = set()
    for attestation in attestations:
        if not isinstance(attestation, Mapping):
            raise ReasoningPackError("review attestation must be an object")
        _require_exact_keys(attestation, _RELEASE_ATTESTATION_KEYS, "review attestation")
        kind = _nonempty(attestation.get("review_kind"), "attestation review kind")
        if kind not in REVIEW_KINDS or kind in seen_kinds:
            raise ReasoningPackError("release must have one logic and one editorial_rights attestation")
        seen_kinds.add(kind)
        if attestation.get("status") != "approved":
            raise ReasoningPackError("release attestation must be approved")
        reviewer_id = _nonempty(attestation.get("reviewer_id"), "attestation reviewer id")
        if reviewer_id in reviewer_ids:
            raise ReasoningPackError("logic and editorial_rights reviews require different reviewer_id values")
        reviewer_ids.add(reviewer_id)
        _validate_reviewed_timestamp(attestation.get("reviewed_at"))
        _validate_release_list(attestation.get("checklist"), "attestation checklist")
        if _validate_lower_sha256(attestation.get("manifest_sha256"), "attestation manifest sha256") != expected_manifest_hash:
            raise ReasoningPackError("review attestation manifest hash does not match reviewed manifest")
        artifact_binding = _require(attestation, "artifact_hashes", dict)
        if artifact_binding != artifact_hashes:
            raise ReasoningPackError("review attestation artifact hashes do not match exact manifest artifacts")
        if any(not isinstance(path, str) or not isinstance(digest, str) for path, digest in artifact_binding.items()):
            raise ReasoningPackError("review attestation artifact hashes must be string mappings")
        record_binding = _require(attestation, "record_hashes", dict)
        if record_binding != expected_record_hashes:
            raise ReasoningPackError("review attestation record hashes do not match exact records")
        if any(not isinstance(record_id, str) or not isinstance(digest, str) for record_id, digest in record_binding.items()):
            raise ReasoningPackError("review attestation record hashes must be string mappings")
    if seen_kinds != REVIEW_KINDS:
        raise ReasoningPackError("reviewed release requires logic and editorial_rights attestations")
    return list(attestations)


def validate_reviewed_reasoning_pack(root: Path) -> dict[str, Any]:
    """Fail closed unless a future pack is fully reviewed and hash-bound.

    This validator intentionally rejects the repository draft and never performs
    catalog registration.  It is suitable for a future, explicit packaging step
    after two people have reviewed a copied/released pack.
    """

    root = Path(root)
    manifest = _read_json(root / "manifest.json", "release manifest")
    artifact_hashes = _validate_release_manifest(manifest, root)
    skill_ids = _validate_release_skill_graph(_read_json(root / "skill-graph.json", "release skill graph"), manifest)
    misconception_ids = _validate_release_taxonomy(
        _read_json(root / "misconception-taxonomy.json", "release misconception taxonomy"), manifest, skill_ids
    )
    records = _validate_release_records(
        _read_json(root / "records.json", "release records"), manifest, skill_ids, misconception_ids
    )
    attestations = _validate_review_attestations(manifest, artifact_hashes, records)
    return {
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "status": RELEASE_STATUS,
        "production_load_allowed": True,
        "record_count": len(records),
        "reviewed_manifest_sha256": reviewed_manifest_sha256(manifest),
        "artifact_hashes": dict(artifact_hashes),
        "review_kinds": sorted(attestation["review_kind"] for attestation in attestations),
    }


def _project_reviewed_record(record: Mapping[str, Any], projection: Literal["public", "private"]) -> dict[str, Any]:
    if projection == "private":
        return copy.deepcopy(dict(record))
    if projection != "public":
        raise ReasoningPackError("reviewed pack projection must be public or private")
    allowed = _PUBLIC_TEACHING_KEYS if record["role"] == "teaching_asset" else _PUBLIC_ASSESSMENT_KEYS
    return {key: copy.deepcopy(record[key]) for key in sorted(allowed) if key in record}


def load_reviewed_reasoning_pack(
    root: Path, *, projection: Literal["public", "private"] = "public"
) -> dict[str, Any]:
    """Load only a validated release into an explicit safe projection.

    The public projection omits scoring keys and teaching-routing internals; the
    private projection is for a future local scoring/policy boundary and must
    not be returned directly to a learner-facing renderer.
    """

    summary = validate_reviewed_reasoning_pack(root)
    document = _read_json(Path(root) / "records.json", "release records")
    return {
        "pack_id": summary["pack_id"],
        "pack_version": summary["pack_version"],
        "status": summary["status"],
        "projection": projection,
        "records": [_project_reviewed_record(record, projection) for record in document["records"]],
    }


def validate_reasoning_pack(root: Path = DEFAULT_DRAFT_PACK_ROOT) -> dict[str, Any]:
    """Validate the complete, intentionally unregistered draft Domain Pack."""

    root = Path(root)
    manifest = _read_json(root / "manifest.json", "manifest")
    _validate_manifest(manifest, root)
    skill_ids = _validate_skill_graph(_read_json(root / "skill-graph.json", "skill graph"))
    misconception_ids = _validate_taxonomy(
        _read_json(root / "misconception-taxonomy.json", "misconception taxonomy"),
        skill_ids,
    )
    records = _validate_records(_read_json(root / "records.json", "records"), skill_ids, misconception_ids)
    checksums = pack_checksums(root)
    return {
        "pack_id": PACK_ID,
        "pack_version": PACK_VERSION,
        "status": REVIEW_STATUS,
        "production_load_allowed": False,
        "record_count": len(records),
        "checksums": checksums,
    }


if __name__ == "__main__":
    print(json.dumps(validate_reasoning_pack(), ensure_ascii=False, sort_keys=True, indent=2))
