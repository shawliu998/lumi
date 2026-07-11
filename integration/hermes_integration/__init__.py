"""Real glue between Lumi domain adapters, KT engine, and Agent runtime."""

# This source checkout contains three intentionally independent packages. Add
# their roots for direct local execution; installed distributions still win by
# normal import order.
from pathlib import Path
import sys

_repo = Path(__file__).resolve().parents[2]
for _name in ("domains", "engine", "runtime"):
    _path = str(_repo / _name)
    if _path not in sys.path:
        sys.path.append(_path)

from .loop import ContinuationError, IntegrationSession, Scenario, continue_attempt, run_attempt, run_scenario

__all__ = [
    "ContinuationError",
    "IntegrationSession",
    "Scenario",
    "continue_attempt",
    "run_attempt",
    "run_scenario",
]
