from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .boot_config import (
    boot_cmdline_path,
    configured_initramfs_file,
    configured_kernel_image,
    current_kernel_release,
    current_root_filesystem_type,
    ensure_bootable_initramfs_for_current_kernel,
    expected_boot_initramfs_file,
    versioned_initrd_candidates,
)
from .commands import fail, info, ok, output, require_commands, run, warn
from .paths import PATHS

READONLY_PACKAGES = ("overlayroot", "cryptsetup", "cryptsetup-bin", "initramfs-tools")


@dataclass(slots=True)
class ReadonlyConfig:
    mode: str = "disabled"
    persist_mount: Path = PATHS.persist_mount
    persist_bluetooth_dir: Path = PATHS.default_persist_bluetooth_dir
    persist_spec: str = ""
    persist_device: str = ""


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


def load_readonly_config(path: Path = PATHS.readonly_env_file) -> ReadonlyConfig:
    config = ReadonlyConfig()
    if not path.is_file():
        return config

    allowed = {
        "B2U_READONLY_MODE",
        "B2U_PERSIST_MOUNT",
        "B2U_PERSIST_BLUETOOTH_DIR",
        "B2U_PERSIST_SPEC",
        "B2U_PERSIST_DEVICE",
    }
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"', line)
        if match is None:
            fail(
                f"Refusing to load invalid read-only config line from {path}:{line_number}: {line}"
            )
        key, value = match.groups()
        if key not in allowed:
            fail(f"Refusing to load unexpected key from {path}: {key}")
        values[key] = value

    return ReadonlyConfig(
        mode=values.get("B2U_READONLY_MODE", "disabled"),
        persist_mount=Path(values.get("B2U_PERSIST_MOUNT", str(PATHS.persist_mount))),
        persist_bluetooth_dir=Path(
            values.get("B2U_PERSIST_BLUETOOTH_DIR", str(PATHS.default_persist_bluetooth_dir))
        ),
        persist_spec=values.get("B2U_PERSIST_SPEC", ""),
        persist_device=values.get("B2U_PERSIST_DEVICE", ""),
    )


