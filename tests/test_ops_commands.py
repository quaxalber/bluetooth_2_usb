import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops.artifacts import make_user_copyable
from bluetooth_2_usb.ops.commands import OpsError, fail_final, info, ok, ok_final, run, warn, warn_fail

OPS_ARTIFACTS_OS = "bluetooth_2_usb.ops.artifacts.os"
OS_ENVIRON = "os.environ"
SUBPROCESS = "subprocess"


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
                with patch.dict(OS_ENVIRON, {}, clear=True), redirect_stdout(stdout):
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
                with patch.dict(OS_ENVIRON, {}, clear=True), redirect_stdout(stdout):
                    helper(message)

                self.assertEqual(stdout.getvalue(), expected)

    def test_status_helpers_skip_color_when_not_tty(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            info("hello")

        self.assertEqual(stdout.getvalue(), "[i] hello\n")

    def test_status_helpers_respect_no_color(self) -> None:
        stdout = _TtyStringIO()
        with patch.dict(OS_ENVIRON, {"NO_COLOR": "1"}), redirect_stdout(stdout):
            info("hello")

        self.assertEqual(stdout.getvalue(), "[i] hello\n")

    def test_make_user_copyable_chowns_sudo_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "artifact.md"
            path.write_text("payload", encoding="utf-8")

            with (
                patch.dict(OS_ENVIRON, {"SUDO_UID": "123", "SUDO_GID": "456"}),
                patch(f"{OPS_ARTIFACTS_OS}.chown") as chown,
            ):
                make_user_copyable(path)

            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            chown.assert_called_once_with(path, 123, 456)

    def test_make_user_copyable_warns_but_does_not_raise_when_chown_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "artifact.md"
            path.write_text("payload", encoding="utf-8")
            stdout = io.StringIO()

            with (
                patch.dict(OS_ENVIRON, {"SUDO_UID": "123", "SUDO_GID": "456"}),
                patch(f"{OPS_ARTIFACTS_OS}.chown", side_effect=PermissionError("denied")),
                redirect_stdout(stdout),
            ):
                make_user_copyable(path)

            self.assertIn("Could not chown", stdout.getvalue())

    def test_run_normalizes_missing_command(self) -> None:
        with (
            patch(f"{SUBPROCESS}.run", side_effect=FileNotFoundError("missing")),
            self.assertRaises(OpsError) as raised,
        ):
            run(["missing-command"])

        self.assertIn("Required command not found", str(raised.exception))

    def test_run_normalizes_timeout(self) -> None:
        timeout = subprocess.TimeoutExpired(["slow-command"], timeout=2, output="partial stdout")

        with patch(f"{SUBPROCESS}.run", side_effect=timeout), self.assertRaises(OpsError) as raised:
            run(["slow-command"], timeout=2)

        self.assertIn("Command timed out after 2s", str(raised.exception))
        self.assertIn("partial stdout", str(raised.exception))
