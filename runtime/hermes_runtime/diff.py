from __future__ import annotations

from typing import Any, Mapping


_MISSING = object()


def state_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic, JSON-Patch-like state changes."""

    changes: list[dict[str, Any]] = []

    def walk(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                child = f"{path}/{_escape(str(key))}"
                lval = left.get(key, _MISSING)
                rval = right.get(key, _MISSING)
                if lval is _MISSING:
                    changes.append({"op": "add", "path": child, "value": rval})
                elif rval is _MISSING:
                    changes.append({"op": "remove", "path": child, "old": lval})
                else:
                    walk(lval, rval, child)
            return
        if left != right:
            changes.append({"op": "replace", "path": path or "/", "old": left, "value": right})

    walk(dict(before), dict(after), "")
    return changes


def _escape(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")
