import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

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

            with patch("bluetooth_2_usb.ops.bluetooth.rfkill_root", return_value=rfkill_root):
                with patch("bluetooth_2_usb.ops.bluetooth.run", side_effect=OpsError("missing rfkill")):
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

            with patch("bluetooth_2_usb.ops.boot_config.boot_config_model_filters", return_value=["cm4"]):
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
            with self.subTest(target=target):
                with self.assertRaises(OpsError):
                    boot_config.boot_initramfs_target_path(target)


class ReadonlyConfigTest(unittest.TestCase):
    def test_overlay_status_prefers_live_state(self) -> None:
        calls = []

        def fake_run(command, *, check=False, capture=True):
            calls.append(command)

            class Completed:
                returncode = 0
                stdout = "0\n"

            return Completed()

        with patch(f"{READONLY_STATUS}.shutil.which", return_value="/usr/bin/raspi-config"):
            with patch(f"{READONLY_STATUS}.run", side_effect=fake_run):
                self.assertEqual(overlay_status(), "enabled")

        self.assertEqual(calls[0], ["raspi-config", "nonint", "get_overlay_now"])

    def test_overlay_status_returns_unknown_when_raspi_config_probe_fails(self) -> None:
        with patch(f"{READONLY_STATUS}.shutil.which", return_value="/usr/bin/raspi-config"):
            with patch(f"{READONLY_STATUS}.run", side_effect=OpsError("raspi-config failed")):
                self.assertEqual(overlay_status(), "unknown")

    def test_overlay_configured_status_returns_unknown_when_probe_fails(self) -> None:
        with patch(f"{READONLY_STATUS}.shutil.which", return_value="/usr/bin/raspi-config"):
            with patch(f"{READONLY_STATUS}.run", side_effect=OSError("raspi-config unavailable")):
                self.assertEqual(overlay_configured_status(), "unknown")

    def test_package_status_returns_empty_when_dpkg_probe_fails(self) -> None:
        with patch(f"{READONLY_STATUS}.run", side_effect=OpsError("dpkg unavailable")):
            self.assertEqual(package_status("overlayroot"), "")

    def test_readonly_config_round_trips_supported_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "readonly.env"
            config = ReadonlyConfig(
                mode="persistent",
                persist_mount=Path("/mnt/persist"),
                persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
                persist_spec="/dev/disk/by-uuid/abc",
                persist_device="/dev/sda1",
            )

            write_readonly_config(config, path)

            self.assertEqual(load_readonly_config(path), config)

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

        self.assertEqual(config.mode, "disabled")
        self.assertEqual(config.persist_bluetooth_dir, Path("/tmp/persist/bt-state"))

    def test_bluetooth_state_persistent_rejects_bluetooth_dir_outside_persist_mount(self) -> None:
        config = ReadonlyConfig(
            mode="persistent",
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

        with patch(f"{READONLY_STATUS}.run", side_effect=fake_run):
            with patch("pathlib.Path.is_dir", return_value=True):
                self.assertFalse(bluetooth_state_persistent(config))

    def test_bluetooth_state_persistent_returns_false_when_findmnt_fails(self) -> None:
        config = ReadonlyConfig(
            mode="persistent",
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
            mode="persistent",
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
            patch(f"{READONLY_STATUS}.readonly_mode", return_value="persistent"),
            patch(f"{READONLY_STATUS}.overlay_status", return_value="enabled"),
            patch(f"{READONLY_STATUS}.overlay_configured_status", return_value="enabled"),
            patch(f"{READONLY_STATUS}._root_filesystem_type", return_value="overlay"),
            patch(f"{READONLY_STATUS}.bluetooth_state_persistent", return_value=True),
            patch(f"{READONLY_STATUS}._findmnt_value", side_effect=fake_findmnt),
            patch(f"{READONLY_STATUS}._mountpoint", return_value=True),
            redirect_stdout(stdout),
        ):
            print_readonly_status()

        output = stdout.getvalue()
        self.assertIn("read-only mode: enabled\n", output)
        self.assertIn("configured read-only mode: enabled\n", output)
        self.assertIn("overlay_live: enabled\n", output)
        self.assertIn("bluetooth state writable storage: mounted\n", output)
        self.assertIn("persist_device: /dev/sda1\n", output)

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
        self.assertIn("configured read-only mode: disabled\n", output)
        self.assertIn("bluetooth state writable storage: not mounted\n", output)
        self.assertIn("persist_device: <unset>\n", output)

    def test_b2u_service_helpers_preserve_inactive_service_state(self) -> None:
        calls = []

        def fake_run(command, *, check=True, capture=False):
            calls.append(command)

            class Completed:
                returncode = 1 if command[:3] == ["systemctl", "is-active", "--quiet"] else 0
                stdout = ""

            return Completed()

        with patch("bluetooth_2_usb.ops.deployment.service_installed", return_value=True):
            with patch(f"{READONLY_SERVICE}.run", side_effect=fake_run):
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
                mode="disabled",
                persist_mount=root / "persist",
                persist_bluetooth_dir=root / "persist" / "bluetooth",
                persist_spec="",
                persist_device="",
            )
            commands = []
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
                stack.enter_context(patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config))
                stack.enter_context(
                    patch(f"{READONLY_WORKFLOWS}.persist_spec_from_device", return_value="/dev/disk/by-uuid/abc")
                )
                stack.enter_context(
                    patch(f"{READONLY_WORKFLOWS}.write_persist_mount_unit", return_value="mnt-persist.mount")
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

    def test_enable_readonly_does_not_rollback_overlayfs_when_validation_fails(self) -> None:
        config = ReadonlyConfig(
            mode="disabled",
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
            persist_spec="/dev/sda1",
            persist_device="/dev/sda1",
        )
        commands = []
        written = []

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
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_bootstrap_safe", return_value=True)
            )
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_missing", return_value=False))
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
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.write_readonly_config", side_effect=written.append))

            with self.assertRaises(OpsError):
                with redirect_stdout(StringIO()) as stdout:
                    enable_readonly()

        self.assertIn(["raspi-config", "nonint", "enable_overlayfs"], commands)
        self.assertNotIn(["raspi-config", "nonint", "disable_overlayfs"], commands)
        self.assertEqual(config.mode, "disabled")
        self.assertEqual(written, [])
        self.assertIn("readonly status", stdout.getvalue())
        self.assertIn(
            "https://github.com/quaxalber/bluetooth_2_usb/blob/main/docs/persistent-readonly.md"
            "#overlayfs-repair-guidance",
            stdout.getvalue(),
        )

    def test_enable_readonly_reports_repair_guidance_when_overlayfs_enable_fails(self) -> None:
        config = ReadonlyConfig(
            mode="disabled",
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
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_bootstrap_safe", return_value=True)
            )
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_missing", return_value=False))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.overlay_status", return_value="disabled"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.current_kernel_release", return_value="6.6.1"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.configured_kernel_image", return_value="kernel8.img"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.configured_initramfs_file", return_value=""))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.expected_boot_initramfs_file", return_value="initramfs8"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.versioned_initrd_candidates", return_value=[]))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=OpsError("raspi-config failed")))
            write_config = stack.enter_context(patch(f"{READONLY_WORKFLOWS}.write_readonly_config"))

            with self.assertRaises(OpsError):
                with redirect_stdout(StringIO()) as stdout:
                    enable_readonly()

        write_config.assert_not_called()
        self.assertIn("readonly status", stdout.getvalue())
        self.assertIn(
            "https://github.com/quaxalber/bluetooth_2_usb/blob/main/docs/persistent-readonly.md"
            "#overlayfs-repair-guidance",
            stdout.getvalue(),
        )
        self.assertIn("disable OverlayFS", stdout.getvalue())

    def test_disable_readonly_disables_overlayfs_and_keeps_persistent_mount_config(self) -> None:
        config = ReadonlyConfig(
            mode="persistent",
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
            persist_spec="/dev/disk/by-uuid/abc",
            persist_device="/dev/sda1",
        )
        commands = []
        written = []

        def fake_run(command, *, check=True, capture=False):
            commands.append(command)

            class Completed:
                returncode = 0
                stdout = ""

            return Completed()

        with ExitStack() as stack:
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.require_commands"))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run))
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.write_readonly_config", side_effect=written.append))

            with redirect_stdout(StringIO()) as stdout:
                disable_readonly()

        self.assertEqual(commands, [["raspi-config", "nonint", "disable_overlayfs"]])
        self.assertEqual(config.mode, "disabled")
        self.assertEqual(written, [config])
        self.assertEqual(config.persist_spec, "/dev/disk/by-uuid/abc")
        self.assertIn("Persistent Bluetooth state mount configuration was kept.", stdout.getvalue())
        self.assertNotIn("Writable Bluetooth state " + "mount configuration was kept.", stdout.getvalue())
