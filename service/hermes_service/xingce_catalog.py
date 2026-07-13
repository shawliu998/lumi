"""Safe public projection of Lumi's all-Xingce coverage contract.

This is intentionally a status catalogue, not a question catalogue: it lets
the client show what is genuinely available without leaking draft content or
pretending that representative fixtures constitute a released subtype.
"""

from __future__ import annotations

from typing import Any

from hermes_domains.xingce_coverage import coverage_summary, load_coverage_matrix


XINGCE_COVERAGE_CATALOG_SCHEMA = "lumi.xingce-coverage-catalog.v1"


class XingceCoverageCatalog:
    def __init__(self) -> None:
        self._matrix = load_coverage_matrix()

    def public_projection(self) -> dict[str, Any]:
        summary = coverage_summary()
        module_labels = {module["id"]: module["label"] for module in self._matrix["canonical_modules"]}
        rows = []
        for subtype in self._matrix["subtypes"]:
            release = subtype.get("release", {"state": "planned"})
            available = release.get("state") == "released"
            row: dict[str, Any] = {
                "subtype_id": subtype["id"],
                "module_id": subtype["module_id"],
                "module_label": module_labels[subtype["module_id"]],
                "label": subtype["label"],
                "form": subtype["form"],
                "availability": "available" if available else "planned",
                "launch": "/v1/judgment/workspace" if subtype["id"] == "xingce.judgment.conditional_logic" and available else None,
                "unavailable_reason": None if available else "reviewed_type_specific_pack_required",
            }
            if available:
                row["pack"] = {
                    "pack_id": release["pack_id"],
                    "pack_version": release["pack_version"],
                }
            rows.append(row)
        return {
            "schema_version": XINGCE_COVERAGE_CATALOG_SCHEMA,
            "local_only": True,
            "summary": summary,
            "items": rows,
        }
