import unittest
from unittest.mock import patch

from bluetooth_2_usb.ops import cli


class OpsCliTest(unittest.TestCase):
    def test_loopback_capture_forwards_unknown_harness_args_with_values(self) -> None:
        with patch(
            "bluetooth_2_usb.ops.cli.loopback_capture", return_value=0
        ) as capture:
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
            capture.call_args.args[1],
            ["--scenario", "keyboard", "--timeout-sec", "1"],
        )

    def test_loopback_inject_forwards_unknown_harness_args_with_values(self) -> None:
        with patch("bluetooth_2_usb.ops.cli.loopback_inject", return_value=0) as inject:
            exit_code = cli.main(
                [
                    "loopback-inject",
                    "--pre-delay-ms",
                    "3000",
                    "--output",
                    "json",
                ]
            )

        self.assertEqual(exit_code, 0)
        inject.assert_called_once_with(["--pre-delay-ms", "3000", "--output", "json"])
