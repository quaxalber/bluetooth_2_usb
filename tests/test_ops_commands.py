import subprocess
import unittest
from unittest.mock import patch

from bluetooth_2_usb.ops.commands import OpsError, run


class OpsCommandsTest(unittest.TestCase):
    def test_run_normalizes_missing_command(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError("missing")):
            with self.assertRaises(OpsError) as raised:
                run(["missing-command"])

        self.assertIn("Required command not found", str(raised.exception))

    def test_run_normalizes_timeout(self) -> None:
        timeout = subprocess.TimeoutExpired(["slow-command"], timeout=2, output="partial stdout")

        with patch("subprocess.run", side_effect=timeout):
            with self.assertRaises(OpsError) as raised:
                run(["slow-command"], timeout=2)

        self.assertIn("Command timed out after 2s", str(raised.exception))
        self.assertIn("partial stdout", str(raised.exception))
