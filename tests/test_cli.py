import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bluetooth_2_usb import cli
from bluetooth_2_usb.inputs.inventory import DeviceEnumerationError, InputDeviceMetadata
from bluetooth_2_usb.runtime.app import GRACEFUL_SHUTDOWN_TIMEOUT_SEC

CLI_MODULE = "bluetooth_2_usb.cli"
INPUTS_INVENTORY = "bluetooth_2_usb.inputs.inventory"
LOOPBACK = "bluetooth_2_usb.loopback"
OPS_CLI = "bluetooth_2_usb.ops.cli"
RUNTIME_APP = "bluetooth_2_usb.runtime.app"


class CliTest(unittest.TestCase):
    def test_graceful_shutdown_timeout_leaves_room_for_systemd_stop_budget(self) -> None:
        self.assertEqual(GRACEFUL_SHUTDOWN_TIMEOUT_SEC, 4.0)

    def test_list_error_returns_environment_exit(self) -> None:
        with patch(f"{INPUTS_INVENTORY}.describe_input_devices", side_effect=DeviceEnumerationError("denied")):
            exit_code = cli.run(["--list"])

        self.assertEqual(exit_code, cli.EXIT_ENVIRONMENT)

    def test_operational_command_delegates_to_operational_cli(self) -> None:
        with patch(f"{OPS_CLI}.main", return_value=17) as operational_main:
            exit_code = cli.run(["smoketest", "--verbose"])

        self.assertEqual(exit_code, 17)
        operational_main.assert_called_once_with(["smoketest", "--verbose"], prog="bluetooth_2_usb")

    def test_loopback_command_delegates_to_loopback_cli(self) -> None:
        with patch(f"{LOOPBACK}.run", return_value=23) as loopback_run:
            exit_code = cli.run(["loopback", "inject", "--scenario", "keyboard"])

        self.assertEqual(exit_code, 23)
        loopback_run.assert_called_once_with(["inject", "--scenario", "keyboard"])

    def test_unknown_positional_command_returns_usage_without_falling_through(self) -> None:
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            exit_code = cli.run(["not-a-command", "--help"])

        self.assertEqual(exit_code, cli.EXIT_USAGE)
        self.assertIn("Unknown command: not-a-command", stderr.getvalue())
        self.assertIn("bluetooth_2_usb loopback inject/capture", stderr.getvalue())

    def test_validate_env_json_output(self) -> None:
        stdout = io.StringIO()
        status = cli.EnvironmentStatus(configfs=True, udc_present=True, udc_path=None)

        with patch(f"{CLI_MODULE}.validate_environment", return_value=status), redirect_stdout(stdout):
            exit_code = cli.run(["--validate-env", "--output", "json"])

        self.assertEqual(exit_code, cli.EXIT_OK)
        self.assertEqual(
            json.loads(stdout.getvalue()), {"configfs": True, "ok": True, "udc_path": None, "udc_present": True}
        )

    def test_get_udc_path_uses_shared_single_controller_discovery(self) -> None:
        state_path = Path("/tmp/udc-state")
        with patch(f"{CLI_MODULE}.resolve_single_udc_state_path", return_value=state_path) as resolve:
            self.assertEqual(cli.get_udc_path(), state_path)

        resolve.assert_called_once_with()

    def test_get_udc_path_treats_missing_or_ambiguous_udc_as_unavailable(self) -> None:
        for error in (FileNotFoundError("missing"), RuntimeError("multiple"), OSError("denied")):
            with (
                self.subTest(error=type(error).__name__),
                patch(f"{CLI_MODULE}.resolve_single_udc_state_path", side_effect=error),
            ):
                self.assertIsNone(cli.get_udc_path())

    def test_list_json_output(self) -> None:
        stdout = io.StringIO()
        devices = [
            InputDeviceMetadata(
                path="/dev/input/event1",
                name="Keyboard",
                phys="phys",
                uniq="",
                capabilities=["EV_KEY"],
                relay_candidate=True,
                exclusion_reason=None,
            )
        ]

        with patch(f"{INPUTS_INVENTORY}.describe_input_devices", return_value=devices), redirect_stdout(stdout):
            exit_code = cli.run(["--list", "--output", "json"])

        self.assertEqual(exit_code, cli.EXIT_OK)
        self.assertEqual(json.loads(stdout.getvalue())[0]["path"], "/dev/input/event1")

    def test_async_run_delegates_runtime_service_mode(self) -> None:
        runtime = AsyncMock()

        args = SimpleNamespace(
            auto=False,
            debug=False,
            devices=[],
            grab=False,
            shortcut=None,
            list=False,
            output="text",
            validate_env=False,
            version=False,
        )
        env_status = cli.EnvironmentStatus(configfs=True, udc_present=True, udc_path=None)

        with (
            patch(f"{CLI_MODULE}.validate_environment", return_value=env_status),
            patch(f"{RUNTIME_APP}.Runtime", return_value=runtime) as runtime_cls,
        ):
            exit_code = cli.asyncio.run(cli.async_run(args))

        self.assertEqual(exit_code, cli.EXIT_OK)
        runtime_cls.assert_called_once()
        runtime.run.assert_awaited_once_with()
