from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping


GENERATOR_NAME = "extractive-local"
GENERATOR_VERSION = "1"
GENERATOR_ID = f"{GENERATOR_NAME}@{GENERATOR_VERSION}"
VERIFIER_ID = "study-pack-deterministic-verifier@1"
NORMALIZATION_NAME = "unicode-nfc-canonical-newline"
NORMALIZATION_VERSION = "1.0.0"

ARTIFACT_TYPES = frozenset(
    {
        "study_pack.one_page_notes",
        "study_pack.knowledge_card",
        "study_pack.practice_item",
        "study_pack.review_task",
    }
)
PRACTICE_KINDS = frozenset({"cloze_exact_v1", "normalized_exact_v1"})
PACK_STATES = frozenset({"draft", "review", "published", "quarantined"})
ARTIFACT_STATES = PACK_STATES

_ID_PREFIXES = frozenset({"p_", "d_", "s_", "a_", "v_", "t_"})
_ENTITY_ID = re.compile(r"^(?:p_|d_|s_|a_|v_|t_)[A-P]{40}$")
_COMMAND_ID = re.compile(r"^c_[A-P]{40}$")


class StudyPackError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class VersionConflict(StudyPackError):
    def __init__(self, expected_version: int, actual_version: int) -> None:
        super().__init__(
            "stale_version",
            f"expected_version {expected_version} does not match current version {actual_version}",
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class CommandConflict(StudyPackError):
    def __init__(self) -> None:
        super().__init__(
            "command_conflict", "command_id was already used for a different mutation"
        )


class OpaqueIdFactory:
    def __init__(self, random_bytes: Callable[[int], bytes] = secrets.token_bytes) -> None:
        self._random_bytes = random_bytes

    def __call__(self, prefix: str) -> str:
        if prefix not in _ID_PREFIXES:
            raise ValueError("unsupported opaque identifier prefix")
        raw = self._random_bytes(20)
        if len(raw) != 20:
            raise ValueError("opaque identifier entropy source returned the wrong length")
        encoded = "".join(
            chr(ord("A") + nibble)
            for byte in raw
            for nibble in (byte >> 4, byte & 0x0F)
        )
        return prefix + encoded


def validate_command_id(value: Any) -> str:
    if not isinstance(value, str) or _COMMAND_ID.fullmatch(value) is None:
        raise StudyPackError(
            "invalid_command_id", "command_id must be an opaque c_ identifier"
        )
    return value


def validate_entity_id(value: Any, prefix: str | None = None) -> str:
    if not isinstance(value, str) or _ENTITY_ID.fullmatch(value) is None:
        raise StudyPackError("invalid_entity_id", "entity identifier is invalid")
    if prefix is not None and not value.startswith(prefix):
        raise StudyPackError("invalid_entity_id", "entity identifier type is invalid")
    return value


@dataclass(frozen=True, slots=True)
class SourceSegment:
    locator_kind: str
    locator_index: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ParsedSource:
    input_kind: str
    media_type: str
    original_bytes: bytes
    normalized_text: str
    segments: tuple[SourceSegment, ...]
    parser_name: str
    parser_version: str
    normalization_name: str
    normalization_version: str
    warnings: tuple[str, ...] = ()

    @property
    def original_sha256(self) -> str:
        return sha256_bytes(self.original_bytes)

    @property
    def normalized_sha256(self) -> str:
        return sha256_text(self.normalized_text)

    @property
    def codepoint_count(self) -> int:
        return len(self.normalized_text)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    document_id: str
    pack_id: str
    source_version: int
    input_kind: str
    media_type: str
    original_sha256: str
    normalized_sha256: str
    byte_count: int
    locator_count: int
    codepoint_count: int
    parser_name: str
    parser_version: str
    normalization_name: str
    normalization_version: str
    extraction_state: str
    warning_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = {"schema_version": "lumi.source-document.v1", **asdict(self)}
        value["warning_codes"] = list(self.warning_codes)
        return value


@dataclass(frozen=True, slots=True)
class SourceSpan:
    span_id: str
    document_id: str
    source_version: int
    normalized_source_sha256: str
    locator_kind: str
    locator_index: int
    start_offset: int
    end_offset: int
    slice_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": "lumi.source-span.v1", **asdict(self)}


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_id: str
    pack_id: str
    artifact_version: int
    artifact_type: str
    lifecycle: str
    content: dict[str, Any]
    content_digest: str
    generator_id: str
    generator_metadata: dict[str, Any]

    def to_dict(self, *, include_private: bool = True) -> dict[str, Any]:
        value = {
            "artifact_id": self.artifact_id,
            "pack_id": self.pack_id,
            "artifact_version": self.artifact_version,
            "artifact_type": self.artifact_type,
            "lifecycle": self.lifecycle,
            "content_digest": self.content_digest,
            "generator_id": self.generator_id,
            "generator_metadata": self.generator_metadata,
        }
        if include_private:
            value["content"] = self.content
        return value


@dataclass(frozen=True, slots=True)
class CandidateSkillLink:
    artifact_id: str
    label: str
    skill_id: str | None
    status: str
    taxonomy_version: str | None
    taxonomy_digest: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VerifierDecision:
    decision_id: str
    pack_id: str
    artifact_id: str
    artifact_version: int
    artifact_digest: str
    verifier_id: str
    accepted: bool
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reason_codes"] = list(self.reason_codes)
        return value


@dataclass(frozen=True, slots=True)
class PracticeAttempt:
    attempt_id: str
    pack_id: str
    artifact_id: str
    artifact_version: int
    answer_digest: str
    correct: bool
    score: float
    evidence_origin: str
    activity_kind: str
    scorer_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": "lumi.study-pack-attempt.v1", **asdict(self)}


@dataclass(frozen=True, slots=True)
class PackEvent:
    pack_id: str
    seq: int
    occurred_at: str
    kind: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_digest(content: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))
