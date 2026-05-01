from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..boot_config import current_root_filesystem_type
from ..commands import run
from .config import ReadonlyConfig, load_readonly_config

READONLY_PACKAGES = ("overlayroot", "cryptsetup", "cryptsetup-bin", "initramfs-tools")


def overlay_status() -> str:
    """Return the live OverlayFS status reported by raspi-config.

    :return: The requested value or status result.
    """
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
    """Return the next-boot OverlayFS status reported by raspi-config.

    :return: The requested value or status result.
    """
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
    """Return the dpkg status string for one package.

    :return: The requested value or status result.
    """
    completed = run(["dpkg-query", "-W", "-f=${Status}", package], check=False, capture=True)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def readonly_stack_packages_healthy() -> bool:
    """Return whether readonly stack packages healthy is true.

    :return: The requested value or status result.
    """
    return all(package_status(package) == "install ok installed" for package in READONLY_PACKAGES)


def readonly_stack_packages_bootstrap_safe() -> bool:
    """Return whether readonly stack packages bootstrap safe is true.

    :return: The requested value or status result.
    """
    return all(
        package_status(package) in {"", "install ok installed"} for package in READONLY_PACKAGES
    )


def readonly_stack_packages_missing() -> bool:
    """Return whether readonly stack packages missing is true.

    :return: The requested value or status result.
    """
    return any(package_status(package) != "install ok installed" for package in READONLY_PACKAGES)


def readonly_stack_package_report() -> str:
    """Return a comma-separated package health report for readonly prerequisites.

    :return: The requested value or status result.
    """
    lines = []
    for package in READONLY_PACKAGES:
        status = package_status(package) or "not installed"
        lines.append(f"{package}: {status}")
    return "\n".join(lines)


def machine_id_valid() -> bool:
    """Return whether /etc/machine-id contains a valid persistent identifier.

    :return: The requested value or status result.
    """
    machine_id = Path("/etc/machine-id")
    return (
        machine_id.is_file()
        and re.fullmatch(r"[0-9a-f]{32}", machine_id.read_text(encoding="utf-8").strip())
        is not None
    )


def bluetooth_state_persistent(config: ReadonlyConfig | None = None) -> bool:
    """Return whether Bluetooth state is configured on persistent writable storage.

    :return: The requested value or status result.
    """
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
    """Return the configured persistent read-only mode.

    :return: The requested value or status result.
    """
    try:
        root_fstype = current_root_filesystem_type()
    except Exception:
        return "unknown"
    if root_fstype == "overlay" and bluetooth_state_persistent():
        return "persistent"
    return "disabled"


def print_readonly_status() -> None:
    """Print readonly status information.

    :return: None.
    """
    config = load_readonly_config()
    print("Read-only status")
    print(f"mode: {readonly_mode()}")
    print(f"configured_mode: {config.mode}")
    print(f"overlay_live: {overlay_status()}")
    print(f"overlay_configured: {overlay_configured_status()}")
    print(f"root_filesystem: {_root_filesystem_type()}")
    print(f"root_source: {_findmnt_value('/', 'SOURCE') or '<unknown>'}")
    print(f"bluetooth_state_persistent: {'yes' if bluetooth_state_persistent(config) else 'no'}")
    print(f"bluetooth_state_source: {_findmnt_value('/var/lib/bluetooth', 'SOURCE') or '<none>'}")
    print(f"persist_mount: {config.persist_mount}")
    print(f"persist_mount_active: {'yes' if _mountpoint(config.persist_mount) else 'no'}")
    print(f"persist_device: {config.persist_device or '<unset>'}")
    print(f"persist_spec: {config.persist_spec or '<unset>'}")


def _root_filesystem_type() -> str:
    try:
        return current_root_filesystem_type()
    except Exception:
        return "unknown"


def _findmnt_value(target: str | Path, field: str) -> str:
    completed = run(
        ["findmnt", "-n", "-o", field, "--target", target],
        check=False,
        capture=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _mountpoint(path: Path) -> bool:
    return run(["mountpoint", "-q", path], check=False).returncode == 0
