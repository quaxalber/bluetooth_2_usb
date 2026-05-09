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
OPS_CLI = "bluetooth_2_usb.ops.cli"
OPS_COMMANDS = "bluetooth_2_usb.ops.commands"
OPS_DEVICES = "bluetooth_2_usb.ops.devices"
SYS = "sys"


class OpsCliTest(unittest.TestCase):
    def tearDown(self) -> None:
        close_log()

    def test_non_loopback_command_rejects_unknown_args(self) -> None:
        with self.assertRaises(SystemExit) as raised, patch(f"{SYS}.stderr", new=io.StringIO()):
            cli.main(["smoketest", "--unknown"], prog="bluetooth_2_usb")

        self.assertEqual(raised.exception.code, 2)

    def test_readonly_setup_dispatches_device_to_workflow(self) -> None:
        with (
            patch(f"{OPS_CLI}.ensure_root"),
            patch(f"{OPS_CLI}.prepare_log"),
            patch(f"{OPS_CLI}.setup_persistent_bluetooth_state") as setup,
        ):
            self.assertEqual(cli.main(["readonly", "setup", "--device", "/dev/sda1"]), 0)

        setup.assert_called_once_with("/dev/sda1")

    def test_install_reuses_managed_venv_by_default(self) -> None:
        with patch(f"{OPS_CLI}.ensure_root"), patch(f"{OPS_CLI}.prepare_log"), patch(f"{OPS_CLI}.install") as install:
            self.assertEqual(cli.main(["install"]), 0)

        install.assert_called_once_with(recreate_venv=False)

    def test_install_recreate_venv_flag_dispatches_to_install(self) -> None:
        with patch(f"{OPS_CLI}.ensure_root"), patch(f"{OPS_CLI}.prepare_log"), patch(f"{OPS_CLI}.install") as install:
            self.assertEqual(cli.main(["install", "--recreate-venv"]), 0)

        install.assert_called_once_with(recreate_venv=True)

    def test_update_reuses_managed_venv_by_default(self) -> None:
        with patch(f"{OPS_CLI}.ensure_root"), patch(f"{OPS_CLI}.prepare_log"), patch(f"{OPS_CLI}.update") as update:
            self.assertEqual(cli.main(["update"]), 0)

        update.assert_called_once_with(recreate_venv=False)

    def test_update_recreate_venv_flag_dispatches_to_update(self) -> None:
        with patch(f"{OPS_CLI}.ensure_root"), patch(f"{OPS_CLI}.prepare_log"), patch(f"{OPS_CLI}.update") as update:
            self.assertEqual(cli.main(["update", "--recreate-venv"]), 0)

        update.assert_called_once_with(recreate_venv=True)

    def test_nested_operational_commands_dispatch_to_selected_workflow(self) -> None:
        cases = (
            (["readonly", "status"], "print_readonly_status"),
            (["readonly", "enable"], "enable_readonly"),
            (["readonly", "disable"], "disable_readonly"),
            (["readonly", "migrate"], "migrate_bluetooth_state_to_rootfs"),
            (["udev", "install"], "install_hid_udev_rule"),
        )

        for argv, target in cases:
            with self.subTest(argv=argv):
                with (
                    patch(f"{OPS_CLI}.ensure_root"),
                    patch(f"{OPS_CLI}.prepare_log"),
                    patch(f"{OPS_CLI}.{target}") as command,
                ):
                    self.assertEqual(cli.main(argv), 0)

                if argv == ["udev", "install"]:
                    command.assert_called_once_with(None)
                else:
                    command.assert_called_once()

    def test_udev_install_help_exposes_repo_root_option(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            cli.main(["udev", "install", "--help"], prog="bluetooth_2_usb")

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--repo-root REPO_ROOT", stdout.getvalue())

    def test_udev_install_dispatches_repo_root_to_host_rule_installer(self) -> None:
        with patch(f"{OPS_CLI}.ensure_root"), patch(f"{OPS_CLI}.install_hid_udev_rule") as install_rule:
            self.assertEqual(cli.main(["udev", "install", "--repo-root", str(REPO_ROOT)]), 0)

        install_rule.assert_called_once_with(REPO_ROOT.resolve())

    def test_repo_root_is_rejected(self) -> None:
        with self.assertRaises(SystemExit) as raised, patch(f"{SYS}.stderr", new=io.StringIO()):
            cli.main(["install", "--repo-root", str(REPO_ROOT)], prog="bluetooth_2_usb")

        self.assertEqual(raised.exception.code, 2)

        with self.assertRaises(SystemExit) as raised, patch(f"{SYS}.stderr", new=io.StringIO()):
            cli.main(["update", "--repo-root", str(REPO_ROOT)], prog="bluetooth_2_usb")

        self.assertEqual(raised.exception.code, 2)

    def test_smoketest_allow_non_pi_is_rejected(self) -> None:
        with self.assertRaises(SystemExit) as raised, patch(f"{SYS}.stderr", new=io.StringIO()):
            cli.main(["smoketest", "--allow-non-pi"], prog="bluetooth_2_usb")

        self.assertEqual(raised.exception.code, 2)

    def test_device_capture_routes_through_operational_cli(self) -> None:
        with patch(f"{OPS_DEVICES}.run", return_value=23) as capture:
            self.assertEqual(cli.main(["device", "capture", "--devices", "/dev/input/event1"]), 23)

        capture.assert_called_once_with(["capture", "--devices", "/dev/input/event1"])

    def test_smoketest_json_output_prints_structured_result(self) -> None:
        class FakeSmokeTest:
            def __init__(self, *, verbose: bool) -> None:
                self.verbose = verbose

            def run(self) -> int:
                print("probe text")
                return 0

            def result_dict(self) -> dict[str, object]:
                return {"exit_code": 0, "result": "ok"}

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(f"{OPS_CLI}.ensure_root"),
            patch(f"{OPS_CLI}.prepare_log"),
            patch(f"{OPS_CLI}.SmokeTest", FakeSmokeTest),
            redirect_stdout(stdout),
            patch(f"{SYS}.stderr", stderr),
        ):
            exit_code = cli.main(["smoketest", "--output", "json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"exit_code": 0, "result": "ok"})
        self.assertIn("probe text", stderr.getvalue())

    def test_prepare_log_closes_file_and_restores_streams(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = io.StringIO()
            with patch(f"{OPS_COMMANDS}.PATHS", ManagedPaths(log_dir=Path(tmpdir))), redirect_stdout(stdout):
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

    def test_hid_dispatch_import_does_not_load_gadget_manager(self) -> None:
        command = (
            "import bluetooth_2_usb.hid.dispatch; "
            "import sys; "
            "print('GADGET_MANAGER_LOADED=' + str('bluetooth_2_usb.gadgets.manager' in sys.modules))"
        )
        completed = self.run_import_probe(command)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("GADGET_MANAGER_LOADED=False", completed.stdout)

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
