from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from pathlib import Path

from ..boot_config import (
    boot_cmdline_path,
    configured_initramfs_file,
    configured_kernel_image,
    current_kernel_release,
    current_root_filesystem_type,
    ensure_bootable_initramfs_for_current_kernel,
    expected_boot_initramfs_file,
    versioned_initrd_candidates,
)
from ..commands import OpsError, backup_file, fail, info, ok, output, require_commands, run, warn
from .config import ReadonlyConfig, load_readonly_config, write_readonly_config
from .service import _systemctl_active, restart_b2u_if_installed, stop_b2u_if_installed
from .status import (
    READONLY_PACKAGES,
    bluetooth_state_persistent,
    machine_id_valid,
    overlay_configured_status,
    overlay_status,
    readonly_stack_package_report,
    readonly_stack_packages_healthy,
)
from .units import (
    install_bluetooth_persist_dropin,
    persist_spec_from_device,
    remove_bluetooth_bind_mount_unit,
    remove_bluetooth_persist_dropin,
    remove_persist_mount_unit,
    write_bluetooth_bind_mount_unit,
    write_persist_mount_unit,
)

INITRAMFS_CONF = Path("/etc/initramfs-tools/initramfs.conf")


def setup_persistent_bluetooth_state(device: str) -> None:
    require_commands(
        [
            "apt-get",
            "blkid",
            "cp",
            "dpkg",
            "dpkg-query",
            "findmnt",
            "mkdir",
            "mount",
            "mountpoint",
            "systemctl",
            "systemd-escape",
            "umount",
        ]
    )
    if not machine_id_valid():
        fail("/etc/machine-id is missing or invalid. Read-only mode requires a stable machine-id.")
    detected_type = run(["blkid", "-s", "TYPE", "-o", "value", device], check=False, capture=True).stdout.strip()
    if not detected_type:
        fail(f"No filesystem detected on {device}. Create an ext4 filesystem first, then rerun this command.")
    if detected_type != "ext4":
        fail(f"Expected ext4 on {device}, got {detected_type}")
    _ensure_readonly_stack_installed()

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
            fail("bluetooth.service did not come back up after enabling the persistent Bluetooth state bind mount")
    finally:
        if bluetooth_was_active and not _systemctl_active("bluetooth.service"):
            run(["systemctl", "start", "bluetooth.service"], check=False)
        elif not bluetooth_was_active and _systemctl_active("bluetooth.service"):
            run(["systemctl", "stop", "bluetooth.service"], check=False)
        restart_b2u_if_installed(b2u_was_active, "after enabling the persistent Bluetooth state bind mount")
    ok(f"Persistent Bluetooth state storage is active at {persist_bluetooth_dir}")


def _ensure_readonly_stack_installed() -> None:
    info("Installing read-only mode prerequisites")
    run(["apt-get", "update", "-y"])

    initramfs_install = run(
        ["apt-get", "install", "-y", "--no-install-recommends", "initramfs-tools"], check=False, capture=True
    )
    if initramfs_install.returncode != 0:
        warn("Initial initramfs-tools install did not complete cleanly; attempting package configuration repair.")
        _print_completed_output(initramfs_install)
    _ensure_initramfs_modules_most()
    if initramfs_install.returncode != 0:
        _configure_pending_packages()

    install = run(
        ["apt-get", "install", "-y", "--no-install-recommends", *READONLY_PACKAGES], check=False, capture=True
    )
    if install.returncode != 0:
        warn(
            "Read-only prerequisite package install did not complete cleanly; attempting package configuration repair."
        )
        _print_completed_output(install)
    _configure_pending_packages()

    if not readonly_stack_packages_healthy():
        warn("OverlayFS package state is incomplete:")
        print(readonly_stack_package_report())
        fail(
            "Read-only prerequisite package setup did not complete cleanly. Rerun readonly setup after fixing apt/dpkg."
        )


def _configure_pending_packages() -> None:
    completed = run(["dpkg", "--configure", "-a"], check=False, capture=True)
    if completed.returncode != 0:
        _print_completed_output(completed)
        fail("dpkg could not finish configuring read-only prerequisite packages.")


def _print_completed_output(completed: subprocess.CompletedProcess[str]) -> None:
    output_text = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip())
    if output_text:
        print(output_text)


