from __future__ import annotations

import shutil

from .commands import fail, info, ok, run
from .paths import PATHS

TRAY_APT_PACKAGES = ("python3-gi", "gir1.2-ayatanaappindicator3-0.1")


def tray_installed() -> bool:
    return PATHS.tray_autostart.exists()


def install_tray() -> None:
    """Install the desktop tray indicator's dependencies and autostart it for all desktop users."""
    if not PATHS.tray_script.is_file() or not PATHS.tray_desktop_entry.is_file():
        fail(f"Tray indicator files are missing from {PATHS.install_dir / 'desktop'}.")
    run(["apt-get", "install", "-y", "--no-install-recommends", *TRAY_APT_PACKAGES])
    _write_autostart_entry()
    ok(f"Tray indicator autostart installed at {PATHS.tray_autostart}")
    info("It starts with the next desktop login. To start it now, run as your desktop user:")
    info(f"  /usr/bin/python3 {PATHS.tray_script} &")


def refresh_tray_autostart() -> None:
    """Keep an existing autostart entry in sync with the checkout; no-op if the tray isn't installed."""
    if tray_installed():
        _write_autostart_entry()
        ok("Tray indicator autostart refreshed")


def uninstall_tray() -> None:
    PATHS.tray_autostart.unlink(missing_ok=True)
    ok("Tray indicator autostart removed")
    info("A running indicator keeps going until logout; quit it from its menu to stop it now.")


def _write_autostart_entry() -> None:
    PATHS.tray_autostart.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PATHS.tray_desktop_entry, PATHS.tray_autostart)
    PATHS.tray_autostart.chmod(0o644)
