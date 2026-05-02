import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.diagnostics import ProbeStatus, SmokeTest, debug_report
from bluetooth_2_usb.ops.diagnostics.redaction import redact
from bluetooth_2_usb.ops.paths import ManagedPaths
from bluetooth_2_usb.ops.readonly import ReadonlyConfig

DIAGNOSTICS_REPORT = "bluetooth_2_usb.ops.diagnostics.report"
DIAGNOSTICS_SMOKETEST = "bluetooth_2_usb.ops.diagnostics.smoketest"


class OpsDiagnosticsTest(unittest.TestCase):
    def test_smoketest_records_structured_probe_results(self) -> None:
        smoke = SmokeTest(verbose=False, allow_non_pi=False)

        smoke.record_bool(True, "ok probe", "failed probe")
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
        self.assertEqual(
            smoke.result_dict(),
            {
                "exit_code": 1,
                "result": "failed",
                "soft_warnings": 1,
                "summary": {},
                "probes": [
                    {"status": "pass", "message": "ok probe", "detail": ""},
                    {"status": "warn", "message": "warning probe", "detail": ""},
                    {"status": "fail", "message": "failed probe", "detail": "failure detail"},
                ],
            },
        )

    def test_redaction_keeps_partuuid_and_uuid_patterns_distinct(self) -> None:
        redacted = redact(
            "root=PARTUUID=1111-2222 boot=UUID=3333-4444 " + "/dev/disk/by-partuuid/aaaa /dev/disk/by-uuid/bbbb",
            hostname="",
        )

        self.assertIn("PARTUUID=<<REDACTED_PARTUUID>>", redacted)
        self.assertIn("UUID=<<REDACTED_UUID>>", redacted)
        self.assertIn("/dev/disk/by-partuuid/<<REDACTED_PARTUUID>>", redacted)
        self.assertIn("/dev/disk/by-uuid/<<REDACTED_UUID>>", redacted)

    def test_redaction_hides_hostname_case_insensitively(self) -> None:
        redacted = redact("Test-Host test-host TEST-HOST", hostname="test-host")

        self.assertEqual(redacted, "<<REDACTED_HOSTNAME>> <<REDACTED_HOSTNAME>> <<REDACTED_HOSTNAME>>")

    def test_smoketest_downgrades_unknown_dwc2_mode_to_heuristic_warning(self) -> None:
        smoke = SmokeTest(verbose=False, allow_non_pi=True)
        checked_modules = []

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with ExitStack() as stack:
                stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.readonly_mode", return_value="disabled"))
                stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.overlay_status", return_value="disabled"))
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_SMOKETEST}._first_modules_load", return_value="modules-load=libcomposite")
                )
                stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.dwc2_mode", return_value="unknown"))
                stack.enter_context(
                    patch(
                        f"{DIAGNOSTICS_SMOKETEST}.boot_config.required_boot_modules_csv",
                        side_effect=AssertionError("should not require known dwc2 mode"),
                    )
                )
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.boot_config_path", return_value=root / "config.txt")
                )
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.boot_cmdline_path", return_value=root / "cmdline.txt")
                )
                stack.enter_context(
                    patch(
                        f"{DIAGNOSTICS_SMOKETEST}.boot_config.expected_dwc2_overlay_line", return_value="dtoverlay=dwc2"
                    )
                )
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.current_root_filesystem_type", return_value="ext4")
                )
                stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.bluetooth_state_persistent", return_value=False))
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.expected_boot_initramfs_file", return_value="")
                )
                stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.bluetooth_rfkill_entries", return_value=[object()]))
                stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.bluetooth_rfkill_blocked", return_value=False))
                stack.enter_context(patch.object(smoke, "_check_boot_overlay"))
                stack.enter_context(
                    patch.object(
                        smoke, "_check_modules", side_effect=lambda _token, required: checked_modules.extend(required)
                    )
                )
                for method in (
                    "_path_exists",
                    "_command_ok",
                    "record_bool",
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
                with patch(f"{DIAGNOSTICS_REPORT}.PATHS", paths):
                    with patch(f"{DIAGNOSTICS_REPORT}.run", side_effect=fake_run):
                        with patch(f"{DIAGNOSTICS_REPORT}.load_readonly_config", return_value=config):
                            with patch(f"{DIAGNOSTICS_REPORT}.overlay_status", return_value="disabled"):
                                with patch(f"{DIAGNOSTICS_REPORT}.readonly_mode", return_value="disabled"):
                                    with patch(f"{DIAGNOSTICS_REPORT}.bluetooth_state_persistent", return_value=False):
                                        with patch(f"{DIAGNOSTICS_REPORT}.rfkill_list_bluetooth", return_value=""):
                                            with patch(
                                                f"{DIAGNOSTICS_REPORT}.boot_config.detect_boot_dir",
                                                return_value=root / "boot",
                                            ):
                                                with patch(
                                                    f"{DIAGNOSTICS_REPORT}.boot_config.boot_config_path",
                                                    return_value=root / "config.txt",
                                                ):
                                                    with patch(
                                                        f"{DIAGNOSTICS_REPORT}.boot_config.boot_cmdline_path",
                                                        return_value=root / "cmdline.txt",
                                                    ):
                                                        self.assertEqual(debug_report(None), 0)

            report = next(paths.log_dir.glob("debug_*.md"))
            self.assertIn("initial_service_state=unknown", report.read_text(encoding="utf-8"))
