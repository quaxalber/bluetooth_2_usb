import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops.bluetooth import clear_bluetooth_rfkill_soft_blocks
from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.readonly import (
    ReadonlyConfig,
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
