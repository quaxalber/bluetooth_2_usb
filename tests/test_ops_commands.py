import io
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from bluetooth_2_usb.ops.commands import OpsError, fail_final, info, ok, ok_final, run, warn, warn_fail


class _TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class OpsCommandsTest(unittest.TestCase):
    def test_status_helpers_color_whole_line_when_tty(self) -> None:
        cases = (
            (info, "hello", "\033[36m[i] hello\033[0m\n"),
            (ok, "hello", "\033[32m[+] hello\033[0m\n"),
            (warn, "hello", "\033[33m[!] hello\033[0m\n"),
            (warn_fail, "hello", "\033[31m[!] hello\033[0m\n"),
        )

        for helper, message, expected in cases:
            with self.subTest(helper=helper.__name__):
                stdout = _TtyStringIO()
                with patch.dict("os.environ", {}, clear=True):
                    with redirect_stdout(stdout):
                        helper(message)

                self.assertEqual(stdout.getvalue(), expected)

    def test_final_helpers_are_bold(self) -> None:
        cases = (
            (ok_final, "done", "\033[1m\033[32m[+] done\033[0m\n"),
            (fail_final, "failed", "\033[1m\033[31m[!] failed\033[0m\n"),
        )

        for helper, message, expected in cases:
            with self.subTest(helper=helper.__name__):
                stdout = _TtyStringIO()
                with patch.dict("os.environ", {}, clear=True):
                    with redirect_stdout(stdout):
                        helper(message)

                self.assertEqual(stdout.getvalue(), expected)

    def test_status_helpers_skip_color_when_not_tty(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            info("hello")

        self.assertEqual(stdout.getvalue(), "[i] hello\n")

    def test_status_helpers_respect_no_color(self) -> None:
        stdout = _TtyStringIO()
        with patch.dict("os.environ", {"NO_COLOR": "1"}):
            with redirect_stdout(stdout):
                info("hello")

        self.assertEqual(stdout.getvalue(), "[i] hello\n")

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
