import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import bluetooth_2_usb.ops.readonly.workflows as readonly_workflows
from bluetooth_2_usb.ops import boot_config
from bluetooth_2_usb.ops.bluetooth import clear_bluetooth_rfkill_soft_blocks, rfkill_list_bluetooth
from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.paths import ManagedPaths
from bluetooth_2_usb.ops.readonly import (
    ReadonlyConfig,
    bluetooth_state_persistent,
    disable_readonly,
    enable_readonly,
    load_readonly_config,
    migrate_bluetooth_state_to_rootfs,
    overlay_configured_status,
    overlay_status,
    package_status,
    print_readonly_status,
    restart_b2u_if_installed,
    setup_persistent_bluetooth_state,
    stop_b2u_if_installed,
    write_bluetooth_bind_mount_unit,
    write_readonly_config,
)

READONLY = "bluetooth_2_usb.ops.readonly"
READONLY_CONFIG = "bluetooth_2_usb.ops.readonly.config"
READONLY_SERVICE = "bluetooth_2_usb.ops.readonly.service"
READONLY_STATUS = "bluetooth_2_usb.ops.readonly.status"
READONLY_UNITS = "bluetooth_2_usb.ops.readonly.units"
READONLY_WORKFLOWS = "bluetooth_2_usb.ops.readonly.workflows"
OPS_BLUETOOTH = "bluetooth_2_usb.ops.bluetooth"
OPS_BOOT_CONFIG = "bluetooth_2_usb.ops.boot_config"
OPS_DEPLOYMENT = "bluetooth_2_usb.ops.deployment"
PATHLIB_PATH = "pathlib.Path"


def _write_rfkill_entry(
    root: Path, index: int, *, type_name: str = "bluetooth", soft: str = "0", hard: str = "0", state: str = "1"
) -> Path:
    rfkill_dir = root / f"rfkill{index}"
    rfkill_dir.mkdir(parents=True, exist_ok=True)
    (rfkill_dir / "type").write_text(f"{type_name}\n", encoding="utf-8")
    (rfkill_dir / "soft").write_text(f"{soft}\n", encoding="utf-8")
    (rfkill_dir / "hard").write_text(f"{hard}\n", encoding="utf-8")
    (rfkill_dir / "state").write_text(f"{state}\n", encoding="utf-8")
    return rfkill_dir


class BluetoothRfkillOpsTest(unittest.TestCase):
    def test_clear_bluetooth_rfkill_soft_blocks_clears_soft_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rfkill_root = Path(tmpdir)
            entry = _write_rfkill_entry(rfkill_root, 0, soft="1", hard="0", state="0")

            clear_bluetooth_rfkill_soft_blocks(rfkill_root)

            self.assertEqual((entry / "soft").read_text(encoding="utf-8").strip(), "0")

    def test_clear_bluetooth_rfkill_soft_blocks_keeps_hard_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rfkill_root = Path(tmpdir)
            entry = _write_rfkill_entry(rfkill_root, 0, soft="1", hard="1", state="0")

            clear_bluetooth_rfkill_soft_blocks(rfkill_root)

            self.assertEqual((entry / "soft").read_text(encoding="utf-8").strip(), "1")
            self.assertEqual((entry / "hard").read_text(encoding="utf-8").strip(), "1")

    def test_clear_bluetooth_rfkill_soft_blocks_with_no_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            clear_bluetooth_rfkill_soft_blocks(Path(tmpdir))

    def test_rfkill_list_bluetooth_handles_missing_rfkill_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rfkill_root = Path(tmpdir)
            _write_rfkill_entry(rfkill_root, 0, soft="1", hard="0", state="0")

            with (
                patch(f"{OPS_BLUETOOTH}.rfkill_root", return_value=rfkill_root),
                patch(f"{OPS_BLUETOOTH}.run", side_effect=OpsError("missing rfkill")),
            ):
                output = rfkill_list_bluetooth()

        self.assertIn("missing rfkill", output)
        self.assertIn("rfkill0 type=bluetooth soft=1 hard=0 state=0", output)


