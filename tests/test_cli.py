import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bluetooth_2_usb import cli
from bluetooth_2_usb.inventory import DeviceEnumerationError, InputDeviceMetadata
from bluetooth_2_usb.runtime import GRACEFUL_SHUTDOWN_TIMEOUT_SEC


class CliTest(unittest.TestCase):
    def test_graceful_shutdown_timeout_leaves_room_for_systemd_stop_budget(self) -> None:
        self.assertEqual(GRACEFUL_SHUTDOWN_TIMEOUT_SEC, 4.0)

    def test_list_devices_error_returns_environment_exit(self) -> None:
        with patch(
            "bluetooth_2_usb.inventory.describe_input_devices",
            side_effect=DeviceEnumerationError("denied"),
        ):
            exit_code = cli.run(["--list_devices"])

        self.assertEqual(exit_code, cli.EXIT_ENVIRONMENT)

    def test_operational_command_delegates_to_operational_cli(self) -> None:
        with patch("bluetooth_2_usb.ops.cli.main", return_value=17) as operational_main:
            exit_code = cli.run(["smoketest", "--verbose"])

        self.assertEqual(exit_code, 17)
        operational_main.assert_called_once_with(["smoketest", "--verbose"], prog="bluetooth_2_usb")

    def test_unknown_positional_command_returns_usage_without_falling_through(self) -> None:
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            exit_code = cli.run(["loopback-inject", "--help"])

        self.assertEqual(exit_code, cli.EXIT_USAGE)
        self.assertIn("Unknown command: loopback-inject", stderr.getvalue())
        self.assertIn("bluetooth_2_usb.loopback inject/capture", stderr.getvalue())

    def test_validate_env_json_output(self) -> None:
        stdout = io.StringIO()
        status = cli.EnvironmentStatus(configfs=True, udc_present=True, udc_path=None)

        with patch("bluetooth_2_usb.cli.validate_environment", return_value=status):
            with redirect_stdout(stdout):
                exit_code = cli.run(["--validate-env", "--output", "json"])

        self.assertEqual(exit_code, cli.EXIT_OK)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"configfs": True, "ok": True, "udc_path": None, "udc_present": True},
        )

    def test_list_devices_json_output(self) -> None:
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

        with patch("bluetooth_2_usb.inventory.describe_input_devices", return_value=devices):
            with redirect_stdout(stdout):
                exit_code = cli.run(["--list_devices", "--output", "json"])

        self.assertEqual(exit_code, cli.EXIT_OK)
        self.assertEqual(json.loads(stdout.getvalue())[0]["path"], "/dev/input/event1")

    def test_async_run_delegates_runtime_service_mode(self) -> None:
        runtime = AsyncMock()

        args = SimpleNamespace(
            auto_discover=False,
            debug=False,
            device_ids=[],
            grab_devices=False,
            interrupt_shortcut=None,
            list_devices=False,
            log_path="",
            log_to_file=False,
            output="text",
            validate_env=False,
            version=False,
        )
        env_status = cli.EnvironmentStatus(configfs=True, udc_present=True, udc_path=None)

        with patch("bluetooth_2_usb.cli.validate_environment", return_value=env_status):
            with patch("bluetooth_2_usb.runtime.Runtime", return_value=runtime) as runtime_cls:
                exit_code = cli.asyncio.run(cli.async_run(args))

        self.assertEqual(exit_code, cli.EXIT_OK)
        runtime_cls.assert_called_once()
        runtime.run.assert_awaited_once_with()
