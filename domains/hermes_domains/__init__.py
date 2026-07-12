"""Unified deterministic adapters for Lumi representative domain slices."""

from .adapters import score_attempt, score_verification_response
from .contract import ContractError, validate_fixture, validate_overlay
from .fixtures import load_fixture_document
from .models import CauseCandidate, ScoreObservation, ScoreResult
from .product_activity import (
    ProductActivity,
    ProductActivityError,
    load_product_activities,
    load_product_activity,
    validate_product_activity_runtime,
)

__all__ = [
    "CauseCandidate",
    "ContractError",
    "ScoreObservation",
    "ScoreResult",
    "ProductActivity",
    "ProductActivityError",
    "score_attempt",
    "score_verification_response",
    "load_fixture_document",
    "load_product_activities",
    "load_product_activity",
    "validate_fixture",
    "validate_overlay",
    "validate_product_activity_runtime",
]
