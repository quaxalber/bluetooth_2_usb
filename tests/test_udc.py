import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.udc import resolve_single_udc_name, resolve_single_udc_state_path, udc_states


class UdcDiscoveryTest(unittest.TestCase):
    def test_resolve_single_udc_name_returns_the_only_controller(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            udc_root = Path(tmpdir)
            (udc_root / "fe980000.usb").mkdir()

            self.assertEqual(resolve_single_udc_name(udc_root), "fe980000.usb")

    def test_resolve_single_udc_name_fails_when_no_controller_exists(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            self.assertRaisesRegex(FileNotFoundError, "No UDC controller was found"),
        ):
            resolve_single_udc_name(Path(tmpdir))

    def test_resolve_single_udc_name_fails_when_root_is_missing(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            self.assertRaisesRegex(FileNotFoundError, "No UDC controller was found"),
        ):
            resolve_single_udc_name(Path(tmpdir) / "missing")

    def test_resolve_single_udc_name_fails_when_multiple_controllers_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            udc_root = Path(tmpdir)
            (udc_root / "aaa-host").mkdir()
            (udc_root / "fe980000.usb").mkdir()

            with self.assertRaisesRegex(RuntimeError, "Multiple UDC controllers"):
                resolve_single_udc_name(udc_root)

    def test_resolve_single_udc_name_preserves_permission_errors(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(Path, "iterdir", side_effect=PermissionError(errno.EACCES, "permission denied")),
            self.assertRaises(PermissionError),
        ):
            resolve_single_udc_name(Path(tmpdir))

    def test_resolve_single_udc_state_path_requires_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            udc_root = Path(tmpdir)
            (udc_root / "fe980000.usb").mkdir()

            with self.assertRaisesRegex(FileNotFoundError, "UDC state file not found"):
                resolve_single_udc_state_path(udc_root)

    def test_resolve_single_udc_state_path_returns_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            udc_root = Path(tmpdir)
            controller = udc_root / "fe980000.usb"
            controller.mkdir()
            state = controller / "state"
            state.write_text("configured\n", encoding="utf-8")

            self.assertEqual(resolve_single_udc_state_path(udc_root), state)

    def test_udc_states_reads_each_controller_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            udc_root = Path(tmpdir)
            controller = udc_root / "fe980000.usb"
            controller.mkdir()
            (controller / "state").write_text("configured\n", encoding="utf-8")

            self.assertEqual(udc_states(udc_root), {"fe980000.usb": "configured"})

    def test_udc_states_reports_unknown_when_state_cannot_be_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            udc_root = Path(tmpdir)
            controller = udc_root / "fe980000.usb"
            controller.mkdir()

            self.assertEqual(udc_states(udc_root), {"fe980000.usb": "unknown"})
