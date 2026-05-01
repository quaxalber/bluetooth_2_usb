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
    _restart_b2u_if_installed,
    _stop_b2u_if_installed,
    bluetooth_state_persistent,
    enable_readonly,
    load_readonly_config,
    overlay_status,
    print_readonly_status,
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
    root: Path,
    index: int,
    *,
    type_name: str = "bluetooth",
    soft: str = "0",
    hard: str = "0",
    state: str = "1",
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

    def test_clear_bluetooth_rfkill_soft_blocks_with_no_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            clear_bluetooth_rfkill_soft_blocks(Path(tmpdir))

    def test_rfkill_list_bluetooth_handles_missing_rfkill_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rfkill_root = Path(tmpdir)
            _write_rfkill_entry(rfkill_root, 0, soft="1", hard="0", state="0")

            with patch("bluetooth_2_usb.ops.bluetooth.rfkill_root", return_value=rfkill_root):
                with patch(
                    "bluetooth_2_usb.ops.bluetooth.run", side_effect=OpsError("missing rfkill")
                ):
                    output = rfkill_list_bluetooth()

        self.assertIn("missing rfkill", output)
        self.assertIn("rfkill0 type=bluetooth soft=1 hard=0 state=0", output)


class BootConfigOpsTest(unittest.TestCase):
    def test_required_boot_modules_rejects_unknown_dwc2_mode(self) -> None:
        with self.assertRaises(OpsError):
            boot_config.required_boot_modules_csv("unknown")

    def test_normalize_modules_load_replaces_stale_otg_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cmdline = Path(tmpdir) / "cmdline.txt"
            cmdline.write_text("root=/dev/mmcblk0p2 modules-load=dwc2,libcomposite,foo quiet\n")

            boot_config.normalize_modules_load(cmdline, "libcomposite")

            self.assertEqual(
                cmdline.read_text(encoding="utf-8"),
                "root=/dev/mmcblk0p2 quiet modules-load=foo,libcomposite\n",
            )


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

    def test_readonly_config_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(load_readonly_config(Path(tmpdir) / "missing").mode, "disabled")

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

    def test_print_readonly_status_reports_configured_and_live_state(self) -> None:
        config = ReadonlyConfig(
            mode="persistent",
            persist_mount=Path("/mnt/persist"),
            persist_bluetooth_dir=Path("/mnt/persist/bluetooth"),
            persist_spec="/dev/disk/by-uuid/abc",
            persist_device="/dev/sda1",
        )

        def fake_findmnt(target: str | Path, field: str) -> str:
            values = {
                ("/", "SOURCE"): "overlayroot",
                ("/var/lib/bluetooth", "SOURCE"): "/dev/sda1[/bluetooth]",
            }
            return values.get((str(target), field), "")

        stdout = StringIO()
        with patch(f"{READONLY_STATUS}.load_readonly_config", return_value=config):
            with patch(f"{READONLY_STATUS}.readonly_mode", return_value="persistent"):
                with patch(f"{READONLY_STATUS}.overlay_status", return_value="enabled"):
                    with patch(
                        f"{READONLY_STATUS}.overlay_configured_status", return_value="enabled"
                    ):
                        with patch(
                            f"{READONLY_STATUS}._root_filesystem_type", return_value="overlay"
                        ):
                            with patch(
                                f"{READONLY_STATUS}.bluetooth_state_persistent", return_value=True
                            ):
                                with patch(
                                    f"{READONLY_STATUS}._findmnt_value", side_effect=fake_findmnt
                                ):
                                    with patch(f"{READONLY_STATUS}._mountpoint", return_value=True):
                                        with redirect_stdout(stdout):
                                            print_readonly_status()

        output = stdout.getvalue()
        self.assertIn("mode: persistent\n", output)
        self.assertIn("configured_mode: persistent\n", output)
        self.assertIn("overlay_live: enabled\n", output)
        self.assertIn("bluetooth_state_persistent: yes\n", output)
        self.assertIn("persist_device: /dev/sda1\n", output)

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
                was_active = _stop_b2u_if_installed("during test")
                _restart_b2u_if_installed(was_active, "during test")

        self.assertFalse(was_active)
        self.assertNotIn(["systemctl", "stop", "bluetooth_2_usb.service"], calls)
        self.assertNotIn(["systemctl", "restart", "bluetooth_2_usb.service"], calls)

    def test_bluetooth_bind_mount_unit_depends_on_persist_mount_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            unit_path = Path(tmpdir) / "var-lib-bluetooth.mount"
            paths = ManagedPaths(bluetooth_bind_mount_unit=unit_path)

            with patch(f"{READONLY_UNITS}.PATHS", paths):
                with patch("pathlib.Path.mkdir"):
                    with patch(
                        f"{READONLY_UNITS}.persist_mount_unit_name",
                        return_value="mnt-persist.mount",
                    ) as unit_name:
                        write_bluetooth_bind_mount_unit(
                            Path("/mnt/persist/custom/bluetooth"), Path("/mnt/persist")
                        )

            unit_name.assert_called_once_with(Path("/mnt/persist"))
            content = unit_path.read_text(encoding="utf-8")

        self.assertIn("After=mnt-persist.mount\n", content)
        self.assertIn("Requires=mnt-persist.mount\n", content)
        self.assertIn("What=/mnt/persist/custom/bluetooth\n", content)

    def test_enable_readonly_rolls_back_overlayfs_when_validation_fails(self) -> None:
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
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.load_readonly_config", return_value=config)
            )
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.machine_id_valid", return_value=True))
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.bluetooth_state_persistent", return_value=True)
            )
            stack.enter_context(
                patch(
                    f"{READONLY_WORKFLOWS}.readonly_stack_packages_bootstrap_safe",
                    return_value=True,
                )
            )
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_missing", return_value=False)
            )
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.readonly_stack_packages_healthy", return_value=True)
            )
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.overlay_status", return_value="disabled")
            )
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.current_kernel_release", return_value="6.6.1")
            )
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.configured_kernel_image", return_value="kernel8.img")
            )
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.configured_initramfs_file", return_value="")
            )
            stack.enter_context(
                patch(
                    f"{READONLY_WORKFLOWS}.expected_boot_initramfs_file",
                    return_value="initramfs8",
                )
            )
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.versioned_initrd_candidates", return_value=[])
            )
            stack.enter_context(
                patch(
                    f"{READONLY_WORKFLOWS}.ensure_bootable_initramfs_for_current_kernel",
                    side_effect=OpsError("initramfs failed"),
                )
            )
            stack.enter_context(patch(f"{READONLY_WORKFLOWS}.run", side_effect=fake_run))
            stack.enter_context(
                patch(f"{READONLY_WORKFLOWS}.write_readonly_config", side_effect=written.append)
            )

            with self.assertRaises(OpsError):
                enable_readonly()

        self.assertIn(["raspi-config", "nonint", "enable_overlayfs"], commands)
        self.assertIn(["raspi-config", "nonint", "disable_overlayfs"], commands)
        self.assertEqual(config.mode, "disabled")
        self.assertEqual(written, [config])
