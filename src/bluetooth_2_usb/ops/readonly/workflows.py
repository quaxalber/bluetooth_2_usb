from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from ..boot_config import (
    boot_cmdline_path,
    configured_initramfs_file,
    configured_kernel_image,
    current_kernel_release,
    ensure_bootable_initramfs_for_current_kernel,
    expected_boot_initramfs_file,
    versioned_initrd_candidates,
)
from ..commands import fail, info, ok, output, require_commands, run, warn
from .config import ReadonlyConfig, load_readonly_config, write_readonly_config
from .service import _systemctl_active, restart_b2u_if_installed, stop_b2u_if_installed
from .status import (
    bluetooth_state_persistent,
    machine_id_valid,
    overlay_configured_status,
    overlay_status,
    readonly_stack_package_report,
    readonly_stack_packages_bootstrap_safe,
    readonly_stack_packages_healthy,
    readonly_stack_packages_missing,
)
from .units import (
    install_bluetooth_persist_dropin,
    persist_spec_from_device,
    write_bluetooth_bind_mount_unit,
    write_persist_mount_unit,
)


def setup_persistent_bluetooth_state(device: str) -> None:
    require_commands(
        ["blkid", "cp", "findmnt", "mkdir", "mount", "mountpoint", "systemctl", "systemd-escape", "umount"]
    )
    if not machine_id_valid():
        fail("/etc/machine-id is missing or invalid. Read-only mode requires a stable machine-id.")
    detected_type = run(["blkid", "-s", "TYPE", "-o", "value", device], check=False, capture=True).stdout.strip()
    if not detected_type:
        fail(f"No filesystem detected on {device}. Create an ext4 filesystem first, then rerun this command.")
    if detected_type != "ext4":
        fail(f"Expected ext4 on {device}, got {detected_type}")

    current = load_readonly_config()
    persist_mount = current.persist_mount
    persist_bluetooth_dir = current.persist_bluetooth_dir
    persist_spec = persist_spec_from_device(device)
    persist_mount.mkdir(parents=True, exist_ok=True)
    persist_mount_unit = write_persist_mount_unit(persist_spec, persist_mount, "ext4")
    write_bluetooth_bind_mount_unit(persist_bluetooth_dir, persist_mount)
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

    bluetooth_was_active = _systemctl_active("bluetooth.service")
    b2u_was_active = stop_b2u_if_installed("before migrating Bluetooth state")
    try:
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
        if bluetooth_was_active:
            run(["systemctl", "start", "bluetooth.service"])
        if bluetooth_was_active and not _systemctl_active("bluetooth.service"):
            fail("bluetooth.service did not come back up after enabling the writable Bluetooth state bind mount")
    finally:
        if bluetooth_was_active and not _systemctl_active("bluetooth.service"):
            run(["systemctl", "start", "bluetooth.service"], check=False)
        elif not bluetooth_was_active and _systemctl_active("bluetooth.service"):
            run(["systemctl", "stop", "bluetooth.service"], check=False)
        restart_b2u_if_installed(b2u_was_active, "after enabling the writable Bluetooth state bind mount")
    ok(f"Writable Bluetooth state storage is active at {persist_bluetooth_dir}")


def _seed_bluetooth_state(persist_bluetooth_dir: Path) -> None:
    source = Path("/var/lib/bluetooth")
    if not source.is_dir():
        return
    lock_dir = persist_bluetooth_dir / ".b2u-seed.lock"
    marker = persist_bluetooth_dir / ".b2u-seeded"
    temp_dir = persist_bluetooth_dir.with_name(f"{persist_bluetooth_dir.name}.tmp-{uuid.uuid4().hex}")
    backup_dir = persist_bluetooth_dir.with_name(f"{persist_bluetooth_dir.name}.backup-{uuid.uuid4().hex}")
    try:
        lock_dir.mkdir()
    except OSError:
        fail(f"Failed to acquire seed lock {lock_dir} for {persist_bluetooth_dir}")
    try:
        ignored = {".b2u-seed.lock", ".b2u-seeded", ".b2u-persistent-state"}
        if not marker.exists() and not any(child.name not in ignored for child in persist_bluetooth_dir.iterdir()):
            temp_dir.mkdir(parents=True)
            for child in source.iterdir():
                destination = temp_dir / child.name
                if child.is_dir():
                    shutil.copytree(child, destination, symlinks=True, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, destination)
            persist_bluetooth_dir.rename(backup_dir)
            try:
                temp_dir.rename(persist_bluetooth_dir)
                marker.touch()
            except Exception:
                if persist_bluetooth_dir.exists():
                    shutil.rmtree(persist_bluetooth_dir)
                backup_dir.rename(persist_bluetooth_dir)
                raise
            else:
                shutil.rmtree(backup_dir, ignore_errors=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)
        try:
            lock_dir.rmdir()
        except OSError:
            pass
    (persist_bluetooth_dir / ".b2u-persistent-state").touch()


def enable_readonly() -> None:
    require_commands(["dpkg-query", "raspi-config"])
    config = load_readonly_config()
    if not machine_id_valid():
        fail("/etc/machine-id is missing or invalid. Read-only mode requires a stable machine-id.")
    if not config.persist_spec:
        fail("Run bluetooth_2_usb readonly setup --device /dev/... before enabling read-only mode.")
    if not bluetooth_state_persistent(config):
        fail(
            "Writable Bluetooth state storage is not active. "
            + "Run bluetooth_2_usb readonly setup --device /dev/... first."
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

    overlay_before = overlay_status()
    try:
        if overlay_before != "enabled":
            if readonly_stack_packages_missing():
                info(
                    "OverlayFS prerequisites are not fully installed yet; raspi-config will install or finish them now."
                )
            run(["raspi-config", "nonint", "enable_overlayfs"])

        if not readonly_stack_packages_healthy():
            warn("OverlayFS package state is incomplete:")
            print(readonly_stack_package_report())
            fail(
                "OverlayFS package setup did not complete cleanly. "
                + "Repair the package state before enabling read-only mode."
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
                warn("OverlayFS is configured for the next boot, but the live root is still writable until reboot.")
            elif re.search(r"(^| )overlayroot=tmpfs($| )", cmdline):
                warn(
                    f"OverlayFS enablement is pending reboot; {boot_cmdline_path()} contains overlayroot=tmpfs "
                    + "even though the live status still reports disabled."
                )
            else:
                fail("OverlayFS is still not configured after raspi-config completed.")
        config.mode = "persistent"
        write_readonly_config(config)
    except Exception:
        warn(
            "OverlayFS was requested but validation did not complete. "
            + "Run `bluetooth_2_usb readonly status` and repair the reported package or boot state before rebooting. "
            + "See: https://github.com/quaxalber/bluetooth_2_usb/blob/main/docs/persistent-readonly.md"
            + "#overlayfs-repair-guidance "
            + "for repair steps. "
            + "To explicitly disable OverlayFS, run: sudo bluetooth_2_usb readonly disable"
        )
        raise
    ok("OverlayFS has been enabled")
    warn("Boot partition read-only mode is intentionally not changed by this command.")
    warn(
        "Read-only mode is configured. Reboot, then run bluetooth_2_usb smoketest --verbose "
        + "and verify reconnect behavior."
    )


def disable_readonly() -> None:
    require_commands(["raspi-config"])
    config = load_readonly_config()
    run(["raspi-config", "nonint", "disable_overlayfs"])
    config.mode = "disabled"
    write_readonly_config(config)
    ok("OverlayFS has been disabled")
    warn("Writable Bluetooth state mount configuration was kept. Reboot to return to a writable root filesystem.")
