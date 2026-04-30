import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.diagnostics import debug_report
from bluetooth_2_usb.ops.paths import ManagedPaths
from bluetooth_2_usb.ops.readonly import ReadonlyConfig


class OpsDiagnosticsTest(unittest.TestCase):
    def test_debug_report_keeps_writing_when_initial_systemctl_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ManagedPaths(install_dir=root / "missing-install", log_dir=root / "logs")
            config = ReadonlyConfig(
                mode="disabled",
                persist_mount=root / "persist",
                persist_bluetooth_dir=root / "persist" / "bluetooth",
                persist_spec="",
                persist_device="",
            )

            def fake_run(command, *, check=True, capture=False, timeout=None, **kwargs):
                if command[:3] == ["systemctl", "is-active", paths.service_unit]:
                    raise OpsError("systemctl unavailable")

                class Completed:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return Completed()

            with patch.dict(os.environ, {"HOSTNAME": "test-host"}):
                with patch("bluetooth_2_usb.ops.diagnostics.PATHS", paths):
                    with patch("bluetooth_2_usb.ops.diagnostics.run", side_effect=fake_run):
                        with patch(
                            "bluetooth_2_usb.ops.diagnostics.load_readonly_config",
                            return_value=config,
                        ):
                            with patch(
                                "bluetooth_2_usb.ops.diagnostics.overlay_status",
                                return_value="disabled",
                            ):
                                with patch(
                                    "bluetooth_2_usb.ops.diagnostics.readonly_mode",
                                    return_value="disabled",
                                ):
                                    with patch(
                                        "bluetooth_2_usb.ops.diagnostics.bluetooth_state_persistent",
                                        return_value=False,
                                    ):
                                        with patch(
                                            "bluetooth_2_usb.ops.diagnostics.rfkill_list_bluetooth",
                                            return_value="",
                                        ):
                                            with patch(
                                                "bluetooth_2_usb.ops.diagnostics.boot_config.detect_boot_dir",
                                                return_value=root / "boot",
                                            ):
                                                with patch(
                                                    "bluetooth_2_usb.ops.diagnostics.boot_config.boot_config_path",
                                                    return_value=root / "config.txt",
                                                ):
                                                    with patch(
                                                        "bluetooth_2_usb.ops.diagnostics.boot_config.boot_cmdline_path",
                                                        return_value=root / "cmdline.txt",
                                                    ):
                                                        self.assertEqual(debug_report(None), 0)

            report = next(paths.log_dir.glob("debug_*.md"))
            self.assertIn("initial_service_state=unknown", report.read_text(encoding="utf-8"))
