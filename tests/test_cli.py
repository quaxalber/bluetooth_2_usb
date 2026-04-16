import io
import json
import signal
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from bluetooth_2_usb import cli
from bluetooth_2_usb.inventory import DeviceEnumerationError, InputDeviceMetadata


class CliTest(unittest.TestCase):
    def test_install_shutdown_signal_handlers_prefers_loop_signal_handlers(
        self,
    ) -> None:
        shutdown_event = cli.asyncio.Event()

        class _FakeLoop:
            def __init__(self) -> None:
                self.add_calls = []
                self.remove_calls = []

            def add_signal_handler(self, sig, callback, sig_name) -> None:
                self.add_calls.append((sig, callback, sig_name))

            def remove_signal_handler(self, sig) -> None:
                self.remove_calls.append(sig)

        fake_loop = _FakeLoop()

        with patch("bluetooth_2_usb.cli.signal.signal") as install_handler:
            previous_handlers, loop_handled_signals = (
                cli._install_shutdown_signal_handlers(shutdown_event, loop=fake_loop)
            )

        self.assertEqual(previous_handlers, {})
        self.assertEqual(
            loop_handled_signals,
            cli._handled_shutdown_signals(),
        )
        self.assertEqual(len(fake_loop.add_calls), len(cli._handled_shutdown_signals()))
        install_handler.assert_not_called()

        fake_loop.add_calls[1][1](fake_loop.add_calls[1][2])
        self.assertTrue(shutdown_event.is_set())

        cli._restore_signal_handlers(
            previous_handlers,
            loop_handled_signals,
            loop=fake_loop,
        )
        self.assertEqual(
            fake_loop.remove_calls,
            list(cli._handled_shutdown_signals()),
        )

    def test_install_shutdown_signal_handlers_wakes_event_loop_threadsafe(self) -> None:
        shutdown_event = cli.asyncio.Event()
        registered_handlers = {}

        class _FakeLoop:
            def __init__(self) -> None:
                self.callbacks = []

            def call_soon_threadsafe(self, callback) -> None:
                self.callbacks.append(callback)

        fake_loop = _FakeLoop()

        with patch("bluetooth_2_usb.cli.signal.getsignal", side_effect=lambda sig: sig):
            with patch(
                "bluetooth_2_usb.cli.signal.signal",
                side_effect=lambda sig, handler: registered_handlers.setdefault(
                    sig, handler
                ),
            ):
                previous_handlers, loop_handled_signals = (
                    cli._install_shutdown_signal_handlers(
                        shutdown_event, loop=fake_loop
                    )
                )

        self.assertEqual(
            set(previous_handlers),
            set(cli._handled_shutdown_signals()),
        )
        self.assertEqual(loop_handled_signals, ())

        registered_handlers[signal.SIGTERM](signal.SIGTERM, None)

        self.assertEqual(fake_loop.callbacks, [shutdown_event.set])

    def test_list_devices_error_returns_environment_exit(self) -> None:
        with patch(
            "bluetooth_2_usb.inventory.describe_input_devices",
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

        with patch(
            "bluetooth_2_usb.inventory.describe_input_devices",
            return_value=devices,
        ):
            with redirect_stdout(stdout):
                exit_code = cli.run(["--list_devices", "--output", "json"])

        self.assertEqual(exit_code, cli.EXIT_OK)
        self.assertEqual(json.loads(stdout.getvalue())[0]["path"], "/dev/input/event1")

    def test_list_devices_text_output_renders_table(self) -> None:
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
            ),
            InputDeviceMetadata(
                path="/dev/input/event2",
                name="Audio Sink",
                phys="alsa",
                uniq="",
                capabilities=[],
                relay_candidate=False,
                exclusion_reason="missing EV_KEY/EV_REL capabilities",
            ),
        ]

        with patch(
            "bluetooth_2_usb.inventory.describe_input_devices",
            return_value=devices,
        ):
            with redirect_stdout(stdout):
                exit_code = cli.run(["--list_devices"])

        rendered = stdout.getvalue()
        self.assertEqual(exit_code, cli.EXIT_OK)
        self.assertIn("Status", rendered)
        self.assertIn("Device", rendered)
        self.assertIn("Identity", rendered)
        self.assertIn("Path", rendered)
        self.assertIn("Exclusion Reason", rendered)
        self.assertIn("Keyboard", rendered)
        self.assertIn("Audio Sink", rendered)
        self.assertIn("missing EV_KEY/EV_REL", rendered)
        self.assertIn("capabilities", rendered)
