import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops import boot_config
from bluetooth_2_usb.ops.bluetooth import clear_bluetooth_rfkill_soft_blocks, rfkill_list_bluetooth
from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.readonly import (
    ReadonlyConfig,
    _restart_b2u_if_installed,
    _stop_b2u_if_installed,
    bluetooth_state_persistent,
    load_readonly_config,
    overlay_status,
    write_readonly_config,
)


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


class ReadonlyConfigTest(unittest.TestCase):
    def test_overlay_status_prefers_live_state(self) -> None:
        calls = []

        def fake_run(command, *, check=False, capture=True):
            calls.append(command)

            class Completed:
                returncode = 0
                stdout = "0\n"

            return Completed()

        with patch(
            "bluetooth_2_usb.ops.readonly.shutil.which", return_value="/usr/bin/raspi-config"
        ):
            with patch("bluetooth_2_usb.ops.readonly.run", side_effect=fake_run):
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

        with patch("bluetooth_2_usb.ops.readonly.run", side_effect=fake_run):
            with patch("pathlib.Path.is_dir", return_value=True):
                self.assertFalse(bluetooth_state_persistent(config))

    def test_b2u_service_helpers_preserve_inactive_service_state(self) -> None:
        calls = []

        def fake_run(command, *, check=True, capture=False):
            calls.append(command)

            class Completed:
                returncode = 1 if command[:3] == ["systemctl", "is-active", "--quiet"] else 0
                stdout = ""

            return Completed()

        with patch("bluetooth_2_usb.ops.deployment.service_installed", return_value=True):
            with patch("bluetooth_2_usb.ops.readonly.run", side_effect=fake_run):
                was_active = _stop_b2u_if_installed("during test")
                _restart_b2u_if_installed(was_active, "during test")

        self.assertFalse(was_active)
        self.assertNotIn(["systemctl", "stop", "bluetooth_2_usb.service"], calls)
        self.assertNotIn(["systemctl", "restart", "bluetooth_2_usb.service"], calls)
