"""Loopback-only sidecar API for the Lumi local client."""

from pathlib import Path
import sys

_repo = Path(__file__).resolve().parents[2]
for _name in ("domains", "engine", "runtime", "integration", "study_pack"):
    _path = str(_repo / _name)
    if _path not in sys.path:
        sys.path.append(_path)

from .api import SidecarApplication, create_server

__all__ = ["SidecarApplication", "create_server"]
