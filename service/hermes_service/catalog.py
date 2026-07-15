from __future__ import annotations

from pathlib import Path
import copy
from typing import Any

from hermes_domains import load_fixture_document
from hermes_domains.lessons import load_lesson_catalog


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "domains" / "fixtures"
LESSON_ROOT = Path(__file__).resolve().parents[2] / "domains" / "lessons"


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
                "title": fixture["module"].split("/", 1)[-1],
                "response_mode": fixture["task"]["response_mode"],
                "prompt": fixture["task"]["prompt"],
                "options": dict(fixture["task"].get("options", {})),
                "skills": [item["skill_id"] for item in fixture.get("skills", [])],
                "connectivity": fixture["execution"]["connectivity"],
            }
            for fixture in fixtures
        ]
        return sorted(items, key=lambda item: (item["domain"], item["path"], item["mode"]))


class LessonCatalog:
    """Manifest-verified lessons plus full fixtures for the existing runtime."""

    def __init__(self, lesson_root: Path = LESSON_ROOT) -> None:
        lessons = load_lesson_catalog(lesson_root=lesson_root)
        if not lessons:
            raise RuntimeError("lesson catalog must contain at least one lesson")
        lesson_ids = [lesson["lesson_id"] for lesson in lessons]
        if not all(_addressable_identifier(item) for item in lesson_ids):
            raise RuntimeError("lesson identifiers must be safe URL path segments")
        if len(set(lesson_ids)) != len(lesson_ids):
            raise RuntimeError("lesson catalog must contain unique lesson identifiers")

        fixtures = [
            fixture
            for lesson in lessons
            for fixture in lesson["practice_fixtures"]
        ]
        fixture_ids = [fixture["fixture_id"] for fixture in fixtures]
        if not all(_addressable_identifier(item) for item in fixture_ids):
            raise RuntimeError("lesson practice fixture identifiers are not addressable")
        if len(set(fixture_ids)) != len(fixture_ids):
            raise RuntimeError("lesson practice fixtures must have globally unique identifiers")

        self._fixtures = {fixture["fixture_id"]: fixture for fixture in fixtures}
        self._details = {
            lesson["lesson_id"]: self._project_detail(lesson)
            for lesson in lessons
        }
        self._items = sorted(
            (self._project_summary(lesson) for lesson in lessons),
            key=lambda item: (item["domain"], item["path"], item["lesson_id"]),
        )

    def list(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._items)

    def resolve(self, lesson_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._details[lesson_id])
        except KeyError as exc:
            raise KeyError(lesson_id) from exc

    def resolve_fixture(self, fixture_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._fixtures[fixture_id])
        except KeyError as exc:
            raise KeyError(fixture_id) from exc

    @staticmethod
    def _project_summary(lesson: dict[str, Any]) -> dict[str, Any]:
        return {
            "lesson_id": lesson["lesson_id"],
            "version": lesson["version"],
            "domain": lesson["domain"],
            "path": lesson["path"],
            "module": lesson["module"],
            "title": lesson["title"],
            "estimated_minutes": lesson["estimated_minutes"],
            "skill_ids": list(lesson["skill_ids"]),
            "practice_count": len(lesson["practice_fixtures"]),
        }

    @classmethod
    def _project_detail(cls, lesson: dict[str, Any]) -> dict[str, Any]:
        method_card = lesson["method_card"]
        worked_example = lesson["worked_example"]
        provenance = lesson["provenance"]
        return {
            **cls._project_summary(lesson),
            "method_card": {
                "definition": method_card["definition"],
                "formula": method_card["formula"],
                "applicability": list(method_card["applicability"]),
                "common_mistake": {
                    "label": method_card["common_mistake"]["label"],
                    "explanation": method_card["common_mistake"]["explanation"],
                },
            },
            "worked_example": {
                "example_id": worked_example["example_id"],
                "prompt": worked_example["prompt"],
                "steps": [
                    {
                        "step_id": step["step_id"],
                        "instruction": step["instruction"],
                        "content": step["content"],
                    }
                    for step in worked_example["steps"]
                ],
                "hint_ladder": [
                    {
                        "level": hint["level"],
                        "label": hint["label"],
                        "prompt": hint["prompt"],
                        "reveal_rank": hint["reveal_rank"],
                    }
                    for hint in worked_example["hint_ladder"]
                ],
            },
            "practice_items": [
                {
                    "fixture_id": fixture["fixture_id"],
                    "prompt": fixture["task"]["prompt"],
                    "response_mode": fixture["task"]["response_mode"],
                    "options": dict(fixture["task"].get("options", {})),
                    "skill_ids": [skill["skill_id"] for skill in fixture["skills"]],
                }
                for fixture in lesson["practice_fixtures"]
            ],
            "completion_policy": {
                "minimum_questions": lesson["completion_policy"]["minimum_questions"],
                "consecutive_verified_transfers": lesson["completion_policy"][
                    "consecutive_verified_transfers"
                ],
                "lesson_reading_changes_mastery": lesson["completion_policy"][
                    "lesson_reading_changes_mastery"
                ],
                "hinted_evidence_discount": lesson["completion_policy"]["hinted_evidence_discount"],
            },
            "provenance": {
                "source_title": provenance["source_title"],
                "rights_status": provenance["rights_status"],
                "review_status": provenance["review_status"],
            },
        }


def _addressable_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 200
        and all(char.isalnum() or char in "-_.:" for char in value)
    )
