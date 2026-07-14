"""Validated authoring contract for every Lumi Xingce adaptive Domain Pack.

The conditional-logic pack predates this module; the remaining reviewed
runtime packs use this shared authoring contract:
it lets every other Xingce subtype describe its own deterministic scorer,
competing error hypotheses, discriminating probe, teaching asset, unseen
transfer, and delayed review without inheriting conditional-logic semantics.

It does not itself publish a pack.  A draft can be validated and evaluated,
but a runtime loader must reject it until two different human reviewers attest
to the immutable payload.  A separate owner decision may release that reviewed
payload while explicitly waiving type-by-type browser acceptance; that decision
never counts as human learning-effect evidence.
"""

from __future__ import annotations

import copy
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contract import ContractError
from .xingce_coverage import load_coverage_matrix


ADAPTIVE_PACK_SCHEMA = "lumi.xingce-adaptive-pack.v1"
ADAPTIVE_RECORDS_SCHEMA = "lumi.xingce-adaptive-records.v1"
ADAPTIVE_SKILLS_SCHEMA = "lumi.xingce-adaptive-skills.v1"
ADAPTIVE_TAXONOMY_SCHEMA = "lumi.xingce-adaptive-misconceptions.v1"
ADAPTIVE_POLICY_ID = "lumi.xingce-type-policy"
ADAPTIVE_POLICY_VERSION = "1.0.0"
DRAFT_STATUS = "draft_unreviewed"
RELEASE_STATUS = "release_ready"
_REVIEW_KINDS = frozenset({"logic", "editorial_rights"})
_ROLES = frozenset({"entry_diagnostic", "routing_diagnostic", "probe", "teaching_asset", "independent_transfer", "delayed_review"})
_ASSESSMENT_ROLES = frozenset({"entry_diagnostic", "routing_diagnostic", "probe", "independent_transfer", "delayed_review"})
_OUTCOMES = frozenset({"support", "refute", "insufficient"})
_FORMS = frozenset({"text_mcq", "numeric_or_mcq", "visual_mcq", "material_mcq"})
_SCORERS = frozenset({"exact_option_v1", "authored_numeric_v1"})
_REQUIRED_ARTIFACTS = frozenset({"records.json", "skill-graph.json", "misconceptions.json"})
_MATERIAL_KINDS = frozenset({"text", "table", "chart", "diagram", "composite"})