def write_readonly_config(config: ReadonlyConfig, path: Path = PATHS.readonly_env_file) -> None:
    path.write_text(
        "\n".join(
            [
                f'B2U_READONLY_MODE="{config.mode}"',
                f'B2U_PERSIST_MOUNT="{config.persist_mount}"',
                f'B2U_PERSIST_BLUETOOTH_DIR="{config.persist_bluetooth_dir}"',
                f'B2U_PERSIST_SPEC="{config.persist_spec}"',
                f'B2U_PERSIST_DEVICE="{config.persist_device}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o644)


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
    relative = "/" + str(resolved.persist_bluetooth_dir.relative_to(resolved.persist_mount))
    return mount_source == f"{persist_mount_source}[{relative}]"


def readonly_mode() -> str:
    try:
        root_fstype = current_root_filesystem_type()
    except Exception:
        return "unknown"
    if root_fstype == "overlay" and bluetooth_state_persistent():
        return "persistent"
    return "disabled"


def persist_mount_unit_name(mount_path: Path) -> str:
    return output(["systemd-escape", "--path", "--suffix=mount", mount_path])


def write_persist_mount_unit(persist_spec: str, mount_path: Path, fs_type: str) -> str:
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
    unit = persist_mount_unit_name(mount_path)
    (Path("/etc/systemd/system") / unit).unlink(missing_ok=True)


def write_bluetooth_bind_mount_unit(source_dir: Path) -> None:
    Path("/var/lib/bluetooth").mkdir(parents=True, exist_ok=True)
    parent_unit = persist_mount_unit_name(source_dir.parent)
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
    PATHS.bluetooth_bind_mount_unit.unlink(missing_ok=True)


def install_bluetooth_persist_dropin() -> None:
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
    PATHS.bluetooth_service_dropin.unlink(missing_ok=True)
    try:
        PATHS.bluetooth_service_dropin_dir.rmdir()
    except OSError:
        pass


def persist_spec_from_device(device: str) -> str:
    uuid = run(
        ["blkid", "-s", "UUID", "-o", "value", device], check=False, capture=True
    ).stdout.strip()
    if not uuid:
        fail(f"Could not determine UUID for {device}")
    return f"/dev/disk/by-uuid/{uuid}"


def setup_persistent_bluetooth_state(device: str) -> None:
    require_commands(["blkid", "cp", "mkdir", "mount", "mountpoint", "systemctl", "systemd-escape"])
    if not machine_id_valid():
        fail(
            "/etc/machine-id is missing or invalid. Persistent read-only mode requires a stable machine-id."
        )
    detected_type = run(
        ["blkid", "-s", "TYPE", "-o", "value", device], check=False, capture=True
    ).stdout.strip()
    if not detected_type:
        fail(
            f"No filesystem detected on {device}. Create an ext4 filesystem first, then rerun this command."
        )
    if detected_type != "ext4":
        fail(f"Expected ext4 on {device}, got {detected_type}")

    current = load_readonly_config()
    persist_mount = current.persist_mount
    persist_bluetooth_dir = persist_mount / PATHS.persist_bluetooth_subdir
    persist_spec = persist_spec_from_device(device)
    persist_mount.mkdir(parents=True, exist_ok=True)
    persist_mount_unit = write_persist_mount_unit(persist_spec, persist_mount, "ext4")
    write_bluetooth_bind_mount_unit(persist_bluetooth_dir)
    install_bluetooth_persist_dropin()
    write_readonly_config(
        ReadonlyConfig(
            mode="disabled",
            persist_mount=persist_mount,
            persist_bluetooth_dir=persist_bluetooth_dir,
            persist_spec=persist_spec,
            persist_device=device,
        )
    )

    _stop_b2u_if_installed("before migrating Bluetooth state")
    run(["systemctl", "stop", "bluetooth.service"])
    run(["systemctl", "daemon-reload"])
    if run(["mountpoint", "-q", persist_mount], check=False).returncode == 0:
        run(["systemctl", "stop", persist_mount_unit], check=False)
        if run(["mountpoint", "-q", persist_mount], check=False).returncode == 0:
            run(["umount", persist_mount])
    run(["systemctl", "enable", "--now", persist_mount_unit])
    persist_bluetooth_dir.mkdir(parents=True, exist_ok=True)
    _seed_bluetooth_state(persist_bluetooth_dir)

    if run(["mountpoint", "-q", "/var/lib/bluetooth"], check=False).returncode == 0:
        current_source = output(["findmnt", "-n", "-o", "SOURCE", "--target", "/var/lib/bluetooth"])
        if current_source != str(persist_bluetooth_dir):
            run(["umount", "/var/lib/bluetooth"])
    Path("/var/lib/bluetooth").mkdir(parents=True, exist_ok=True)
    run(["systemctl", "enable", "--now", "var-lib-bluetooth.mount"])
    run(["systemctl", "start", "bluetooth.service"])
    if not _systemctl_active("bluetooth.service"):
        fail("bluetooth.service did not come back up after enabling the persistent bind mount")
    _restart_b2u_if_installed("after enabling the persistent bind mount")
    ok(f"Persistent Bluetooth state is active at {persist_bluetooth_dir}")


def _seed_bluetooth_state(persist_bluetooth_dir: Path) -> None:
    source = Path("/var/lib/bluetooth")
    if not source.is_dir():
        return
    lock_dir = persist_bluetooth_dir / ".b2u-seed.lock"
    marker = persist_bluetooth_dir / ".b2u-seeded"
    try:
        lock_dir.mkdir()
    except OSError:
        fail(f"Failed to acquire seed lock {lock_dir} for {persist_bluetooth_dir}")
    try:
        ignored = {".b2u-seed.lock", ".b2u-seeded", ".b2u-persistent-state"}
        if not marker.exists() and not any(
            child.name not in ignored for child in persist_bluetooth_dir.iterdir()
        ):
            for child in source.iterdir():
                destination = persist_bluetooth_dir / child.name
                if child.is_dir():
                    shutil.copytree(child, destination, symlinks=True, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, destination)
            marker.touch()
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass
    (persist_bluetooth_dir / ".b2u-persistent-state").touch()


def enable_readonly() -> None:
    require_commands(["dpkg-query", "raspi-config"])
    config = load_readonly_config()
    if not machine_id_valid():
        fail(
            "/etc/machine-id is missing or invalid. Persistent read-only mode requires a stable machine-id."
        )
    if not config.persist_spec:
        fail("Run bluetooth_2_usb readonly-setup --device /dev/... before enabling read-only mode.")
    if not bluetooth_state_persistent(config):
        fail(
            "Persistent Bluetooth state is not active. Run bluetooth_2_usb readonly-setup --device /dev/... first."
        )
    if not readonly_stack_packages_bootstrap_safe():
        warn("OverlayFS package state is incomplete:")
        print(readonly_stack_package_report())
        fail(
            "OverlayFS package setup did not complete cleanly. Repair the package state before enabling read-only mode."
        )

    kernel_release = current_kernel_release()
    info(f"Kernel release: {kernel_release}")
    info(f"Configured kernel image: {configured_kernel_image()}")
    info(f"Explicit initramfs entry: {configured_initramfs_file() or '<none>'}")
    info(f"Expected boot initramfs file: {expected_boot_initramfs_file() or '<none>'}")
    info(
        "Versioned initramfs candidates: "
        + (" ".join(str(path) for path in versioned_initrd_candidates(kernel_release)) or "<none>")
    )

    if overlay_status() != "enabled":
        if readonly_stack_packages_missing():
            info(
                "OverlayFS prerequisites are not fully installed yet; raspi-config will install or finish them now."
            )
        run(["raspi-config", "nonint", "enable_overlayfs"])
    if not readonly_stack_packages_healthy():
        warn("OverlayFS package state is incomplete:")
        print(readonly_stack_package_report())
        fail(
            "OverlayFS package setup did not complete cleanly. Repair the package state before enabling read-only mode."
        )

    target = ensure_bootable_initramfs_for_current_kernel()
    ok(f"Boot initramfs is ready at {target}")
    if overlay_status() != "enabled":
        cmdline = (
            boot_cmdline_path().read_text(encoding="utf-8", errors="replace")
            if boot_cmdline_path().is_file()
            else ""
        )
        if overlay_configured_status() == "enabled":
            warn(
                "OverlayFS is configured for the next boot, but the live root is still writable until reboot."
            )
        elif re.search(r"(^| )overlayroot=tmpfs($| )", cmdline):
            warn(
                f"OverlayFS enablement is pending reboot; {boot_cmdline_path()} contains overlayroot=tmpfs even though the live status still reports disabled."
            )
        else:
            fail("OverlayFS is still not configured after raspi-config completed.")
    config.mode = "persistent"
    write_readonly_config(config)
    ok("OverlayFS has been enabled")
    warn("Boot partition read-only mode is intentionally not changed by this command.")
    warn(
        "Persistent read-only mode is configured. Reboot, then run bluetooth_2_usb smoketest --verbose and verify reconnect behavior."
    )


def disable_readonly() -> None:
    require_commands(["raspi-config"])
    config = load_readonly_config()
    run(["raspi-config", "nonint", "disable_overlayfs"])
    config.mode = "disabled"
    write_readonly_config(config)
    ok("OverlayFS has been disabled")
    warn(
        "Persistent Bluetooth mount configuration was kept. Reboot to return to a writable root filesystem."
    )


def _systemctl_active(unit: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def _stop_b2u_if_installed(context: str) -> None:
    from .deployment import service_installed

    state = service_installed()
    if state is None:
        fail(f"Unable to query systemd for {PATHS.service_unit} {context}")
    if state:
        run(["systemctl", "stop", PATHS.service_unit])


def _restart_b2u_if_installed(context: str) -> None:
    from .deployment import service_installed

    state = service_installed()
    if state is None:
        fail(f"Unable to query systemd for {PATHS.service_unit} {context}")
    if state:
        run(["systemctl", "restart", PATHS.service_unit])
        if not _systemctl_active(PATHS.service_unit):
            fail(f"{PATHS.service_unit} did not come back up {context}")
