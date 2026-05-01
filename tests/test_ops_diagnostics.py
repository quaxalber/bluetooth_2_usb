import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.diagnostics import ProbeStatus, SmokeTest, debug_report
from bluetooth_2_usb.ops.paths import ManagedPaths
from bluetooth_2_usb.ops.readonly import ReadonlyConfig


class OpsDiagnosticsTest(unittest.TestCase):
    def test_smoketest_records_structured_probe_results(self) -> None:
        smoke = SmokeTest(verbose=False, allow_non_pi=False)

        smoke._bool(True, "ok probe", "failed probe")
        smoke.soft_warn("warning probe")
        smoke.warn_fail("failed probe", "failure detail")

        self.assertEqual(
            [(result.status, result.message, result.detail) for result in smoke.results],
            [
                (ProbeStatus.PASS, "ok probe", ""),
                (ProbeStatus.WARN, "warning probe", ""),
                (ProbeStatus.FAIL, "failed probe", "failure detail"),
            ],
        )
        self.assertEqual(smoke.soft_warnings, 1)
        self.assertEqual(smoke.exit_code, 1)

    def test_smoketest_downgrades_unknown_dwc2_mode_to_heuristic_warning(self) -> None:
        smoke = SmokeTest(verbose=False, allow_non_pi=True)
        checked_modules = []

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with ExitStack() as stack:
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.diagnostics.readonly_mode", return_value="disabled")
                )
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.diagnostics.overlay_status", return_value="disabled")
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics._first_modules_load",
                        return_value="modules-load=libcomposite",
                    )
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics.boot_config.dwc2_mode",
                        return_value="unknown",
                    )
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics.boot_config.required_boot_modules_csv",
                        side_effect=AssertionError("should not require known dwc2 mode"),
                    )
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics.boot_config.boot_config_path",
                        return_value=root / "config.txt",
                    )
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics.boot_config.boot_cmdline_path",
                        return_value=root / "cmdline.txt",
                    )
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics.boot_config.expected_dwc2_overlay_line",
                        return_value="dtoverlay=dwc2",
                    )
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics.boot_config.current_root_filesystem_type",
                        return_value="ext4",
                    )
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics.bluetooth_state_persistent",
                        return_value=False,
                    )
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics.boot_config.expected_boot_initramfs_file",
                        return_value="",
                    )
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics.bluetooth_rfkill_entries",
                        return_value=[object()],
                    )
                )
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.diagnostics.bluetooth_rfkill_blocked",
                        return_value=False,
                    )
                )
                stack.enter_context(patch.object(smoke, "_check_boot_overlay"))
                stack.enter_context(
                    patch.object(
                        smoke,
                        "_check_modules",
                        side_effect=lambda _token, required: checked_modules.extend(required),
                    )
                )
                for method in (
                    "_path_exists",
                    "_command_ok",
                    "_bool",
                    "_check_overlay_runtime",
                    "_check_initramfs",
                    "_check_readonly",
                ):
                    stack.enter_context(patch.object(smoke, method))
                stack.enter_context(patch.object(smoke, "_capture", return_value=(0, "[]")))
                stack.enter_context(patch.object(smoke, "_relayable_count", return_value=0))
                stack.enter_context(patch.object(smoke, "_paired_count", return_value=0))

                self.assertEqual(smoke.run(), 0)

        self.assertEqual(checked_modules, ["libcomposite"])
        self.assertEqual(smoke.soft_warnings, 1)

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
