"""Safe public projection of Lumi's all-Xingce coverage contract.

This is intentionally a status catalogue, not a question catalogue: it lets
the client show what is genuinely available without leaking draft content or
pretending that representative fixtures constitute a released subtype.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from hermes_domains.xingce_coverage import coverage_summary, load_coverage_matrix


XINGCE_COVERAGE_CATALOG_SCHEMA = "lumi.xingce-coverage-catalog.v1"


class XingceCoverageCatalog:
    def __init__(self, *, available_subtype_ids: Iterable[str] = ()) -> None:
        self._matrix = load_coverage_matrix()
        self._available_subtype_ids = frozenset(available_subtype_ids)

    def public_projection(self) -> dict[str, Any]:
        summary = coverage_summary()
        module_labels = {module["id"]: module["label"] for module in self._matrix["canonical_modules"]}
        rows = []
        for subtype in self._matrix["subtypes"]:
            release = subtype.get("release", {"state": "planned"})
            content_status = release.get("state")
            content_ready = content_status in {"released", "reviewed_release_ready"}
            available = content_ready and subtype["id"] in self._available_subtype_ids
            row: dict[str, Any] = {
                "subtype_id": subtype["id"],
                "module_id": subtype["module_id"],
                "module_label": module_labels[subtype["module_id"]],
                "label": subtype["label"],
                "form": subtype["form"],
                "content_status": content_status,
                "availability": "available" if available else "planned",
                "launch": (
                    "/v1/judgment/workspace"
                    if subtype["id"] == "xingce.judgment.conditional_logic" and available
                    else f"/v1/xingce/adaptive/{subtype['id']}/workspace" if available else None
                ),
                "unavailable_reason": (
                    None if available
                    else "local_reviewed_pack_not_registered" if content_ready
                    else "reviewed_type_specific_pack_required"
                ),
            }
            if available:
                row["pack"] = {
                    "pack_id": release["pack_id"],
                    "pack_version": release["pack_version"],
                }
            rows.append(row)
        summary["available_subtypes"] = sum(row["availability"] == "available" for row in rows)
        for module_id, module in summary["modules"].items():
            module["available"] = sum(
                row["module_id"] == module_id and row["availability"] == "available"
                for row in rows
            )
        return {
            "schema_version": XINGCE_COVERAGE_CATALOG_SCHEMA,
            "local_only": True,
            "summary": summary,
            "items": rows,
        }
