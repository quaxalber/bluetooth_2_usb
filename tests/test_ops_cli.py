import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops import cli
from bluetooth_2_usb.ops.commands import close_log, prepare_log
from bluetooth_2_usb.ops.paths import ManagedPaths

REPO_ROOT = Path(__file__).resolve().parents[1]


class OpsCliTest(unittest.TestCase):
    def tearDown(self) -> None:
        close_log()

    def test_non_loopback_command_rejects_unknown_args(self) -> None:
        with self.assertRaises(SystemExit) as raised, patch("sys.stderr", new=io.StringIO()):
            cli.main(["smoketest", "--unknown"], prog="bluetooth_2_usb")

        self.assertEqual(raised.exception.code, 2)

    def test_readonly_setup_dispatches_device_to_workflow(self) -> None:
        with (
            patch("bluetooth_2_usb.ops.cli.ensure_root"),
            patch("bluetooth_2_usb.ops.cli.prepare_log"),
            patch("bluetooth_2_usb.ops.cli.setup_persistent_bluetooth_state") as setup,
        ):
            self.assertEqual(cli.main(["readonly", "setup", "--device", "/dev/sda1"]), 0)

        setup.assert_called_once_with("/dev/sda1")

    def test_nested_operational_commands_dispatch_to_selected_workflow(self) -> None:
        cases = (
            (["readonly", "status"], "print_readonly_status"),
            (["readonly", "enable"], "enable_readonly"),
            (["readonly", "disable"], "disable_readonly"),
            (["udev", "install"], "install_hid_udev_rule"),
        )

        for argv, target in cases:
            with self.subTest(argv=argv):
                with (
                    patch("bluetooth_2_usb.ops.cli.ensure_root"),
                    patch("bluetooth_2_usb.ops.cli.prepare_log"),
                    patch(f"bluetooth_2_usb.ops.cli.{target}") as command,
                ):
                    self.assertEqual(cli.main(argv), 0)

                command.assert_called_once()

    def test_udev_install_help_exposes_repo_root_option(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["udev", "install", "--help"], prog="bluetooth_2_usb")

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--repo-root REPO_ROOT", stdout.getvalue())
        self.assertIn("udev/70-bluetooth_2_usb_hidapi.rules", stdout.getvalue())

    def test_smoketest_json_output_prints_structured_result(self) -> None:
        class FakeSmokeTest:
            def __init__(self, *, verbose: bool, allow_non_pi: bool) -> None:
                self.verbose = verbose
                self.allow_non_pi = allow_non_pi

            def run(self) -> int:
                print("probe text")
                return 0

            def result_dict(self) -> dict[str, object]:
                return {"exit_code": 0, "result": "ok"}

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("bluetooth_2_usb.ops.cli.ensure_root"),
            patch("bluetooth_2_usb.ops.cli.prepare_log"),
            patch("bluetooth_2_usb.ops.cli.SmokeTest", FakeSmokeTest),
            redirect_stdout(stdout),
            patch("sys.stderr", stderr),
        ):
            exit_code = cli.main(["smoketest", "--output", "json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"exit_code": 0, "result": "ok"})
        self.assertIn("probe text", stderr.getvalue())

    def test_prepare_log_closes_file_and_restores_streams(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = io.StringIO()
            with patch("bluetooth_2_usb.ops.commands.PATHS", ManagedPaths(log_dir=Path(tmpdir))):
                with redirect_stdout(stdout):
                    log_path = prepare_log("test")
                    print("payload")
                    close_log()

            self.assertIn("payload", stdout.getvalue())
            self.assertIn("payload", log_path.read_text(encoding="utf-8"))

    def test_gadget_identity_import_does_not_load_usb_hid(self) -> None:
        self.assert_import_does_not_load_usb_hid("import bluetooth_2_usb.gadgets.identity")

    def test_operational_cli_import_does_not_load_usb_hid(self) -> None:
        self.assert_import_does_not_load_usb_hid("import bluetooth_2_usb.ops.cli")

    def test_gadgets_package_import_does_not_load_usb_hid(self) -> None:
        self.assert_import_does_not_load_usb_hid("import bluetooth_2_usb.gadgets")

    def test_validate_env_does_not_load_usb_hid(self) -> None:
        command = (
            "import sys; "
            "from bluetooth_2_usb.cli import run; "
            "exit_code = run(['--validate-env']); "
            "print('USB_HID_LOADED=' + str('usb_hid' in sys.modules)); "
            "raise SystemExit(exit_code)"
        )
        completed = self.run_import_probe(command)

        self.assertIn(completed.returncode, {0, 3})
        self.assertIn("USB_HID_LOADED=False", completed.stdout)

    def test_gadgets_package_lazy_exports_still_work(self) -> None:
        command = (
            "from bluetooth_2_usb.gadgets import GadgetLayout, build_default_layout; "
            "print(GadgetLayout.__name__); "
            "print(build_default_layout().__class__.__name__)"
        )
        completed = self.run_import_probe(command)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("GadgetLayout", completed.stdout)

    def assert_import_does_not_load_usb_hid(self, statement: str) -> None:
        command = f"{statement}; import sys; print('USB_HID_LOADED=' + str('usb_hid' in sys.modules))"
        completed = self.run_import_probe(command)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("USB_HID_LOADED=False", completed.stdout)

    def run_import_probe(self, command: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT / "src")
        return subprocess.run(
            [sys.executable, "-c", command],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            cwd=REPO_ROOT,
            timeout=10,
        )