class XingceAdaptivePackError(ContractError):
    """A type-specific adaptive pack cannot safely enter the local pipeline."""


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def reviewed_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash the release manifest without the self-referential signatures.

    Review attestations sign the exact content-review intent, artifact hashes
    and review-evidence checksum.  The attestation list itself is excluded so a
    signature can name this digest without creating a hash cycle.  A later
    owner product-release decision is also excluded: content reviewers did not
    sign that operational decision, and adding it must not rewrite history.
    """
    signed = copy.deepcopy(manifest)
    gate = signed.get("human_review_gate")
    if isinstance(gate, dict):
        gate.pop("review_attestations", None)
    signed.pop("product_release", None)
    return canonical_json_sha256(signed)


def record_sha256(record: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(record))
    payload.pop("record_sha256", None)
    return canonical_json_sha256(payload)


def _require(mapping: Mapping[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    if key not in mapping or not isinstance(mapping[key], kind):
        raise XingceAdaptivePackError(f"missing or invalid {key}")
    return mapping[key]


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise XingceAdaptivePackError(f"{label} must be a non-empty string")
    return value


def _short_id(value: Any, label: str) -> str:
    result = _nonempty(value, label)
    if len(result) > 120 or any(char.isspace() for char in result):
        raise XingceAdaptivePackError(f"{label} must be a short token")
    return result


def _sha256(value: Any, label: str) -> str:
    digest = _nonempty(value, label)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise XingceAdaptivePackError(f"{label} must be a lower-case SHA-256")
    return digest


def _as_string_list(value: Any, label: str, *, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise XingceAdaptivePackError(f"{label} must contain at least {minimum} values")
    result = [_short_id(item, label) for item in value]
    if len(result) != len(set(result)):
        raise XingceAdaptivePackError(f"{label} must not contain duplicates")
    return result


def _coverage_subtype(subtype_id: str) -> Mapping[str, Any]:
    matrix = load_coverage_matrix()
    rows = [row for row in matrix["subtypes"] if row["id"] == subtype_id]
    if len(rows) != 1:
        raise XingceAdaptivePackError("pack subtype is not declared by the Xingce coverage matrix")
    return rows[0]


def _validate_manifest(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    if manifest.get("schema_version") != ADAPTIVE_PACK_SCHEMA:
        raise XingceAdaptivePackError("unsupported adaptive pack schema")
    _short_id(manifest.get("pack_id"), "pack_id")
    _short_id(manifest.get("pack_version"), "pack_version")
    status = manifest.get("status")
    if status not in {DRAFT_STATUS, RELEASE_STATUS}:
        raise XingceAdaptivePackError("pack status must be draft_unreviewed or release_ready")
    if manifest.get("release_ready") is not (status == RELEASE_STATUS):
        raise XingceAdaptivePackError("release_ready must exactly match the pack status")
    expected_registration = "allowed_after_human_review" if status == RELEASE_STATUS else "forbidden_until_human_review"
    if manifest.get("runtime_registration") != expected_registration:
        raise XingceAdaptivePackError("runtime registration is inconsistent with review status")

    subtype_id = _short_id(manifest.get("subtype_id"), "subtype_id")
    subtype = _coverage_subtype(subtype_id)
    if manifest.get("module_id") != subtype["module_id"]:
        raise XingceAdaptivePackError("pack module does not match its canonical subtype")
    if manifest.get("form") != subtype["form"] or manifest.get("form") not in _FORMS:
        raise XingceAdaptivePackError("pack form does not match its canonical subtype")
    if manifest.get("scorer") != subtype["scorer"] or manifest.get("scorer") not in _SCORERS:
        raise XingceAdaptivePackError("pack scorer does not match its canonical subtype")

    policy = _require(manifest, "policy", Mapping)
    if policy.get("policy_id") != ADAPTIVE_POLICY_ID or policy.get("policy_version") != ADAPTIVE_POLICY_VERSION:
        raise XingceAdaptivePackError("pack must bind the shared type policy exactly")
    if policy.get("candidate_status") != "unconfirmed":
        raise XingceAdaptivePackError("pack candidates must remain unconfirmed")
    if policy.get("state_commit_rule") != "independent_unassisted_transfer_only":
        raise XingceAdaptivePackError("pack must reserve state updates for independent transfer")

    rights = _require(manifest, "rights", Mapping)
    if rights.get("content_origin") not in {"original_lumi", "versioned_export"}:
        raise XingceAdaptivePackError("pack rights must name original or versioned-export content")
    if rights.get("distribution") not in {"draft_no_distribution", "release_distribution_allowed"}:
        raise XingceAdaptivePackError("pack rights distribution is invalid")
    if status == DRAFT_STATUS and rights.get("distribution") != "draft_no_distribution":
        raise XingceAdaptivePackError("draft pack cannot claim distributable content")
    if status == RELEASE_STATUS and rights.get("distribution") != "release_distribution_allowed":
        raise XingceAdaptivePackError("release pack must explicitly allow distribution")
    if rights.get("content_origin") == "versioned_export":
        _sha256(rights.get("source_export_sha256"), "source_export_sha256")
        _nonempty(rights.get("source_export_id"), "source_export_id")

    product_release = manifest.get("product_release")
    if product_release is not None:
        if status != RELEASE_STATUS or not isinstance(product_release, Mapping):
            raise XingceAdaptivePackError("product release requires reviewed release-ready content")
        if set(product_release) != {
            "state",
            "acceptance_basis",
            "accepted_at",
            "waived_gate",
            "human_effect_evidence",
            "claim_scope",
        }:
            raise XingceAdaptivePackError("product release declaration has unsupported fields")
        if product_release.get("state") != "released":
            raise XingceAdaptivePackError("product release state must be released")
        if product_release.get("acceptance_basis") != "owner_acceptance_waiver":
            raise XingceAdaptivePackError("product release must record owner_acceptance_waiver")
        try:
            date.fromisoformat(str(product_release.get("accepted_at", "")))
        except ValueError as exc:
            raise XingceAdaptivePackError("product release accepted_at must be an ISO date") from exc
        if product_release.get("waived_gate") != "type_by_type_human_local_browser_acceptance":
            raise XingceAdaptivePackError("product release must identify the waived human-local gate")
        if product_release.get("human_effect_evidence") != "unavailable":
            raise XingceAdaptivePackError("product release cannot claim human-effect evidence")
        if product_release.get("claim_scope") != "content_and_mechanism_availability_only":
            raise XingceAdaptivePackError("product release claim scope is not bounded")

    evidence = _require(manifest, "content_evidence", Mapping)
    expected_evidence = set(subtype["content_requirements"])
    if set(evidence) != expected_evidence:
        raise XingceAdaptivePackError("pack content evidence must cover its subtype requirements exactly")
    for key, value in evidence.items():
        if key in {"asset_checksum", "material_checksum"}:
            _sha256(value, key)
        else:
            _nonempty(value, f"content evidence {key}")

    gate = _require(manifest, "human_review_gate", Mapping)
    if gate.get("required") is not True or gate.get("production_load_allowed") is not (status == RELEASE_STATUS):
        raise XingceAdaptivePackError("human review gate is inconsistent with pack status")
    if status == DRAFT_STATUS:
        reviews = _require(gate, "required_reviews", list)
        kinds = set()
        for review in reviews:
            if not isinstance(review, Mapping) or review.get("status") != "pending":
                raise XingceAdaptivePackError("draft review gate must contain only pending reviews")
            kinds.add(review.get("review_kind"))
            _as_string_list(review.get("required_checks"), "review required_checks")
        if kinds != _REVIEW_KINDS:
            raise XingceAdaptivePackError("draft needs logic and editorial-rights reviews")
    else:
        attestations = _require(gate, "review_attestations", list)
        kinds: set[str] = set()
        reviewers: set[str] = set()
        expected_manifest_sha256 = reviewed_manifest_sha256(manifest)
        attested_manifest_hashes: set[str] = set()
        for attestation in attestations:
            if not isinstance(attestation, Mapping) or attestation.get("status") != "approved":
                raise XingceAdaptivePackError("release review attestations must be approved")
            kind = _nonempty(attestation.get("review_kind"), "review kind")
            reviewer = _nonempty(attestation.get("reviewer_id"), "reviewer_id")
            kinds.add(kind)
            reviewers.add(reviewer)
            attested_manifest_hashes.add(_sha256(attestation.get("manifest_sha256"), "reviewed manifest sha256"))
        if kinds != _REVIEW_KINDS or len(reviewers) != 2 or len(attestations) != 2:
            raise XingceAdaptivePackError("release requires two different human reviewer attestations")
        if attested_manifest_hashes != {expected_manifest_sha256}:
            raise XingceAdaptivePackError("reviewed manifest sha256 does not bind this exact release")

    artifacts = _require(manifest, "artifacts", list)
    artifact_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise XingceAdaptivePackError("artifact must be an object")
        path = _nonempty(artifact.get("path"), "artifact path")
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise XingceAdaptivePackError("artifact path must be local and relative")
        _sha256(artifact.get("sha256"), "artifact sha256")
        artifact_paths.add(path)
    if not _REQUIRED_ARTIFACTS.issubset(artifact_paths):
        raise XingceAdaptivePackError("pack artifacts must include records, skills, and misconceptions")
    if status == RELEASE_STATUS and "review-evidence.json" not in artifact_paths:
        raise XingceAdaptivePackError("release requires an immutable review-evidence artifact")
    return subtype


def _validate_skills(document: Mapping[str, Any], manifest: Mapping[str, Any], status: str) -> set[str]:
    if document.get("schema_version") != ADAPTIVE_SKILLS_SCHEMA:
        raise XingceAdaptivePackError("unsupported adaptive skill graph schema")
    if document.get("pack_id") != manifest["pack_id"] or document.get("pack_version") != manifest["pack_version"]:
        raise XingceAdaptivePackError("skill graph pack identity mismatch")
    if document.get("review_status") != status:
        raise XingceAdaptivePackError("skill graph review status mismatch")
    skills = _require(document, "skills", list)
    ids: set[str] = set()
    for skill in skills:
        if not isinstance(skill, Mapping):
            raise XingceAdaptivePackError("skill must be an object")
        skill_id = _short_id(skill.get("skill_id"), "skill_id")
        if skill_id in ids:
            raise XingceAdaptivePackError("skill ids must be unique")
        ids.add(skill_id)
        _nonempty(skill.get("label"), "skill label")
        _nonempty(skill.get("mastery_claim"), "skill mastery claim")
    if not ids:
        raise XingceAdaptivePackError("adaptive pack needs at least one skill")
    return ids


def _validate_taxonomy(document: Mapping[str, Any], manifest: Mapping[str, Any], status: str, skill_ids: set[str]) -> set[str]:
    if document.get("schema_version") != ADAPTIVE_TAXONOMY_SCHEMA:
        raise XingceAdaptivePackError("unsupported adaptive misconception schema")
    if document.get("pack_id") != manifest["pack_id"] or document.get("pack_version") != manifest["pack_version"]:
        raise XingceAdaptivePackError("misconception taxonomy pack identity mismatch")
    if document.get("review_status") != status:
        raise XingceAdaptivePackError("misconception taxonomy review status mismatch")
    rows = _require(document, "candidate_misconceptions", list)
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise XingceAdaptivePackError("candidate misconception must be an object")
        cause_id = _short_id(row.get("cause_id"), "cause_id")
        if cause_id in ids:
            raise XingceAdaptivePackError("candidate cause ids must be unique")
        ids.add(cause_id)
        _nonempty(row.get("label"), "candidate cause label")
        if row.get("status") != "unconfirmed" or row.get("is_ground_truth", False) is not False:
            raise XingceAdaptivePackError("authored causes must remain unconfirmed hypotheses")
        targets = _as_string_list(row.get("target_skill_ids"), "candidate target_skill_ids")
        if not set(targets).issubset(skill_ids):
            raise XingceAdaptivePackError("candidate cause references an unknown skill")
    if len(ids) < 2:
        raise XingceAdaptivePackError("adaptive pack needs at least two candidate causes")
    return ids


def _validate_options(record: Mapping[str, Any]) -> set[str]:
    options = _require(record, "options", list)
    labels: set[str] = set()
    for option in options:
        if not isinstance(option, Mapping):
            raise XingceAdaptivePackError("assessment option must be an object")
        label = _short_id(option.get("label"), "option label")
        _nonempty(option.get("text"), "option text")
        if label in labels:
            raise XingceAdaptivePackError("assessment option labels must be unique")
        labels.add(label)
    if len(labels) < 2:
        raise XingceAdaptivePackError("assessment needs at least two options")
    return labels


def _validate_material_source(value: Any, *, nested: bool = False) -> None:
    """Validate the small, learner-visible material vocabulary.

    Materials deliberately live inside the immutable record rather than behind
    a mutable URL or a local path.  They contain only presentation data; answer
    keys, scoring fields, and candidate-routing fields remain record-private.
    """

    if not isinstance(value, Mapping):
        raise XingceAdaptivePackError("source_material must be an object")
    kind = value.get("kind")
    if kind not in _MATERIAL_KINDS:
        raise XingceAdaptivePackError("source_material kind is unsupported")

    if kind == "text":
        if set(value) != {"kind", "title", "body", "scope_note"}:
            raise XingceAdaptivePackError("text source_material has unsupported fields")
        _nonempty(value.get("title"), "material title")
        _nonempty(value.get("body"), "material body")
        _nonempty(value.get("scope_note"), "material scope note")
        return

    if kind == "table":
        if set(value) != {"kind", "title", "columns", "rows", "scope_note"}:
            raise XingceAdaptivePackError("table source_material has unsupported fields")
        _nonempty(value.get("title"), "material title")
        _nonempty(value.get("scope_note"), "material scope note")
        columns = value.get("columns")
        rows = value.get("rows")
        if not isinstance(columns, list) or not 2 <= len(columns) <= 8 or any(not isinstance(item, str) or not item.strip() for item in columns):
            raise XingceAdaptivePackError("material table columns are invalid")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 30:
            raise XingceAdaptivePackError("material table rows are invalid")
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise XingceAdaptivePackError("material table row width is invalid")
            for cell in row:
                if isinstance(cell, bool) or not isinstance(cell, (str, int, float)) or (isinstance(cell, str) and not cell.strip()):
                    raise XingceAdaptivePackError("material table cell is invalid")
        return

    if kind == "chart":
        if set(value) != {"kind", "title", "alt_text", "unit_scope", "categories", "series"}:
            raise XingceAdaptivePackError("chart source_material has unsupported fields")
        _nonempty(value.get("title"), "chart title")
        _nonempty(value.get("alt_text"), "chart alt text")
        _nonempty(value.get("unit_scope"), "chart unit and scope")
        categories = value.get("categories")
        series = value.get("series")
        if not isinstance(categories, list) or not 2 <= len(categories) <= 12 or any(not isinstance(item, str) or not item.strip() for item in categories):
            raise XingceAdaptivePackError("chart categories are invalid")
        if not isinstance(series, list) or not 1 <= len(series) <= 4:
            raise XingceAdaptivePackError("chart series are invalid")
        for item in series:
            if not isinstance(item, Mapping) or set(item) != {"label", "values"} or not isinstance(item.get("label"), str) or not item["label"].strip():
                raise XingceAdaptivePackError("chart series are invalid")
            values = item.get("values")
            if not isinstance(values, list) or len(values) != len(categories) or any(isinstance(number, bool) or not isinstance(number, (int, float)) for number in values):
                raise XingceAdaptivePackError("chart values are invalid")
        return

    if kind == "diagram":
        if set(value) != {"kind", "title", "alt_text", "panels"}:
            raise XingceAdaptivePackError("diagram source_material has unsupported fields")
        _nonempty(value.get("title"), "diagram title")
        _nonempty(value.get("alt_text"), "diagram alt text")
        panels = value.get("panels")
        if not isinstance(panels, list) or not 2 <= len(panels) <= 8:
            raise XingceAdaptivePackError("diagram panels are invalid")
        labels: set[str] = set()
        for panel in panels:
            if not isinstance(panel, Mapping) or set(panel) != {"label", "tokens"}:
                raise XingceAdaptivePackError("diagram panel has unsupported fields")
            label = _nonempty(panel.get("label"), "diagram panel label")
            tokens = panel.get("tokens")
            if label in labels or not isinstance(tokens, list) or not 1 <= len(tokens) <= 12:
                raise XingceAdaptivePackError("diagram panels are invalid")
            if any(not isinstance(token, str) or not token.strip() or len(token) > 8 for token in tokens):
                raise XingceAdaptivePackError("diagram token is invalid")
            labels.add(label)
        return

    if nested or set(value) != {"kind", "title", "scope_note", "parts"}:
        raise XingceAdaptivePackError("composite source_material has unsupported fields")
    _nonempty(value.get("title"), "material title")
    _nonempty(value.get("scope_note"), "material scope note")
    parts = value.get("parts")
    if not isinstance(parts, list) or not 2 <= len(parts) <= 4:
        raise XingceAdaptivePackError("composite material parts are invalid")
    for part in parts:
        _validate_material_source(part, nested=True)


def _material_checksum(records: Sequence[Mapping[str, Any]], *, kinds: set[str] | None = None) -> str:
    payload = []
    for record in records:
        material = record.get("source_material")
        if not isinstance(material, Mapping) or (kinds is not None and material.get("kind") not in kinds):
            continue
        payload.append({"record_id": record["record_id"], "source_material": material})
    return canonical_json_sha256(payload)


def _validate_records(
    document: Mapping[str, Any], manifest: Mapping[str, Any], status: str, skill_ids: set[str], cause_ids: set[str]
) -> None:
    if document.get("schema_version") != ADAPTIVE_RECORDS_SCHEMA:
        raise XingceAdaptivePackError("unsupported adaptive records schema")
    if document.get("pack_id") != manifest["pack_id"] or document.get("pack_version") != manifest["pack_version"]:
        raise XingceAdaptivePackError("records pack identity mismatch")
    if document.get("review_status") != status:
        raise XingceAdaptivePackError("records review status mismatch")
    records = _require(document, "records", list)
    index: dict[str, Mapping[str, Any]] = {}
    role_counts: dict[str, int] = {}
    entry_groups: set[str] = set()
    transfer_groups: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise XingceAdaptivePackError("record must be an object")
        record_id = _short_id(record.get("record_id"), "record_id")
        if record_id in index:
            raise XingceAdaptivePackError("record ids must be unique")
        index[record_id] = record
        if record.get("record_sha256") != record_sha256(record):
            raise XingceAdaptivePackError("record checksum does not match authored record")
        role = record.get("role")
        if role not in _ROLES:
            raise XingceAdaptivePackError("unsupported adaptive record role")
        role_counts[role] = role_counts.get(role, 0) + 1
        _nonempty(record.get("title"), "record title")
        if record.get("review_status") != status or record.get("content_origin") != manifest["rights"]["content_origin"]:
            raise XingceAdaptivePackError("record provenance or review status mismatch")
        targets = _as_string_list(record.get("target_skill_ids"), "record target_skill_ids")
        if not set(targets).issubset(skill_ids):
            raise XingceAdaptivePackError("record references an unknown skill")
        candidates = _as_string_list(record.get("candidate_misconception_ids"), "record candidate_misconception_ids")
        if not set(candidates).issubset(cause_ids):
            raise XingceAdaptivePackError("record references an unknown candidate cause")
        independence_group = _short_id(record.get("independence_group"), "independence_group")
        if role in {"entry_diagnostic", "routing_diagnostic"}:
            entry_groups.add(independence_group)
            if len(candidates) < 2:
                raise XingceAdaptivePackError("entry diagnostics must name competing candidate causes")
            _as_string_list(record.get("route_probe_ids"), "entry route_probe_ids")
        if role == "independent_transfer":
            transfer_groups.add(independence_group)
            if record.get("requires_no_hints") is not True:
                raise XingceAdaptivePackError("independent transfer must prohibit hints")
        if role == "delayed_review":
            if record.get("requires_no_hints") is not True:
                raise XingceAdaptivePackError("delayed review must prohibit hints")
            if not isinstance(record.get("scheduled_after_days"), int) or record["scheduled_after_days"] < 1:
                raise XingceAdaptivePackError("delayed review needs a positive schedule interval")
            _as_string_list(record.get("eligible_after_transfer_ids"), "review eligible transfer ids")
        if role in _ASSESSMENT_ROLES:
            _nonempty(record.get("prompt"), "assessment prompt")
            if manifest["form"] in {"material_mcq", "visual_mcq"}:
                _validate_material_source(record.get("source_material"))
            elif "source_material" in record:
                raise XingceAdaptivePackError("source_material is reserved for material_mcq records")
            scorer = manifest["scorer"]
            if scorer == "exact_option_v1":
                if record.get("response_mode") != "single_choice":
                    raise XingceAdaptivePackError("exact option scorer requires single-choice response")
                labels = _validate_options(record)
                if _short_id(record.get("correct_option"), "correct_option") not in labels:
                    raise XingceAdaptivePackError("correct option must be present in assessment options")
            else:
                mode = record.get("response_mode")
                if mode == "single_choice":
                    labels = _validate_options(record)
                    if _short_id(record.get("correct_option"), "correct_option") not in labels:
                        raise XingceAdaptivePackError("numeric-or-mcq correct option must be present")
                elif mode == "numeric":
                    answer = _require(record, "answer_spec", Mapping)
                    if not isinstance(answer.get("target"), (int, float)) or isinstance(answer.get("target"), bool):
                        raise XingceAdaptivePackError("numeric answer target must be a number")
                    tolerance = answer.get("tolerance", 0)
                    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or tolerance < 0:
                        raise XingceAdaptivePackError("numeric answer tolerance must be non-negative")
                else:
                    raise XingceAdaptivePackError("numeric-or-mcq records require numeric or single-choice response")
        if role == "probe":
            discriminates = _as_string_list(record.get("discriminates"), "probe discriminates", minimum=2)
            if not set(discriminates).issubset(cause_ids):
                raise XingceAdaptivePackError("probe discriminates an unknown candidate cause")
            evidence_map = _require(record, "candidate_evidence_map", Mapping)
            if set(evidence_map) != set(discriminates):
                raise XingceAdaptivePackError("probe evidence map must cover exactly its discriminated candidates")
            for cause_id, outcomes in evidence_map.items():
                if not isinstance(outcomes, Mapping) or not outcomes:
                    raise XingceAdaptivePackError("probe evidence outcomes must be a non-empty mapping")
                if any(outcome not in _OUTCOMES for outcome in outcomes.values()):
                    raise XingceAdaptivePackError("probe may support, refute, or remain insufficient only")
        if role == "teaching_asset":
            targets = _as_string_list(record.get("target_candidate_ids"), "teaching target_candidate_ids")
            if not set(targets).issubset(cause_ids):
                raise XingceAdaptivePackError("teaching targets an unknown candidate cause")
            _nonempty(record.get("teaching_content"), "teaching content")

    for role in ("entry_diagnostic", "probe", "teaching_asset", "independent_transfer", "delayed_review"):
        if role_counts.get(role, 0) < 1:
            raise XingceAdaptivePackError(f"adaptive pack needs at least one {role}")
    if entry_groups & transfer_groups:
        raise XingceAdaptivePackError("independent transfers must use unseen independence groups")
    for record in records:
        if record["role"] in {"entry_diagnostic", "routing_diagnostic"} and not set(record["route_probe_ids"]).issubset(index):
            raise XingceAdaptivePackError("entry routes to an unknown probe")
        if record["role"] == "delayed_review" and not set(record["eligible_after_transfer_ids"]).issubset(index):
            raise XingceAdaptivePackError("review references an unknown transfer")
        if record["role"] == "delayed_review" and not all(index[item]["role"] == "independent_transfer" for item in record["eligible_after_transfer_ids"]):
            raise XingceAdaptivePackError("review must follow an independent transfer")


def validate_xingce_adaptive_documents(
    manifest: Mapping[str, Any], records: Mapping[str, Any], skills: Mapping[str, Any], taxonomy: Mapping[str, Any]
) -> None:
    """Validate the complete, immutable logical payload before registration."""

    subtype = _validate_manifest(manifest)
    status = str(manifest["status"])
    skill_ids = _validate_skills(skills, manifest, status)
    cause_ids = _validate_taxonomy(taxonomy, manifest, status, skill_ids)
    _validate_records(records, manifest, status, skill_ids, cause_ids)
    if manifest["form"] in {"material_mcq", "visual_mcq"}:
        assessment_records = [record for record in records["records"] if record["role"] in _ASSESSMENT_ROLES]
        evidence = manifest["content_evidence"]
        if "material_checksum" in evidence and evidence["material_checksum"] != _material_checksum(assessment_records):
            raise XingceAdaptivePackError("material checksum does not bind the authored source materials")
        if "asset_checksum" in evidence:
            asset_kind = "diagram" if manifest["form"] == "visual_mcq" else "chart"
            asset_checksum = _material_checksum(assessment_records, kinds={asset_kind})
            if not any(record["source_material"]["kind"] == asset_kind for record in assessment_records) or evidence["asset_checksum"] != asset_checksum:
                raise XingceAdaptivePackError("asset checksum does not bind the authored visual materials")
    # The matrix query is intentionally at the end as a cheap assertion that
    # the records did not replace the type-specific requirements with generic
    # conditional-logic metadata.
    if manifest["form"] != subtype["form"] or manifest["scorer"] != subtype["scorer"]:
        raise XingceAdaptivePackError("validated pack drifted from subtype profile")


def _read_json(root: Path, name: str) -> dict[str, Any]:
    try:
        payload = json.loads((root / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XingceAdaptivePackError(f"adaptive pack cannot load {name}") from exc
    if not isinstance(payload, dict):
        raise XingceAdaptivePackError(f"adaptive pack {name} must be an object")
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_xingce_adaptive_pack(root: str | Path, *, require_reviewed: bool = False) -> dict[str, Any]:
    """Read an immutable adaptive pack; runtime callers can require review."""

    path = Path(root)
    manifest = _read_json(path, "manifest.json")
    records = _read_json(path, "records.json")
    skills = _read_json(path, "skill-graph.json")
    taxonomy = _read_json(path, "misconceptions.json")
    validate_xingce_adaptive_documents(manifest, records, skills, taxonomy)
    if require_reviewed and manifest["status"] != RELEASE_STATUS:
        raise XingceAdaptivePackError("content_review_required")
    declared = {str(item["path"]): str(item["sha256"]) for item in manifest["artifacts"]}
    for name, expected in declared.items():
        candidate = path / name
        if candidate.resolve().parent != path.resolve() and path.resolve() not in candidate.resolve().parents:
            raise XingceAdaptivePackError("adaptive pack artifact escapes its root")
        if not candidate.is_file() or _file_sha256(candidate) != expected:
            raise XingceAdaptivePackError("adaptive pack artifact checksum mismatch")
    if manifest["status"] == RELEASE_STATUS:
        evidence = _read_json(path, "review-evidence.json")
        if evidence.get("schema_version") != "lumi.xingce-review-evidence.v1":
            raise XingceAdaptivePackError("release review evidence schema is invalid")
        workbook = evidence.get("manual_review_workbook")
        rows = evidence.get("reviewer_attestations")
        if not isinstance(workbook, Mapping) or not isinstance(rows, list) or len(rows) != 2:
            raise XingceAdaptivePackError("release review evidence is incomplete")
        if not isinstance(workbook.get("name"), str) or not workbook["name"].strip():
            raise XingceAdaptivePackError("release review workbook name is invalid")
        _sha256(workbook.get("sha256"), "review workbook sha256")
        evidence_pairs = {(row.get("review_kind"), row.get("reviewer_id"), row.get("reviewed_at")) for row in rows if isinstance(row, Mapping)}
        gate_pairs = {(row.get("review_kind"), row.get("reviewer_id"), row.get("reviewed_at")) for row in manifest["human_review_gate"]["review_attestations"]}
        if evidence_pairs != gate_pairs or len(evidence_pairs) != 2:
            raise XingceAdaptivePackError("release review evidence does not match its reviewer attestations")
    return {
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "status": manifest["status"],
        "subtype_id": manifest["subtype_id"],
        "module_id": manifest["module_id"],
        "form": manifest["form"],
        "scorer": manifest["scorer"],
        "records": [dict(row) for row in records["records"]],
        "skills": [dict(row) for row in skills["skills"]],
        "candidate_misconceptions": [dict(row) for row in taxonomy["candidate_misconceptions"]],
        "product_release": copy.deepcopy(manifest.get("product_release")),
    }


def public_record_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the smallest learner-visible record projection for a given role."""

    base = {"record_id": record["record_id"], "role": record["role"], "title": record["title"]}
    if record["role"] == "teaching_asset":
        return {**base, "teaching_content": record["teaching_content"]}
    result = {**base, "prompt": record["prompt"], "response_mode": record["response_mode"]}
    if record["response_mode"] == "single_choice":
        result["options"] = [dict(option) for option in record["options"]]
    if "source_material" in record:
        result["source_material"] = copy.deepcopy(record["source_material"])
    return result
