import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from bluetooth_2_usb import cli
from bluetooth_2_usb.inventory import DeviceEnumerationError, InputDeviceMetadata


class CliTest(unittest.TestCase):
    def test_list_devices_error_returns_environment_exit(self) -> None:
        with patch(
            "bluetooth_2_usb.cli.describe_input_devices",
            side_effect=DeviceEnumerationError("denied"),
        ):
            exit_code = cli.run(["--list_devices"])

        self.assertEqual(exit_code, cli.EXIT_ENVIRONMENT)

    def test_validate_env_json_output(self) -> None:
        stdout = io.StringIO()
        status = cli.EnvironmentStatus(configfs=True, udc_present=True, udc_path=None)

        with patch("bluetooth_2_usb.cli.validate_environment", return_value=status):
            with redirect_stdout(stdout):
                exit_code = cli.run(["--validate-env", "--output", "json"])

        self.assertEqual(exit_code, cli.EXIT_OK)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "configfs": True,
                "ok": True,
                "udc_path": None,
                "udc_present": True,
            },
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

        with patch("bluetooth_2_usb.cli.describe_input_devices", return_value=devices):
            with redirect_stdout(stdout):
                exit_code = cli.run(["--list_devices", "--output", "json"])

        self.assertEqual(exit_code, cli.EXIT_OK)
        self.assertEqual(json.loads(stdout.getvalue())[0]["path"], "/dev/input/event1")
