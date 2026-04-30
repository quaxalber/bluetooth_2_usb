from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .commands import OpsError, fail, run, warn
from .paths import PATHS


def loopback_inject(argv: list[str]) -> int:
    if any(arg in {"-h", "--help"} for arg in argv):
        python = str(PATHS.venv_python if PATHS.venv_python.exists() else sys.executable)
        os.execv(python, [python, "-m", "bluetooth_2_usb.loopback", "inject", *argv])
        return 127
    if not PATHS.venv_python.exists():
        fail(f"Managed Python not found: {PATHS.venv_python}")
    settle_raw = os.environ.get("B2U_LOOPBACK_SERVICE_SETTLE_SEC", "10")
    try:
        settle = float(settle_raw)
        if settle < 0:
            raise ValueError
    except ValueError:
        warn(f"Ignoring invalid B2U_LOOPBACK_SERVICE_SETTLE_SEC={settle_raw}; using default 10")
        settle = 10.0
    _wait_for_service_settle(settle)
    os.execv(str(PATHS.venv_python), [str(PATHS.venv_python), "-m", "bluetooth_2_usb.loopback", "inject", *argv])
    return 127


def _wait_for_service_settle(settle_seconds: float) -> None:
    if settle_seconds == 0:
        return
    if run(["systemctl", "is-active", "--quiet", PATHS.service_unit], check=False).returncode != 0:
        return
    raw = run(
        ["systemctl", "show", PATHS.service_unit, "--property=ActiveEnterTimestampMonotonic", "--value"],
        check=False,
        capture=True,
    ).stdout.strip()
    if not raw or raw == "0":
        return
    try:
        active_since_us = int(raw)
    except ValueError:
        return
    uptime = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
    now_us = int(float(uptime) * 1_000_000)
    settle_us = int(settle_seconds * 1_000_000)
    age_us = now_us - active_since_us
    if age_us < settle_us:
        time.sleep((settle_us - age_us) / 1_000_000)


def loopback_capture(repo_root: Path, argv: list[str]) -> int:
    python_bin = _host_capture_python(repo_root)
    env = os.environ.copy()
    pythonpath = str(repo_root / "src")
    env["PYTHONPATH"] = pythonpath + (f"{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else "")
    os.execvpe(python_bin, [python_bin, "-m", "bluetooth_2_usb.loopback", "capture", *argv], env)
    return 127


def _host_capture_python(repo_root: Path) -> str:
    override = os.environ.get("HOST_CAPTURE_PYTHON")
    if override:
        return override
    candidates = [repo_root / "venv/bin/python", repo_root / "venv/Scripts/python.exe", Path("python3"), Path("python")]
    for candidate in candidates:
        command = [str(candidate), "-c", "import hid"]
        try:
            completed = run(command, check=False, capture=True)
        except OpsError:
            continue
        if completed.returncode == 0:
            return str(candidate)
    fail("No suitable Python with hidapi found. Set HOST_CAPTURE_PYTHON or install the Python package 'hidapi'.")
    return sys.executable