def _ensure_initramfs_modules_most(path: Path = INITRAMFS_CONF) -> None:
    if path.is_file():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    else:
        lines = []

    changed = False
    found = False
    updated_lines = []
    for line in lines:
        if re.fullmatch(r"\s*MODULES\s*=.*", line) and not line.lstrip().startswith("#"):
            found = True
            if line != "MODULES=most":
                changed = True
            updated_lines.append("MODULES=most")
        else:
            updated_lines.append(line)

    if not found:
        updated_lines.append("MODULES=most")
        changed = True

    if not changed:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path)
    path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


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
            "Persistent Bluetooth state storage is not active. "
            + "Run bluetooth_2_usb readonly setup --device /dev/... first."
        )
    if not readonly_stack_packages_healthy():
        warn("OverlayFS package state is incomplete:")
        print(readonly_stack_package_report())
        fail(
            "Read-only prerequisite packages are not fully installed. "
            + "Rerun bluetooth_2_usb readonly setup --device /dev/... before enabling read-only mode."
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
            run(["raspi-config", "nonint", "enable_overlayfs"])

        if not readonly_stack_packages_healthy():
            warn("OverlayFS package state is incomplete:")
            print(readonly_stack_package_report())
            fail(
                "Read-only prerequisite packages are not fully installed. "
                + "Rerun bluetooth_2_usb readonly setup --device /dev/... before enabling read-only mode."
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
    except Exception:
        warn(
            "OverlayFS was requested but validation did not complete. "
            + "Run `bluetooth_2_usb readonly status` and inspect the reported package or boot state before rebooting. "
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
    run(["raspi-config", "nonint", "disable_overlayfs"])
    ok("OverlayFS has been disabled")
    warn("Persistent Bluetooth state mount configuration was kept.")
    warn("Reboot to return to a writable root filesystem.")
    warn(
        "After reboot, run `sudo bluetooth_2_usb readonly migrate` if you want to move Bluetooth state back to rootfs."
    )


def migrate_bluetooth_state_to_rootfs() -> None:
    require_commands(["findmnt", "mountpoint", "systemctl", "systemd-escape", "umount"])
    config = load_readonly_config()
    root_fstype = current_root_filesystem_type()
    if root_fstype == "overlay":
        fail(
            "Refusing to migrate Bluetooth state while the root filesystem is overlay-backed. "
            + "Reboot after disabling read-only mode first."
        )
    if not bluetooth_state_persistent(config):
        fail("Persistent Bluetooth state is not mounted at /var/lib/bluetooth; nothing to migrate.")
    if not config.persist_bluetooth_dir.is_dir():
        fail(f"Persistent Bluetooth state directory is missing: {config.persist_bluetooth_dir}")

    bluetooth_was_active = _systemctl_active("bluetooth.service")
    b2u_was_active = stop_b2u_if_installed("before migrating Bluetooth state back to rootfs")
    target = Path("/var/lib/bluetooth")
    temp_dir = target.with_name(f"{target.name}.b2u-migrate-{uuid.uuid4().hex}")
    backup_dir = target.with_name(f"{target.name}.b2u-backup-{uuid.uuid4().hex}")
    cleanup_error: OpsError | None = None
    try:
        if bluetooth_was_active:
            run(["systemctl", "stop", "bluetooth.service"])
        shutil.copytree(config.persist_bluetooth_dir, temp_dir, symlinks=True)
        run(["systemctl", "disable", "--now", "var-lib-bluetooth.mount"], check=False)
        if run(["mountpoint", "-q", target], check=False).returncode == 0:
            run(["umount", target])
        if target.exists():
            target.rename(backup_dir)
        try:
            temp_dir.rename(target)
        except Exception:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if backup_dir.exists():
                backup_dir.rename(target)
            raise
        else:
            shutil.rmtree(backup_dir, ignore_errors=True)
        remove_bluetooth_persist_dropin()
        remove_bluetooth_bind_mount_unit()
        try:
            _disable_persistent_storage_mount(config)
        except OpsError as exc:
            cleanup_error = exc
        finally:
            run(["systemctl", "daemon-reload"], check=False)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if bluetooth_was_active and not _systemctl_active("bluetooth.service"):
            run(["systemctl", "start", "bluetooth.service"], check=False)
        restart_b2u_if_installed(b2u_was_active, "after migrating Bluetooth state back to rootfs")
    ok("Bluetooth state has been migrated back to /var/lib/bluetooth on the root filesystem.")
    if cleanup_error is None:
        ok("Persistent storage mount has been disabled and unmounted.")
    else:
        warn(f"Persistent storage mount cleanup failed: {cleanup_error}")
        warn(f"Manual cleanup may be required for {config.persist_mount}.")
    warn("Data on the persistent device was left intact.")


def _disable_persistent_storage_mount(config: ReadonlyConfig) -> None:
    unit = output(["systemd-escape", "--path", "--suffix=mount", config.persist_mount])
    run(["systemctl", "disable", "--now", unit], check=False)
    if run(["findmnt", "-rn", config.persist_mount], check=False, capture=True).returncode == 0:
        try:
            run(["umount", config.persist_mount])
        except OpsError:
            fail(f"Persistent storage mount is no longer needed but could not be unmounted: {config.persist_mount}")
    remove_persist_mount_unit(config.persist_mount)
