from __future__ import annotations

from pathlib import Path
import copy
from typing import Any

from hermes_domains import (
    load_fixture_document,
    load_product_activities,
    validate_product_activity_runtime,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "domains" / "fixtures"
PRODUCT_ACTIVITY_PAYLOAD = (
    Path(__file__).resolve().parents[2]
    / "domains"
    / "local_content"
    / "xingce"
    / "p031-data-analysis-v1.json"
)


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


class ProductActivityCatalog:
    """Private local activity records with an explicitly safe public projection.

    The generated payload may contain scoring keys needed by the deterministic
    domain compiler.  Those records never leave this catalog through ``list``
    or ``get``; callers receive a projection built field-by-field instead.
    Missing local content is a supported state so a clean checkout can still
    start the sidecar and retain the representative 42-scenario catalog.
    """

    def __init__(
        self,
        payload_path: str | Path | None = None,
        *,
        activities: tuple[Any, ...] | None = None,
    ) -> None:
        path = Path(PRODUCT_ACTIVITY_PAYLOAD if payload_path is None else payload_path)
        if activities is None:
            activities = load_product_activities(path) if path.is_file() else ()
        self._launchers: dict[str, Any] = {}
        self._launchable_fixture_ids: set[str] = set()
        self._items: dict[str, dict[str, Any]] = {}
        for activity in activities:
            public = activity.public_view()
            release_id = public["release_id"]
            first = public["first_answer"]
            transfer = public["independent_transfer"]
            first_id = first["question_id"]
            transfer_id = transfer["question_id"]
            if first_id in self._items or transfer_id in self._items:
                raise RuntimeError("duplicate product activity item id")
            self._items[first_id] = self._project(first, release_id)
            self._items[transfer_id] = self._project(transfer, release_id)
            # Only the first-answer item starts a new runtime session. The
            # transfer item is bound to that session and submitted through the
            # continuation endpoint, never as a freestanding first attempt.
            self._launchers[first_id] = activity
            fixture = activity.to_runtime_fixture()
            self._launchable_fixture_ids.add(str(fixture["fixture_id"]))

    def list(
        self,
        *,
        release_id: str | None = None,
        diagnostic_role: str | None = None,
    ) -> list[dict[str, Any]]:
        items = sorted(
            self._items.values(),
            key=lambda item: (item["release_id"], item["diagnostic_role"]),
        )
        if release_id is not None:
            items = [item for item in items if item["release_id"] == release_id]
        if diagnostic_role is not None:
            items = [
                item
                for item in items
                if item["diagnostic_role"] == diagnostic_role
            ]
        return [copy.deepcopy(item) for item in items]

    def get(self, activity_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._items[activity_id])
        except KeyError as exc:
            raise KeyError(activity_id) from exc

    def resolve_fixture(self, activity_id: str) -> dict[str, Any]:
        try:
            fixture = self._launchers[activity_id].to_runtime_fixture()
        except KeyError as exc:
            raise KeyError(activity_id) from exc
        validate_product_activity_runtime(fixture)
        return fixture

    def is_launchable_fixture(self, fixture_id: str) -> bool:
        return fixture_id in self._launchable_fixture_ids

    @staticmethod
    def _project(item: dict[str, Any], release_id: str) -> dict[str, Any]:
        activity_id = _required_text(item, "question_id")
        role = _required_text(item, "diagnostic_role")
        material = _required_text(item, "material_text")
        stem = _required_text(item, "stem_text")
        raw_options = item.get("options")
        if not isinstance(raw_options, list) or len(raw_options) != 4:
            raise RuntimeError(f"product activity options are invalid: {activity_id}")
        options: list[dict[str, str]] = []
        labels: set[str] = set()
        for option in raw_options:
            if not isinstance(option, dict):
                raise RuntimeError(f"product activity option is invalid: {activity_id}")
            label = _required_text(option, "label")
            text = _required_text(option, "text")
            if label in labels:
                raise RuntimeError(f"duplicate product activity option: {activity_id}")
            labels.add(label)
            options.append({"label": label, "text": text})
        source = item.get("source")
        if not isinstance(source, dict):
            raise RuntimeError(f"product activity source is invalid: {activity_id}")
        content_signature = _required_text(source, "content_signature")
        return {
            "schema_version": "lumi.product-activity.v1",
            "activity_id": activity_id,
            "item_id": activity_id,
            "release_id": release_id,
            "content_signature": content_signature,
            "domain": "xingce",
            "module": "资料分析",
            "diagnostic_role": role,
            "response_mode": "single_choice",
            "material_text": material,
            "stem_text": stem,
            "options": options,
            "source": {
                "paper_title": source.get("paper_title"),
                "year": source.get("year"),
                "question_no": source.get("question_no"),
                "source_site": source.get("source_site"),
                "source_url": source.get("source_url"),
            },
            "links": {
                "self": f"/v1/product-activities/{activity_id}",
                "attempts": "/v1/attempts",
            },
        }


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"product activity {key} must be non-empty text")
    return value
