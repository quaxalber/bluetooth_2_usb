from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..boot_config import current_root_filesystem_type
from ..commands import run
from .config import ReadonlyConfig, load_readonly_config

READONLY_PACKAGES = ("overlayroot", "cryptsetup", "cryptsetup-bin", "initramfs-tools")


def overlay_status() -> str:
    if shutil.which("raspi-config") is None:
        return "unknown"
    for command in (
        ["raspi-config", "nonint", "get_overlay_now"],
        ["raspi-config", "nonint", "get_overlay_conf"],
    ):
        completed = run(command, check=False, capture=True)
        if completed.returncode == 0:
            return _overlay_state_from_code(completed.stdout.strip())
    return "unknown"


def overlay_configured_status() -> str:
    if shutil.which("raspi-config") is None:
        return "unknown"
    completed = run(["raspi-config", "nonint", "get_overlay_conf"], check=False, capture=True)
    if completed.returncode != 0:
        return "unknown"
    return _overlay_state_from_code(completed.stdout.strip())


def _overlay_state_from_code(raw: str) -> str:
    state = "".join(raw.split())
    if state == "0":
        return "enabled"
    if state == "1":
        return "disabled"
    return "unknown"


def package_status(package: str) -> str:
    completed = run(["dpkg-query", "-W", "-f=${Status}", package], check=False, capture=True)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def readonly_stack_packages_healthy() -> bool:
    return all(package_status(package) == "install ok installed" for package in READONLY_PACKAGES)


def readonly_stack_packages_bootstrap_safe() -> bool:
    return all(
        package_status(package) in {"", "install ok installed"} for package in READONLY_PACKAGES
    )


def readonly_stack_packages_missing() -> bool:
    return any(package_status(package) != "install ok installed" for package in READONLY_PACKAGES)


def readonly_stack_package_report() -> str:
    lines = []
    for package in READONLY_PACKAGES:
        status = package_status(package) or "not installed"
        lines.append(f"{package}: {status}")
    return "\n".join(lines)


def machine_id_valid() -> bool:
    machine_id = Path("/etc/machine-id")
    return (
        machine_id.is_file()
        and re.fullmatch(r"[0-9a-f]{32}", machine_id.read_text(encoding="utf-8").strip())
        is not None
    )


def bluetooth_state_persistent(config: ReadonlyConfig | None = None) -> bool:
    resolved = load_readonly_config() if config is None else config
    if run(["mountpoint", "-q", "/var/lib/bluetooth"], check=False).returncode != 0:
        return False
    if not resolved.persist_bluetooth_dir.is_dir():
        return False

    mount_source = run(
        ["findmnt", "-n", "-o", "SOURCE", "--target", "/var/lib/bluetooth"],
        check=False,
        capture=True,
    ).stdout.strip()
    if mount_source == str(resolved.persist_bluetooth_dir):
        return True

    persist_mount_source = run(
        ["findmnt", "-n", "-o", "SOURCE", "--target", resolved.persist_mount],
        check=False,
        capture=True,
    ).stdout.strip()
    if not persist_mount_source:
        return False
    try:
        relative = "/" + str(resolved.persist_bluetooth_dir.relative_to(resolved.persist_mount))
    except ValueError:
        return False
    return mount_source == f"{persist_mount_source}[{relative}]"


def readonly_mode() -> str:
    try:
        root_fstype = current_root_filesystem_type()
    except Exception:
        return "unknown"
    if root_fstype == "overlay" and bluetooth_state_persistent():
        return "persistent"
    return "disabled"
