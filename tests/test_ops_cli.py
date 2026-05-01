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

    def test_loopback_capture_forwards_unknown_loopback_args_with_values(self) -> None:
        with patch("bluetooth_2_usb.ops.cli.loopback_capture", return_value=0) as capture:
            exit_code = cli.main(
                [
                    "loopback-capture",
                    "--repo-root",
                    "/tmp/repo",
                    "--scenario",
                    "keyboard",
                    "--timeout-sec",
                    "1",
                ]
            )

        self.assertEqual(exit_code, 0)
        capture.assert_called_once()
        self.assertEqual(
            capture.call_args.args[1], ["--scenario", "keyboard", "--timeout-sec", "1"]
        )

    def test_loopback_inject_forwards_unknown_loopback_args_with_values(self) -> None:
        with patch("bluetooth_2_usb.ops.cli.loopback_inject", return_value=0) as inject:
            exit_code = cli.main(["loopback-inject", "--pre-delay-ms", "3000", "--output", "json"])

        self.assertEqual(exit_code, 0)
        inject.assert_called_once_with(["--pre-delay-ms", "3000", "--output", "json"])

    def test_non_loopback_command_rejects_unknown_args(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            with patch("sys.stderr", new=io.StringIO()):
                cli.main(["smoketest", "--unknown"], prog="bluetooth_2_usb")

        self.assertEqual(raised.exception.code, 2)

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