class BootConfigOpsTest(unittest.TestCase):
    def test_required_boot_modules_rejects_unknown_dwc2_mode(self) -> None:
        with self.assertRaises(OpsError):
            boot_config.required_boot_modules_csv("unknown")

    def test_boot_config_assignment_uses_matching_model_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "config.txt"
            config.write_text(
                "\n".join(["arm_64bit=0", "[pi4]", "arm_64bit=1", "[pi5]", "arm_64bit=0"]) + "\n", encoding="utf-8"
            )

            value = boot_config.boot_config_assignment_value("arm_64bit", config_file=config, model_filters=["pi4"])

        self.assertEqual(value, "1")

    def test_configured_initramfs_uses_matching_model_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "config.txt"
            config.write_text(
                "\n".join(
                    [
                        "initramfs initramfs-default followkernel",
                        "[cm4]",
                        "initramfs initramfs-cm4 followkernel",
                        "[pi5]",
                        "initramfs initramfs-pi5 followkernel",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch(f"{OPS_BOOT_CONFIG}.boot_config_model_filters", return_value=["cm4"]):
                self.assertEqual(boot_config.configured_initramfs_file(config), "initramfs-cm4")

    def test_normalize_dwc2_overlay_replaces_stale_lines_under_all_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "config.txt"
            config.write_text(
                "dtoverlay=dwc2\n" "dtoverlay=vc4-kms-v3d\n" "[all]\n" "dtoverlay=dwc2,dr_mode=host\n" "arm_64bit=1\n",
                encoding="utf-8",
            )

            boot_config.normalize_dwc2_overlay(config, "dtoverlay=dwc2,dr_mode=peripheral")

            self.assertEqual(
                config.read_text(encoding="utf-8"),
                "dtoverlay=vc4-kms-v3d\n[all]\ndtoverlay=dwc2,dr_mode=peripheral\narm_64bit=1\n",
            )

    def test_normalize_modules_load_replaces_stale_otg_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cmdline = Path(tmpdir) / "cmdline.txt"
            cmdline.write_text("root=/dev/mmcblk0p2 modules-load=dwc_otg,dwc2,libcomposite,foo quiet\n")

            boot_config.normalize_modules_load(cmdline, "libcomposite")

            self.assertEqual(
                cmdline.read_text(encoding="utf-8"), "root=/dev/mmcblk0p2 quiet modules-load=foo,libcomposite\n"
            )

    def test_normalize_modules_load_adds_missing_token_and_preserves_unrelated_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cmdline = Path(tmpdir) / "cmdline.txt"
            cmdline.write_text("root=/dev/mmcblk0p2 modules-load=i2c-dev quiet\n")

            boot_config.normalize_modules_load(cmdline, "dwc2,libcomposite")

            self.assertEqual(
                cmdline.read_text(encoding="utf-8"),
                "root=/dev/mmcblk0p2 quiet modules-load=i2c-dev,dwc2,libcomposite\n",
            )

    def test_boot_initramfs_target_rejects_unsafe_paths(self) -> None:
        for target in ("/boot/initramfs8", "../initramfs8", "nested/initramfs8"):
            with self.subTest(target=target), self.assertRaises(OpsError):
                boot_config.boot_initramfs_target_path(target)

    def test_kernel_config_candidates_include_detected_firmware_boot_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            firmware = Path(tmpdir) / "firmware"

            with patch(f"{OPS_BOOT_CONFIG}.detect_boot_dir", return_value=firmware):
                candidates = boot_config.kernel_config_candidates("6.12.81-b2u-wake")

        self.assertEqual(
            candidates,
            [Path("/boot/config-6.12.81-b2u-wake"), firmware / "config-6.12.81-b2u-wake", Path("/proc/config.gz")],
        )

    def test_kernel_config_snippet_reads_detected_firmware_boot_dir_config(self) -> None:
        release = "99.99.99-b2u-test"
        with tempfile.TemporaryDirectory() as tmpdir:
            firmware = Path(tmpdir) / "firmware"
            firmware.mkdir()
            (firmware / f"config-{release}").write_text(
                "\n".join(["CONFIG_USB_DWC2=y", "CONFIG_USB_LIBCOMPOSITE=m", "CONFIG_UNRELATED=y"]) + "\n",
                encoding="utf-8",
            )

            with (
                patch(f"{OPS_BOOT_CONFIG}.detect_boot_dir", return_value=firmware),
                patch(f"{OPS_BOOT_CONFIG}.current_kernel_release", return_value=release),
            ):
                snippet = boot_config.kernel_config_snippet()

        self.assertEqual(snippet, "CONFIG_USB_DWC2=y\nCONFIG_USB_LIBCOMPOSITE=m")


class ReadonlyConfigTest(unittest.TestCase):
    def test_overlay_status_prefers_live_state(self) -> None:
        calls = []

        def fake_run(command, *, check=False, capture=True):
            calls.append(command)

            class Completed:
                returncode = 0
                stdout = "0\n"

            return Completed()

        with (
            patch(f"{READONLY_STATUS}.shutil.which", return_value="/usr/bin/raspi-config"),
            patch(f"{READONLY_STATUS}.run", side_effect=fake_run),
        ):
            self.assertEqual(overlay_status(), "enabled")

        self.assertEqual(calls[0], ["raspi-config", "nonint", "get_overlay_now"])

    def test_overlay_status_returns_unknown_when_raspi_config_probe_fails(self) -> None:
        with (
            patch(f"{READONLY_STATUS}.shutil.which", return_value="/usr/bin/raspi-config"),
            patch(f"{READONLY_STATUS}.run", side_effect=OpsError("raspi-config failed")),
        ):
            self.assertEqual(overlay_status(), "unknown")

    def test_overlay_configured_status_returns_unknown_when_probe_fails(self) -> None:
        with (
            patch(f"{READONLY_STATUS}.shutil.which", return_value="/usr/bin/raspi-config"),
            patch(f"{READONLY_STATUS}.run", side_effect=OSError("raspi-config unavailable")),
        ):
            self.assertEqual(overlay_configured_status(), "unknown")

    def test_package_status_returns_empty_when_dpkg_probe_fails(self) -> None:
        with patch(f"{READONLY_STATUS}.run", side_effect=OpsError("dpkg unavailable")):
            self.assertEqual(package_status("overlayroot"), "")

    def test_initramfs_modules_most_replaces_dep_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "initramfs.conf"
            path.write_text("# keep\nMODULES=dep\nBUSYBOX=auto\n", encoding="utf-8")

            with patch(f"{READONLY_WORKFLOWS}.backup_file") as backup:
                readonly_workflows._ensure_initramfs_modules_most(path)

            self.assertEqual(path.read_text(encoding="utf-8"), "# keep\nMODULES=most\nBUSYBOX=auto\n")
            backup.assert_called_once_with(path)

    def test_initramfs_modules_most_appends_missing_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "initramfs.conf"
            path.write_text("# MODULES=dep\nBUSYBOX=auto\n", encoding="utf-8")

            with patch(f"{READONLY_WORKFLOWS}.backup_file") as backup:
                readonly_workflows._ensure_initramfs_modules_most(path)

            self.assertEqual(path.read_text(encoding="utf-8"), "# MODULES=dep\nBUSYBOX=auto\nMODULES=most\n")
            backup.assert_called_once_with(path)

    def test_initramfs_modules_most_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "initramfs.conf"
            path.write_text("MODULES=most\n", encoding="utf-8")

            with patch(f"{READONLY_WORKFLOWS}.backup_file") as backup:
                readonly_workflows._ensure_initramfs_modules_most(path)

            self.assertEqual(path.read_text(encoding="utf-8"), "MODULES=most\n")
            backup.assert_not_called()

    def test_readonly_config_round_trips_supported_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "readonly.env"
            config = ReadonlyConfig(
                persist_mount=Path("/mnt/persist"),
                persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
                persist_spec="/dev/disk/by-uuid/abc",
                persist_device="/dev/sda1",
            )

            write_readonly_config(config, path)

            self.assertEqual(load_readonly_config(path), config)

    def test_readonly_config_ignores_legacy_mode_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "readonly.env"
            path.write_text(
                "\n".join(
                    [
                        'B2U_READONLY_MODE="persistent"',
                        'B2U_PERSIST_MOUNT="/mnt/persist"',
                        'B2U_PERSIST_BLUETOOTH_DIR="/mnt/persist/bluetooth"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_readonly_config(path)

        self.assertEqual(config.persist_mount, Path("/mnt/persist"))
        self.assertEqual(config.persist_bluetooth_dir, Path("/mnt/persist/bluetooth"))

    def test_write_readonly_config_omits_legacy_mode_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "readonly.env"

            write_readonly_config(ReadonlyConfig(), path)

            self.assertNotIn("B2U_READONLY_MODE", path.read_text(encoding="utf-8"))

    def test_readonly_config_rejects_unexpected_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "readonly.env"
            path.write_text('UNEXPECTED="value"\n', encoding="utf-8")

            with self.assertRaises(OpsError):
                load_readonly_config(path)

    def test_readonly_config_rejects_empty_or_relative_persist_paths(self) -> None:
        cases = [
            'B2U_PERSIST_MOUNT=""\nB2U_PERSIST_BLUETOOTH_DIR="/persist/bluetooth"\n',
            'B2U_PERSIST_MOUNT="persist"\nB2U_PERSIST_BLUETOOTH_DIR="/persist/bluetooth"\n',
            'B2U_PERSIST_MOUNT="/persist"\nB2U_PERSIST_BLUETOOTH_DIR="bluetooth"\n',
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "readonly.env"
            for content in cases:
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")

                    with self.assertRaises(OpsError):
                        load_readonly_config(path)

    def test_readonly_config_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = ManagedPaths(persist_mount=Path("/tmp/persist"), persist_bluetooth_subdir="bt-state")
            with patch(f"{READONLY_CONFIG}.PATHS", paths):
                config = load_readonly_config(Path(tmpdir) / "missing")

        self.assertEqual(config.persist_bluetooth_dir, Path("/tmp/persist/bt-state"))

    def test_bluetooth_state_persistent_rejects_bluetooth_dir_outside_persist_mount(self) -> None:
        config = ReadonlyConfig(
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/var/lib/bluetooth"),
            persist_spec="/dev/sda1",
            persist_device="/dev/sda1",
        )

        def fake_run(command, *, check=False, capture=False):
            class Completed:
                returncode = 0
                stdout = "/dev/sda1\n"

            return Completed()

        with patch(f"{READONLY_STATUS}.run", side_effect=fake_run), patch(f"{PATHLIB_PATH}.is_dir", return_value=True):
            self.assertFalse(bluetooth_state_persistent(config))

    def test_bluetooth_state_persistent_returns_false_when_findmnt_fails(self) -> None:
        config = ReadonlyConfig(
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
            persist_spec="/dev/sda1",
            persist_device="/dev/sda1",
        )

        with patch(f"{READONLY_STATUS}.run", side_effect=OpsError("findmnt unavailable")):
            self.assertFalse(bluetooth_state_persistent(config))

    def test_bluetooth_state_persistent_returns_false_when_config_cannot_load(self) -> None:
        with patch(f"{READONLY_STATUS}.load_readonly_config", side_effect=OpsError("invalid readonly env")):
            self.assertFalse(bluetooth_state_persistent())

    def test_print_readonly_status_reports_configured_and_live_state(self) -> None:
        config = ReadonlyConfig(
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
            persist_spec="/dev/disk/by-uuid/abc",
            persist_device="/dev/sda1",
        )

        def fake_findmnt(target: str | Path, field: str) -> str:
            values = {("/", "SOURCE"): "overlayroot", ("/var/lib/bluetooth", "SOURCE"): "/dev/sda1[/bluetooth]"}
            return values.get((str(target), field), "")

        stdout = StringIO()
        with (
            patch(f"{READONLY_STATUS}.load_readonly_config", return_value=config),
            patch(f"{READONLY_STATUS}.readonly_mode", return_value="enabled"),
            patch(f"{READONLY_STATUS}.overlay_status", return_value="enabled"),
            patch(f"{READONLY_STATUS}.overlay_configured_status", return_value="enabled"),
            patch(f"{READONLY_STATUS}._root_filesystem_type", return_value="overlay"),
            patch(f"{READONLY_STATUS}.bluetooth_state_persistent", return_value=True),
            patch(f"{READONLY_STATUS}.bluetooth_state_storage", return_value="persistent"),
            patch(f"{READONLY_STATUS}._findmnt_value", side_effect=fake_findmnt),
            patch(f"{READONLY_STATUS}._mountpoint", return_value=True),
            redirect_stdout(stdout),
        ):
            print_readonly_status()

        output = stdout.getvalue()
        self.assertIn("read-only mode: enabled\n", output)
        self.assertIn("overlay_live: enabled\n", output)
        self.assertIn("bluetooth state storage: persistent\n", output)
        self.assertIn("persist_device: /dev/sda1\n", output)
        self.assertNotIn("configured read-only mode:", output)

    def test_print_readonly_status_uses_safe_defaults_when_config_cannot_load(self) -> None:
        stdout = StringIO()
        with (
            patch(f"{READONLY_STATUS}.load_readonly_config", side_effect=OpsError("invalid readonly env")),
            patch(f"{READONLY_STATUS}.readonly_mode", return_value="disabled"),
            patch(f"{READONLY_STATUS}.overlay_status", return_value="unknown"),
            patch(f"{READONLY_STATUS}.overlay_configured_status", return_value="unknown"),
            patch(f"{READONLY_STATUS}._root_filesystem_type", return_value="unknown"),
            patch(f"{READONLY_STATUS}.bluetooth_state_persistent", return_value=False),
            patch(f"{READONLY_STATUS}._findmnt_value", return_value=""),
            patch(f"{READONLY_STATUS}._mountpoint", return_value=False),
            redirect_stdout(stdout),
        ):
            print_readonly_status()

        output = stdout.getvalue()
        self.assertIn("bluetooth state storage:", output)
        self.assertIn("persist_device: <unset>\n", output)
        self.assertNotIn("configured read-only mode:", output)

    def test_b2u_service_helpers_preserve_inactive_service_state(self) -> None:
        calls = []

        def fake_run(command, *, check=True, capture=False):
            calls.append(command)

            class Completed:
                returncode = 1 if command[:3] == ["systemctl", "is-active", "--quiet"] else 0
                stdout = ""

            return Completed()

        with (
            patch(f"{OPS_DEPLOYMENT}.service_installed", return_value=True),
            patch(f"{READONLY_SERVICE}.run", side_effect=fake_run),
        ):
            was_active = stop_b2u_if_installed("during test")
            restart_b2u_if_installed(was_active, "during test")

        self.assertFalse(was_active)
        self.assertNotIn(["systemctl", "stop", "bluetooth_2_usb.service"], calls)
        self.assertNotIn(["systemctl", "restart", "bluetooth_2_usb.service"], calls)

    def test_bluetooth_bind_mount_unit_depends_on_persist_mount_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unit_path = root / "var-lib-bluetooth.mount"
            paths = ManagedPaths(bluetooth_bind_mount_unit=unit_path)

            def local_path(value: str) -> Path:
                if value == "/var/lib/bluetooth":
                    return root / "var/lib/bluetooth"
                return Path(value)

            with (
                patch(f"{READONLY_UNITS}.PATHS", paths),
                patch(f"{READONLY_UNITS}.Path", side_effect=local_path),
                patch(f"{READONLY_UNITS}.output", return_value="mnt-persist.mount"),
            ):
                write_bluetooth_bind_mount_unit(Path("/mnt/persist/custom/bluetooth"), Path("/mnt/persist"))

            content = unit_path.read_text(encoding="utf-8")

        self.assertIn("After=mnt-persist.mount\n", content)
        self.assertIn("Requires=mnt-persist.mount\n", content)
        self.assertIn("What=/mnt/persist/custom/bluetooth\n", content)

    def test_setup_persistent_bluetooth_state_writes_config_and_mounts_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = ReadonlyConfig(
                persist_mount=root / "persist",
                persist_bluetooth_dir=root / "persist" / "bluetooth",
                persist_spec="",
                persist_device="",
            )
            commands = []
            events = []
            written = []
            var_lib_bluetooth = root / "var/lib/bluetooth"

            def fake_run(command, *, check=True, capture=False):
                commands.append(command)

                class Completed:
                    returncode = 0
                    stdout = ""

                if command[:4] == ["blkid", "-s", "TYPE", "-o"]:
                    Completed.stdout = "ext4\n"
                elif command[:2] == ["mountpoint", "-q"]:
                    Completed.returncode = 1
                return Completed()

            def local_path(value: str) -> Path:
                if value == "/var/lib/bluetooth":
                    return var_lib_bluetooth
                return Path(value)

            with ExitStack() as stack:
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.require_commands"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.machine_id_valid", return_value=True))
                ensure_stack = stack.enter_context(
                    patch(
                        f"{READONLY_WORKFLOWS}._ensure_readonly_stack_installed",
                        side_effect=lambda: events.append("packages"),
                    )
                )
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config))
                stack.enter_context(
                    patch(f"{READONLY_WORKFLOWS}.persist_spec_from_device", return_value="/dev/disk/by-uuid/abc")
                )
                stack.enter_context(
                    patch(
                        f"{READONLY_WORKFLOWS}.write_persist_mount_unit",
                        side_effect=lambda *_args: events.append("mount_unit") or "mnt-persist.mount",
                    )
                )
                write_bind = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.write_bluetooth_bind_mount_unit"))
                install_dropin = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.install_bluetooth_persist_dropin"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.write_readonly_config", side_effect=written.append))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}._systemctl_active", side_effect=[True, True, True]))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.stop_b2u_if_installed", return_value=False))
                restart_b2u = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.restart_b2u_if_installed"))
                seed_state = stack.enter_context(patch(f"{READONLY_WORKFLOWS}._seed_bluetooth_state"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.Path", side_effect=local_path))

                setup_persistent_bluetooth_state("/dev/sda1")

            self.assertTrue(var_lib_bluetooth.is_dir())
            ensure_stack.assert_called_once_with()
            self.assertEqual(events[:2], ["packages", "mount_unit"])
            self.assertEqual(written[0].persist_spec, "/dev/disk/by-uuid/abc")
            self.assertEqual(written[0].persist_device, "/dev/sda1")
            write_bind.assert_called_once_with(root / "persist" / "bluetooth", root / "persist")
            install_dropin.assert_called_once_with()
            seed_state.assert_called_once_with(root / "persist" / "bluetooth")
            restart_b2u.assert_called_once_with(False, "after enabling the persistent Bluetooth state bind mount")
            self.assertIn(["systemctl", "stop", "bluetooth.service"], commands)
            self.assertIn(["systemctl", "enable", "--now", "mnt-persist.mount"], commands)
            self.assertIn(["systemctl", "enable", "--now", "var-lib-bluetooth.mount"], commands)
            self.assertIn(["systemctl", "start", "bluetooth.service"], commands)

    def test_setup_persistent_bluetooth_state_fails_before_mount_migration_when_packages_fail(self) -> None:
        config = ReadonlyConfig(
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
            persist_spec="",
            persist_device="",
        )

        def fake_run(command, *, check=True, capture=False):
            class Completed:
                returncode = 0
                stdout = "ext4\n" if command[:4] == ["blkid", "-s", "TYPE", "-o"] else ""

            return Completed()

        with ExitStack() as stack:
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.require_commands"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.machine_id_valid", return_value=True))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run))
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}._ensure_readonly_stack_installed", side_effect=OpsError("apt failed"))
            )
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config))
            write_mount = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.write_persist_mount_unit"))
            stop_b2u = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.stop_b2u_if_installed"))

            with self.assertRaisesRegex(OpsError, "apt failed"):
                setup_persistent_bluetooth_state("/dev/sda1")

        write_mount.assert_not_called()
        stop_b2u.assert_not_called()

    def test_ensure_readonly_stack_installs_packages_and_configures_dpkg(self) -> None:
        commands = []

        def fake_run(command, *, check=True, capture=False):
            commands.append(command)

            class Completed:
                returncode = 0
                stdout = ""
                stderr = ""

            return Completed()

        with (
            patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run),
            patch(f"{READONLY_WORKFLOWS}._ensure_initramfs_modules_most") as ensure_modules,
            patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_healthy", return_value=True),
        ):
            readonly_workflows._ensure_readonly_stack_installed()

        self.assertEqual(commands[0], ["apt-get", "update", "-y"])
        self.assertEqual(commands[1], ["apt-get", "install", "-y", "--no-install-recommends", "initramfs-tools"])
        ensure_modules.assert_called_once_with()
        self.assertIn(["dpkg", "--configure", "-a"], commands)
        self.assertIn(
            [
                "apt-get",
                "install",
                "-y",
                "--no-install-recommends",
                "overlayroot",
                "cryptsetup",
                "cryptsetup-bin",
                "initramfs-tools",
            ],
            commands,
        )

    def test_ensure_readonly_stack_fails_with_package_report_when_packages_remain_incomplete(self) -> None:
        def fake_run(_command, *, check=True, capture=False):
            class Completed:
                returncode = 0
                stdout = ""
                stderr = ""

            return Completed()

        with (
            patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run),
            patch(f"{READONLY_WORKFLOWS}._ensure_initramfs_modules_most"),
            patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_healthy", return_value=False),
            patch(f"{READONLY_WORKFLOWS}.readonly_stack_package_report", return_value="overlayroot: half-configured"),
            redirect_stdout(StringIO()) as stdout,
            self.assertRaisesRegex(OpsError, "Read-only prerequisite package setup did not complete cleanly"),
        ):
            readonly_workflows._ensure_readonly_stack_installed()

        self.assertIn("overlayroot: half-configured", stdout.getvalue())

    def test_enable_readonly_does_not_rollback_overlayfs_when_validation_fails(self) -> None:
        config = ReadonlyConfig(
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
            persist_spec="/dev/sda1",
            persist_device="/dev/sda1",
        )
        commands = []

        def fake_run(command, *, check=True, capture=False):
            commands.append(command)

            class Completed:
                returncode = 0
                stdout = ""

            return Completed()

        with ExitStack() as stack:
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.require_commands"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.machine_id_valid", return_value=True))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.bluetooth_state_persistent", return_value=True))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_healthy", return_value=True))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.overlay_status", return_value="disabled"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.current_kernel_release", return_value="6.6.1"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.configured_kernel_image", return_value="kernel8.img"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.configured_initramfs_file", return_value=""))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.expected_boot_initramfs_file", return_value="initramfs8"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.versioned_initrd_candidates", return_value=[]))
            stack.enter_context(
                patch(
                    f"{READONLY_WORKFLOWS}.ensure_bootable_initramfs_for_current_kernel",
                    side_effect=OpsError("initramfs failed"),
                )
            )
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run))

            with self.assertRaises(OpsError), redirect_stdout(StringIO()) as stdout:
                enable_readonly()

        self.assertIn(["raspi-config", "nonint", "enable_overlayfs"], commands)
        self.assertNotIn(["raspi-config", "nonint", "disable_overlayfs"], commands)
        self.assertIn("readonly status", stdout.getvalue())
        self.assertNotIn("overlayfs-repair-guidance", stdout.getvalue())
        self.assertNotIn("for repair steps", stdout.getvalue())

    def test_enable_readonly_reports_status_guidance_when_overlayfs_enable_fails(self) -> None:
        config = ReadonlyConfig(
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
            persist_spec="/dev/sda1",
            persist_device="/dev/sda1",
        )

        with ExitStack() as stack:
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.require_commands"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.machine_id_valid", return_value=True))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.bluetooth_state_persistent", return_value=True))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_healthy", return_value=True))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.overlay_status", return_value="disabled"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.current_kernel_release", return_value="6.6.1"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.configured_kernel_image", return_value="kernel8.img"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.configured_initramfs_file", return_value=""))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.expected_boot_initramfs_file", return_value="initramfs8"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.versioned_initrd_candidates", return_value=[]))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=OpsError("raspi-config failed")))
            write_config = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.write_readonly_config"))

            with self.assertRaises(OpsError), redirect_stdout(StringIO()) as stdout:
                enable_readonly()

        write_config.assert_not_called()
        self.assertIn("readonly status", stdout.getvalue())
        self.assertNotIn("overlayfs-repair-guidance", stdout.getvalue())
        self.assertIn("disable OverlayFS", stdout.getvalue())

    def test_enable_readonly_tells_user_to_rerun_setup_when_packages_are_incomplete(self) -> None:
        config = ReadonlyConfig(
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
            persist_spec="/dev/sda1",
            persist_device="/dev/sda1",
        )

        with ExitStack() as stack:
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.require_commands"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.machine_id_valid", return_value=True))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.bluetooth_state_persistent", return_value=True))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_healthy", return_value=False))
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.readonly_stack_package_report", return_value="bad package")
            )
            run_command = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run"))

            with (
                redirect_stdout(StringIO()) as stdout,
                self.assertRaisesRegex(OpsError, "Rerun bluetooth_2_usb readonly setup"),
            ):
                enable_readonly()

        run_command.assert_not_called()
        self.assertIn("bad package", stdout.getvalue())

    def test_disable_readonly_disables_overlayfs_and_keeps_persistent_mount_config(self) -> None:
        commands = []

        def fake_run(command, *, check=True, capture=False):
            commands.append(command)

            class Completed:
                returncode = 0
                stdout = ""

            return Completed()

        with ExitStack() as stack:
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.require_commands"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run))

            with redirect_stdout(StringIO()) as stdout:
                disable_readonly()

        self.assertEqual(commands, [["raspi-config", "nonint", "disable_overlayfs"]])
        self.assertIn("Persistent Bluetooth state mount configuration was kept.", stdout.getvalue())
        self.assertIn("readonly migrate", stdout.getvalue())

    def test_migrate_bluetooth_state_refuses_overlay_root(self) -> None:
        with (
            patch(f"{READONLY_WORKFLOWS}.require_commands"),
            patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=ReadonlyConfig()),
            patch(f"{READONLY_WORKFLOWS}.current_root_filesystem_type", return_value="overlay"),
            self.assertRaisesRegex(OpsError, "overlay-backed"),
        ):
            migrate_bluetooth_state_to_rootfs()

    def test_migrate_bluetooth_state_refuses_when_persistent_state_is_not_mounted(self) -> None:
        config = ReadonlyConfig(
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
            persist_spec="/dev/disk/by-uuid/abc",
            persist_device="/dev/sda1",
        )
        with (
            patch(f"{READONLY_WORKFLOWS}.require_commands"),
            patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config),
            patch(f"{READONLY_WORKFLOWS}.current_root_filesystem_type", return_value="ext4"),
            patch(f"{READONLY_WORKFLOWS}.bluetooth_state_persistent", return_value=False),
            self.assertRaisesRegex(OpsError, "not mounted"),
        ):
            migrate_bluetooth_state_to_rootfs()

    def test_migrate_bluetooth_state_copies_state_and_removes_bind_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            persist_bluetooth = root / "persist/bluetooth"
            persist_bluetooth.mkdir(parents=True)
            (persist_bluetooth / "controller").mkdir()
            (persist_bluetooth / "controller/settings").write_text("paired\n", encoding="utf-8")
            root_bluetooth = root / "var/lib/bluetooth"
            root_bluetooth.mkdir(parents=True)
            (root_bluetooth / "old").write_text("old\n", encoding="utf-8")
            config = ReadonlyConfig(
                persist_mount=root / "persist",
                persist_bluetooth_dir=persist_bluetooth,
                persist_spec="/dev/disk/by-uuid/abc",
                persist_device="/dev/sda1",
            )
            commands = []

            def fake_run(command, *, check=True, capture=False):
                commands.append(command)

                class Completed:
                    returncode = 0
                    stdout = ""

                if command[:2] == ["mountpoint", "-q"]:
                    Completed.returncode = 1
                return Completed()

            def local_path(value: str) -> Path:
                if value == "/var/lib/bluetooth":
                    return root_bluetooth
                return Path(value)

            with ExitStack() as stack:
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.require_commands"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.current_root_filesystem_type", return_value="ext4"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.bluetooth_state_persistent", return_value=True))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}._systemctl_active", side_effect=[True, False]))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.stop_b2u_if_installed", return_value=True))
                restart_b2u = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.restart_b2u_if_installed"))
                remove_dropin = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.remove_bluetooth_persist_dropin"))
                remove_bind = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.remove_bluetooth_bind_mount_unit"))
                remove_persist = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.remove_persist_mount_unit"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.output", return_value="persist.mount"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.Path", side_effect=local_path))

                with redirect_stdout(StringIO()) as stdout:
                    migrate_bluetooth_state_to_rootfs()

            self.assertEqual((root_bluetooth / "controller/settings").read_text(encoding="utf-8"), "paired\n")
            self.assertFalse((root_bluetooth / "old").exists())
            self.assertTrue((persist_bluetooth / "controller/settings").exists())
            self.assertIn(["systemctl", "disable", "--now", "var-lib-bluetooth.mount"], commands)
            self.assertIn(["systemctl", "disable", "--now", "persist.mount"], commands)
            self.assertIn(["umount", config.persist_mount], commands)
            self.assertIn(["systemctl", "start", "bluetooth.service"], commands)
            self.assertIn("Data on the persistent device was left intact.", stdout.getvalue())
            remove_dropin.assert_called_once_with()
            remove_bind.assert_called_once_with()
            remove_persist.assert_called_once_with(config.persist_mount)
            restart_b2u.assert_called_once_with(True, "after migrating Bluetooth state back to rootfs")

    def test_migrate_bluetooth_state_removes_persist_unit_when_persist_mount_already_unmounted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            persist_bluetooth = root / "persist/bluetooth"
            persist_bluetooth.mkdir(parents=True)
            (persist_bluetooth / "settings").write_text("paired\n", encoding="utf-8")
            root_bluetooth = root / "var/lib/bluetooth"
            root_bluetooth.mkdir(parents=True)
            config = ReadonlyConfig(
                persist_mount=root / "persist",
                persist_bluetooth_dir=persist_bluetooth,
                persist_spec="/dev/disk/by-uuid/abc",
                persist_device="/dev/sda1",
            )
            commands = []

            def fake_run(command, *, check=True, capture=False):
                commands.append(command)

                class Completed:
                    returncode = 0
                    stdout = ""

                if command[:2] == ["mountpoint", "-q"] or command[:2] == ["findmnt", "-rn"]:
                    Completed.returncode = 1
                return Completed()

            def local_path(value: str) -> Path:
                if value == "/var/lib/bluetooth":
                    return root_bluetooth
                return Path(value)

            with ExitStack() as stack:
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.require_commands"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.current_root_filesystem_type", return_value="ext4"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.bluetooth_state_persistent", return_value=True))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}._systemctl_active", return_value=False))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.stop_b2u_if_installed", return_value=False))
                restart_b2u = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.restart_b2u_if_installed"))
                remove_persist = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.remove_persist_mount_unit"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.remove_bluetooth_persist_dropin"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.remove_bluetooth_bind_mount_unit"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.output", return_value="persist.mount"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.Path", side_effect=local_path))

                migrate_bluetooth_state_to_rootfs()

            self.assertIn(["systemctl", "disable", "--now", "persist.mount"], commands)
            self.assertNotIn(["umount", config.persist_mount], commands)
            remove_persist.assert_called_once_with(config.persist_mount)
            restart_b2u.assert_called_once_with(False, "after migrating Bluetooth state back to rootfs")

    def test_migrate_bluetooth_state_restores_services_when_persist_unmount_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            persist_bluetooth = root / "persist/bluetooth"
            persist_bluetooth.mkdir(parents=True)
            (persist_bluetooth / "settings").write_text("paired\n", encoding="utf-8")
            root_bluetooth = root / "var/lib/bluetooth"
            root_bluetooth.mkdir(parents=True)
            config = ReadonlyConfig(
                persist_mount=root / "persist",
                persist_bluetooth_dir=persist_bluetooth,
                persist_spec="/dev/disk/by-uuid/abc",
                persist_device="/dev/sda1",
            )
            commands = []

            def fake_run(command, *, check=True, capture=False):
                commands.append(command)
                if command == ["umount", config.persist_mount]:
                    raise OpsError("umount failed")

                class Completed:
                    returncode = 0
                    stdout = ""

                if command[:2] == ["mountpoint", "-q"]:
                    Completed.returncode = 1
                return Completed()

            def local_path(value: str) -> Path:
                if value == "/var/lib/bluetooth":
                    return root_bluetooth
                return Path(value)

            with ExitStack() as stack:
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.require_commands"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.current_root_filesystem_type", return_value="ext4"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.bluetooth_state_persistent", return_value=True))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}._systemctl_active", side_effect=[True, False]))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.stop_b2u_if_installed", return_value=True))
                restart_b2u = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.restart_b2u_if_installed"))
                remove_persist = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.remove_persist_mount_unit"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.remove_bluetooth_persist_dropin"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.remove_bluetooth_bind_mount_unit"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.output", return_value="persist.mount"))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run))
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.Path", side_effect=local_path))

                with redirect_stdout(StringIO()) as stdout:
                    migrate_bluetooth_state_to_rootfs()

            output = stdout.getvalue()
            self.assertIn(["systemctl", "start", "bluetooth.service"], commands)
            self.assertIn(["systemctl", "daemon-reload"], commands)
            self.assertIn(
                "Bluetooth state has been migrated back to /var/lib/bluetooth on the root filesystem.", output
            )
            self.assertIn("Persistent storage mount cleanup failed", output)
            self.assertIn(str(config.persist_mount), output)
            self.assertIn("Data on the persistent device was left intact.", output)
            remove_persist.assert_not_called()
            restart_b2u.assert_called_once_with(True, "after migrating Bluetooth state back to rootfs")
