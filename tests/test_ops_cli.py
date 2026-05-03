import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops import cli
from bluetooth_2_usb.ops.commands import close_log, prepare_log
from bluetooth_2_usb.ops.paths import ManagedPaths


class OpsCliTest(unittest.TestCase):
    def tearDown(self) -> None:
        close_log()

    def test_non_loopback_command_rejects_unknown_args(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            with patch("sys.stderr", new=io.StringIO()):
                cli.main(["smoketest", "--unknown"], prog="bluetooth_2_usb")

        self.assertEqual(raised.exception.code, 2)

    def test_nested_operational_commands_dispatch_correctly(self) -> None:
        with patch("bluetooth_2_usb.ops.cli.ensure_root"):
            with patch("bluetooth_2_usb.ops.cli.prepare_log"):
                with patch("bluetooth_2_usb.ops.cli.setup_persistent_bluetooth_state") as setup:
                    self.assertEqual(cli.main(["readonly", "setup", "--device", "/dev/sda1"]), 0)
                with patch("bluetooth_2_usb.ops.cli.print_readonly_status") as status:
                    self.assertEqual(cli.main(["readonly", "status"]), 0)
                with patch("bluetooth_2_usb.ops.cli.enable_readonly") as enable:
                    self.assertEqual(cli.main(["readonly", "enable"]), 0)
                with patch("bluetooth_2_usb.ops.cli.disable_readonly") as disable:
                    self.assertEqual(cli.main(["readonly", "disable"]), 0)
                with patch("bluetooth_2_usb.ops.cli.install_hid_udev_rule") as install_rule:
                    self.assertEqual(cli.main(["udev", "install"]), 0)

        setup.assert_called_once_with("/dev/sda1")
        status.assert_called_once_with()
        enable.assert_called_once_with()
        disable.assert_called_once_with()
        install_rule.assert_called_once()

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

        with patch("bluetooth_2_usb.ops.cli.ensure_root"):
            with patch("bluetooth_2_usb.ops.cli.prepare_log"):
                with patch("bluetooth_2_usb.ops.cli.SmokeTest", FakeSmokeTest):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout):
                        with patch("sys.stderr", stderr):
                            exit_code = cli.main(["smoketest", "--output", "json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().count("\n"), 1)
        self.assertEqual(json.loads(stdout.getvalue()), {"exit_code": 0, "result": "ok"})
        self.assertEqual(stderr.getvalue(), "probe text\n")

    def test_prepare_log_closes_file_and_restores_streams(self) -> None:
        with patch("bluetooth_2_usb.ops.commands.PATHS", ManagedPaths(log_dir=Path(self.id()))):
            with redirect_stdout(io.StringIO()):
                with patch("pathlib.Path.mkdir"):
                    with patch("pathlib.Path.open") as open_log:
                        log_file = open_log.return_value

                        prepare_log("test")
                        close_log()

        log_file.close.assert_called_once_with()
