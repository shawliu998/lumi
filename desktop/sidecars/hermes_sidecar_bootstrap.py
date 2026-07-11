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

    catalog.FIXTURE_ROOT = Path(sys._MEIPASS) / "domains" / "fixtures"

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
