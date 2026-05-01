from __future__ import annotations

import re
from pathlib import Path

from ..commands import fail, output, run
from ..paths import PATHS


def persist_mount_unit_name(mount_path: Path) -> str:
    """Return the systemd mount unit name for a mount path.

    :return: The requested value or status result.
    """
    return output(["systemd-escape", "--path", "--suffix=mount", mount_path])


def write_persist_mount_unit(persist_spec: str, mount_path: Path, fs_type: str) -> str:
    """Write persist mount unit configuration.

    :return: The requested value or status result.
    """
    if not persist_spec:
        fail("Persistent mount spec must not be empty.")
    if "\n" in persist_spec or re.fullmatch(r"[A-Za-z0-9_./:=-]+", persist_spec) is None:
        fail(f"Persistent mount spec contains unsupported characters: {persist_spec}")
    unit_name = persist_mount_unit_name(mount_path)
    unit_path = Path("/etc/systemd/system") / unit_name
    unit_path.write_text(
        f"""[Unit]
Description=bluetooth_2_usb persistent storage mount
Before=local-fs.target bluetooth.service {PATHS.service_unit}

[Mount]
What={persist_spec}
Where={mount_path}
Type={fs_type}
Options=defaults,noatime

[Install]
WantedBy=local-fs.target
""",
        encoding="utf-8",
    )
    unit_path.chmod(0o644)
    return unit_name


def remove_persist_mount_unit(mount_path: Path) -> None:
    """Remove persist mount unit state.

    :return: None.
    """
    unit = persist_mount_unit_name(mount_path)
    (Path("/etc/systemd/system") / unit).unlink(missing_ok=True)


def write_bluetooth_bind_mount_unit(source_dir: Path, persist_mount: Path) -> None:
    """Write bluetooth bind mount unit configuration.

    :return: None.
    """
    Path("/var/lib/bluetooth").mkdir(parents=True, exist_ok=True)
    parent_unit = persist_mount_unit_name(persist_mount)
    PATHS.bluetooth_bind_mount_unit.write_text(
        f"""[Unit]
Description=bluetooth_2_usb persistent Bluetooth state bind mount
After={parent_unit}
Requires={parent_unit}
Before=bluetooth.service {PATHS.service_unit}

[Mount]
What={source_dir}
Where=/var/lib/bluetooth
Type=none
Options=bind

[Install]
WantedBy=local-fs.target
""",
        encoding="utf-8",
    )
    PATHS.bluetooth_bind_mount_unit.chmod(0o644)


def remove_bluetooth_bind_mount_unit() -> None:
    """Remove bluetooth bind mount unit state.

    :return: None.
    """
    PATHS.bluetooth_bind_mount_unit.unlink(missing_ok=True)


def install_bluetooth_persist_dropin() -> None:
    """Install bluetooth persist dropin resources.

    :return: None.
    """
    PATHS.bluetooth_service_dropin_dir.mkdir(parents=True, exist_ok=True)
    PATHS.bluetooth_service_dropin.write_text(
        """[Unit]
After=var-lib-bluetooth.mount
Requires=var-lib-bluetooth.mount
RequiresMountsFor=/var/lib/bluetooth

[Service]
""",
        encoding="utf-8",
    )
    PATHS.bluetooth_service_dropin.chmod(0o644)


def remove_bluetooth_persist_dropin() -> None:
    """Remove bluetooth persist dropin state.

    :return: None.
    """
    PATHS.bluetooth_service_dropin.unlink(missing_ok=True)
    try:
        PATHS.bluetooth_service_dropin_dir.rmdir()
    except OSError:
        pass


def persist_spec_from_device(device: str) -> str:
    """Return a stable filesystem specifier for a persistence block device.

    :return: The requested value or status result.
    """
    uuid = run(
        ["blkid", "-s", "UUID", "-o", "value", device], check=False, capture=True
    ).stdout.strip()
    if not uuid:
        fail(f"Could not determine UUID for {device}")
    return f"/dev/disk/by-uuid/{uuid}"
