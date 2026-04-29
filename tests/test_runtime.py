import asyncio
import signal
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bluetooth_2_usb.runtime import (
    Runtime,
    _handled_shutdown_signals,
)
from bluetooth_2_usb.runtime_config import runtime_config_from_args
from bluetooth_2_usb.runtime_events import ShutdownRequested


class RuntimeConfigTest(unittest.TestCase):
    def test_runtime_config_from_args_normalizes_mutable_cli_values(self) -> None:
        args = SimpleNamespace(
            auto_discover=True,
            debug=False,
            device_ids=["/dev/input/event7"],
            grab_devices=True,
            interrupt_shortcut=["KEY_LEFTCTRL", "KEY_F12"],
            log_path="/tmp/b2u.log",
            log_to_file=True,
        )

        config = runtime_config_from_args(args, udc_path=Path("/tmp/udc-state"))

        self.assertEqual(config.device_ids, ("/dev/input/event7",))
        self.assertEqual(config.interrupt_shortcut, ("KEY_LEFTCTRL", "KEY_F12"))
        self.assertEqual(config.udc_path, Path("/tmp/udc-state"))


class RuntimeSignalTest(unittest.IsolatedAsyncioTestCase):
    async def test_signal_handlers_enqueue_shutdown_events_in_running_loop(
        self,
    ) -> None:
        runtime = Runtime(
            runtime_config_from_args(
                SimpleNamespace(
                    auto_discover=False,
                    debug=False,
                    device_ids=[],
                    grab_devices=False,
                    interrupt_shortcut=[],
                    log_path="",
                    log_to_file=False,
                ),
                udc_path=None,
            )
        )

        handlers = runtime._install_signal_handlers()
        try:
            for _handled_signal in _handled_shutdown_signals():
                signal.raise_signal(_handled_signal)
                event = await asyncio.wait_for(runtime._events.get(), timeout=1)
                self.assertEqual(
                    event,
                    ShutdownRequested(signal.Signals(_handled_signal).name),
                )
        finally:
            runtime._restore_signal_handlers(handlers)

    async def test_signal_fallback_does_not_require_threadsafe_loop_bridge(
        self,
    ) -> None:
        runtime = Runtime(
            runtime_config_from_args(
                SimpleNamespace(
                    auto_discover=False,
                    debug=False,
                    device_ids=[],
                    grab_devices=False,
                    interrupt_shortcut=[],
                    log_path="",
                    log_to_file=False,
                ),
                udc_path=None,
            )
        )
        registered_handlers = {}
        loop = asyncio.get_running_loop()

        with patch.object(loop, "add_signal_handler", side_effect=NotImplementedError):
            with patch("bluetooth_2_usb.runtime.signal.getsignal", side_effect=str):
                with patch(
                    "bluetooth_2_usb.runtime.signal.signal",
                    side_effect=lambda sig, handler: registered_handlers.setdefault(
                        sig,
                        handler,
                    ),
                ):
                    handlers = runtime._install_signal_handlers()

        try:
            self.assertEqual(set(registered_handlers), set(_handled_shutdown_signals()))
            registered_handlers[signal.SIGTERM](signal.SIGTERM, None)
            self.assertEqual(
                await asyncio.wait_for(runtime._events.get(), timeout=1),
                ShutdownRequested("SIGTERM"),
            )
        finally:
            with patch("bluetooth_2_usb.runtime.signal.signal"):
                runtime._restore_signal_handlers(handlers)
