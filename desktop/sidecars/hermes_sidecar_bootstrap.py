"""PyInstaller entry point for the immutable local Lumi sidecar contract."""

from pathlib import Path
import os
import signal
import sys
import threading
import time

# The service intentionally resolves fixtures relative to the workspace tree.
# In a one-file executable, preserve that read-only layout inside PyInstaller's
# extraction directory without changing the shared service package.
if getattr(sys, "frozen", False):
    from hermes_service import catalog
    from hermes_domains import product_activity

    catalog.FIXTURE_ROOT = Path(sys._MEIPASS) / "domains" / "fixtures"
    catalog.PRODUCT_ACTIVITY_PAYLOAD = (
        Path(sys._MEIPASS)
        / "domains"
        / "local_content"
        / "xingce"
        / "p031-data-analysis-v1.json"
    )
    product_activity.DEFAULT_RELEASE_ROOT = (
        Path(sys._MEIPASS)
        / "domains"
        / "content"
        / "xingce"
        / "p031-data-analysis-v1"
    )
    product_activity.DEFAULT_MANIFEST_PATH = (
        product_activity.DEFAULT_RELEASE_ROOT / "manifest.json"
    )
    product_activity.DEFAULT_OVERLAY_PATH = (
        product_activity.DEFAULT_RELEASE_ROOT / "pedagogical-overlay.json"
    )
    product_activity.DEFAULT_PAYLOAD_PATH = catalog.PRODUCT_ACTIVITY_PAYLOAD
    os.environ.setdefault(
        "LUMI_JUDGMENT_PACK_ROOT",
        str(
            Path(sys._MEIPASS)
            / "domains"
            / "released"
            / "judgment"
            / "lumi-conditional-reasoning-v0-0.1.0-reviewed-local-20260713"
        ),
    )
    os.environ.setdefault(
        "LUMI_XINGCE_ADAPTIVE_PACK_ROOTS",
        str(Path(sys._MEIPASS) / "domains" / "released" / "xingce"),
    )

from hermes_service.cli import main


def _parent_death_watchdog(parent_pid: int) -> None:
    """Exit if the Tauri parent goes away before it can reap this process."""
    while True:
        time.sleep(0.5)
        if os.getppid() == 1:
            os.kill(os.getpid(), signal.SIGTERM)
            return
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            os.kill(os.getpid(), signal.SIGTERM)
            return


_parent_pid = os.getppid()
threading.Thread(
    target=_parent_death_watchdog,
    args=(_parent_pid,),
    daemon=True,
    name="hermes-parent-death-watchdog",
).start()


if __name__ == "__main__":
    raise SystemExit(main())
