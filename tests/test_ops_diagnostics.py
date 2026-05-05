import os
import signal
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.diagnostics import ProbeStatus, SmokeTest, debug_report
from bluetooth_2_usb.ops.diagnostics.redaction import redact
from bluetooth_2_usb.ops.paths import ManagedPaths
from bluetooth_2_usb.ops.readonly import ReadonlyConfig

DIAGNOSTICS_REPORT = "bluetooth_2_usb.ops.diagnostics.report"
DIAGNOSTICS_SMOKETEST = "bluetooth_2_usb.ops.diagnostics.smoketest"


class _RfkillEntry:
    def line(self) -> str:
        return "rfkill0 type=bluetooth soft=0 hard=0 state=1"


class OpsDiagnosticsTest(unittest.TestCase):
    def run_smoketest_harness(
        self,
        smoke: SmokeTest,
        *,
        root: Path,
        dwc2_mode: str = "module",
        modules_load: str = "",
        rfkill_entries: list[_RfkillEntry] | None = None,
        rfkill_blocked: bool = False,
        udc_states: dict[str, str] | None = None,
    ) -> list[str]:
        checked_modules: list[str] = []

        with ExitStack() as stack:
            stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.readonly_mode", return_value="disabled"))
            stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.overlay_status", return_value="disabled"))
            stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}._first_modules_load", return_value=modules_load))
            stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.dwc2_mode", return_value=dwc2_mode))
            stack.enter_context(
                patch(
                    f"{DIAGNOSTICS_SMOKETEST}.boot_config.required_boot_modules_csv",
                    side_effect=(
                        AssertionError("known dwc2 mode should not be required") if dwc2_mode == "unknown" else None
                    ),
                    return_value="dwc2",
                )
            )
            stack.enter_context(
                patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.boot_config_path", return_value=root / "config.txt")
            )
            stack.enter_context(
                patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.boot_cmdline_path", return_value=root / "cmdline.txt")
            )
            stack.enter_context(
                patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.expected_dwc2_overlay_line", return_value="")
            )
            stack.enter_context(
                patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.current_root_filesystem_type", return_value="ext4")
            )
            stack.enter_context(
                patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.configured_kernel_image", return_value="kernel8.img")
            )
            stack.enter_context(
                patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.configured_initramfs_file", return_value="")
            )
            stack.enter_context(
                patch(f"{DIAGNOSTICS_SMOKETEST}.boot_config.expected_boot_initramfs_file", return_value="")
            )
            stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.bluetooth_state_persistent", return_value=False))
            stack.enter_context(
                patch(f"{DIAGNOSTICS_SMOKETEST}._udc_states", return_value=udc_states or {"dummy.udc": "configured"})
            )
            stack.enter_context(
                patch(f"{DIAGNOSTICS_SMOKETEST}.bluetooth_rfkill_entries", return_value=rfkill_entries or [])
            )
            stack.enter_context(patch(f"{DIAGNOSTICS_SMOKETEST}.bluetooth_rfkill_blocked", return_value=rfkill_blocked))
            stack.enter_context(patch.object(smoke, "_check_boot_overlay"))
            stack.enter_context(
                patch.object(
                    smoke, "_check_modules", side_effect=lambda _token, required: checked_modules.extend(required)
                )
            )
            for method in (
                "_path_exists",
                "_command_ok",
                "_check_overlay_runtime",
                "_check_initramfs",
                "_check_readonly",
            ):
                stack.enter_context(patch.object(smoke, method))
            stack.enter_context(patch.object(smoke, "_capture", return_value=(0, "[]")))
            stack.enter_context(patch.object(smoke, "_relayable_count", return_value=0))
            stack.enter_context(patch.object(smoke, "_paired_count", return_value=0))

            smoke.run()

        return checked_modules

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

        with tempfile.TemporaryDirectory() as tmpdir:
            checked_modules = self.run_smoketest_harness(
                smoke,
                root=Path(tmpdir),
                dwc2_mode="unknown",
                modules_load="modules-load=libcomposite",
                rfkill_entries=[_RfkillEntry()],
            )

        self.assertEqual(checked_modules, ["libcomposite"])
        self.assertEqual(smoke.soft_warnings, 1)

    def test_smoketest_warns_when_udc_is_not_configured(self) -> None:
        smoke = SmokeTest(verbose=False, allow_non_pi=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            self.run_smoketest_harness(
                smoke, root=Path(tmpdir), modules_load="modules-load=dwc2", udc_states={"dummy.udc": "not attached"}
            )

        warnings = [result for result in smoke.results if result.status is ProbeStatus.WARN]
        self.assertTrue(any("UDC is not configured" in result.message for result in warnings))
        self.assertEqual(smoke.summary["UDC state"], "dummy.udc=not attached")

    def test_smoketest_records_healthy_rfkill_probe(self) -> None:
        smoke = SmokeTest(verbose=False, allow_non_pi=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.run_smoketest_harness(smoke, root=Path(tmpdir), rfkill_entries=[_RfkillEntry()])

        rfkill_results = [
            result for result in smoke.results if result.message == "Bluetooth rfkill state is not blocked"
        ]
        self.assertEqual(len(rfkill_results), 1)
        self.assertEqual(rfkill_results[0].status, ProbeStatus.PASS)
        self.assertEqual(rfkill_results[0].detail, "rfkill0 type=bluetooth soft=0 hard=0 state=1")
        self.assertEqual(stdout.getvalue().count("[+] Bluetooth rfkill state is not blocked"), 1)

    def test_smoketest_verbose_summary_groups_related_items_in_logical_order(self) -> None:
        smoke = SmokeTest(verbose=True, allow_non_pi=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.run_smoketest_harness(smoke, root=Path(tmpdir), rfkill_entries=[_RfkillEntry()])

        output = stdout.getvalue()
        self.assertLess(output.index("### Boot and USB"), output.index("### Bluetooth"))
        self.assertLess(output.index("### Bluetooth"), output.index("### Read-Only Mode"))
        self.assertLess(output.index("### Read-Only Mode"), output.index("### Result"))

        readonly_group = output[output.index("### Read-Only Mode") : output.index("### Result")]
        self.assertLess(readonly_group.index("Read-only mode:"), readonly_group.index("OverlayFS configured:"))
        self.assertLess(readonly_group.index("OverlayFS configured:"), readonly_group.index("Root filesystem type:"))
        self.assertLess(readonly_group.index("Root filesystem type:"), readonly_group.index("Root overlay active:"))
        self.assertLess(
            readonly_group.index("Root overlay active:"), readonly_group.index("Bluetooth persistent mount:")
        )
        self.assertEqual(smoke.result_dict()["summary"]["Bluetooth persistent mount"], "not mounted")

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

    def test_debug_report_keeps_writing_when_readonly_config_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ManagedPaths(install_dir=root / "missing-install", log_dir=root / "logs")

            def fake_run(command, *, check=True, capture=False, timeout=None, **kwargs):
                del command, check, capture, timeout, kwargs

                class Completed:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return Completed()

            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"HOSTNAME": "test-host"}))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.PATHS", paths))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.run", side_effect=fake_run))
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_REPORT}.load_readonly_config", side_effect=OpsError("invalid readonly env"))
                )
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.overlay_status", return_value="disabled"))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.readonly_mode", return_value="disabled"))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.rfkill_list_bluetooth", return_value=""))
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_REPORT}.boot_config.detect_boot_dir", return_value=root / "boot")
                )
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_REPORT}.boot_config.boot_config_path", return_value=root / "config.txt")
                )
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_REPORT}.boot_config.boot_cmdline_path", return_value=root / "cmdline.txt")
                )

                self.assertEqual(debug_report(None), 0)

            report = next(paths.log_dir.glob("debug_*.md")).read_text(encoding="utf-8")
            self.assertIn("bluetooth_state_persistent_mount=unknown", report)
            self.assertIn("Read-only config parse error: invalid readonly env", report)

    def test_debug_report_records_os_errors_as_command_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ManagedPaths(install_dir=root / "install", log_dir=root / "logs")
            paths.venv_python.parent.mkdir(parents=True)
            paths.venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
            config = ReadonlyConfig(
                mode="disabled",
                persist_mount=root / "persist",
                persist_bluetooth_dir=root / "persist" / "bluetooth",
                persist_spec="",
                persist_device="",
            )

            def fake_run(command, *, check=True, capture=False, timeout=None, **kwargs):
                if command[:2] == [paths.venv_python, "-m"]:
                    raise PermissionError("venv python is not executable")

                class Completed:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return Completed()

            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"HOSTNAME": "test-host"}))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.PATHS", paths))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.run", side_effect=fake_run))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.load_readonly_config", return_value=config))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.overlay_status", return_value="disabled"))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.readonly_mode", return_value="disabled"))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.bluetooth_state_persistent", return_value=False))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.rfkill_list_bluetooth", return_value=""))
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_REPORT}.boot_config.detect_boot_dir", return_value=root / "boot")
                )
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_REPORT}.boot_config.boot_config_path", return_value=root / "config.txt")
                )
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_REPORT}.boot_config.boot_cmdline_path", return_value=root / "cmdline.txt")
                )

                self.assertEqual(debug_report(None), 0)

            report = next(paths.log_dir.glob("debug_*.md")).read_text(encoding="utf-8")
            self.assertIn("venv python is not executable", report)
            self.assertIn("[command failed]", report)

    def test_debug_report_cleans_up_live_debug_after_keyboard_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "venv/bin").mkdir(parents=True)
            (root / "venv/bin/python").touch()
            paths = ManagedPaths(install_dir=root, log_dir=root / "logs", readonly_env_file=root / "readonly-env")
            config = ReadonlyConfig(
                mode="disabled",
                persist_mount=root / "persist",
                persist_bluetooth_dir=root / "persist" / "bluetooth",
                persist_spec="",
                persist_device="",
            )

            class FakeProcess:
                pid = 1234

                def __init__(self) -> None:
                    self.wait_calls = 0

                def wait(self, timeout=None):
                    self.wait_calls += 1
                    if self.wait_calls == 1:
                        raise KeyboardInterrupt
                    if self.wait_calls == 2:
                        raise subprocess.TimeoutExpired("debug", timeout)
                    return 0

            process = FakeProcess()

            def fake_run(command, *, check=True, capture=False, timeout=None, **kwargs):
                class Completed:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                if command[:3] == ["systemctl", "is-active", paths.service_unit]:
                    Completed.stdout = "inactive\n"
                elif command[:3] == ["systemctl", "is-active", "--quiet"]:
                    Completed.returncode = 1
                elif command[-2:] == ["--print-shell-command", "--append-debug"]:
                    Completed.stdout = "echo live-debug\n"
                return Completed()

            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"HOSTNAME": "test-host"}))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.PATHS", paths))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.run", side_effect=fake_run))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.load_readonly_config", return_value=config))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.overlay_status", return_value="disabled"))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.readonly_mode", return_value="disabled"))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.bluetooth_state_persistent", return_value=False))
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.rfkill_list_bluetooth", return_value=""))
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_REPORT}.boot_config.detect_boot_dir", return_value=root / "boot")
                )
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_REPORT}.boot_config.boot_config_path", return_value=root / "config.txt")
                )
                stack.enter_context(
                    patch(f"{DIAGNOSTICS_REPORT}.boot_config.boot_cmdline_path", return_value=root / "cmdline.txt")
                )
                stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.subprocess.Popen", return_value=process))
                killpg = stack.enter_context(patch(f"{DIAGNOSTICS_REPORT}.os.killpg"))

                self.assertEqual(debug_report(None), 0)

            report = next(paths.log_dir.glob("debug_*.md")).read_text(encoding="utf-8")
            self.assertIn("Live Bluetooth-2-USB debug output", report)
        self.assertEqual(
            [call.args for call in killpg.call_args_list],
            [(process.pid, signal.SIGTERM), (process.pid, signal.SIGKILL)],
        )
