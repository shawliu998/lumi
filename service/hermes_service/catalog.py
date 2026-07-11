from __future__ import annotations

from pathlib import Path
import copy
from typing import Any

from hermes_domains import load_fixture_document


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "domains" / "fixtures"


class ScenarioCatalog:
    """Read-only safe projection of the independently addressable 42 fixtures."""

    def __init__(self) -> None:
        fixtures = self._load_fixtures()
        self._fixtures = {fixture["fixture_id"]: fixture for fixture in fixtures}
        self._items = self._project(fixtures)

    def list(self, *, domain: str | None = None, mode: str | None = None) -> list[dict[str, Any]]:
        items = self._items
        if domain is not None:
            items = [item for item in items if item["domain"] == domain]
        if mode is not None:
            items = [item for item in items if item["mode"] == mode]
        return [dict(item) for item in items]

    def resolve(self, fixture_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._fixtures[fixture_id])
        except KeyError as exc:
            raise KeyError(fixture_id) from exc

    def _load_fixtures(self) -> list[dict[str, Any]]:
        fixtures = [
            load_fixture_document(path, fixture_root=FIXTURE_ROOT)
            for path in sorted(FIXTURE_ROOT.rglob("*.json"))
        ]
        if len(fixtures) != 42 or len({item["fixture_id"] for item in fixtures}) != 42:
            raise RuntimeError("representative scenario catalog must contain 42 unique fixtures")
        return fixtures

    @staticmethod
    def _project(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items = [
            {
                "fixture_id": fixture["fixture_id"],
                "domain": fixture["domain"],
                "path": fixture["path"],
                "mode": fixture["mode"],
                "module": fixture["module"],
                "response_mode": fixture["task"]["response_mode"],
                "connectivity": fixture["execution"]["connectivity"],
            }
            for fixture in fixtures
        ]
        return sorted(items, key=lambda item: (item["domain"], item["path"], item["mode"]))
