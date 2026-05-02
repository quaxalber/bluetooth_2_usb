import asyncio
import signal
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bluetooth_2_usb.runtime.app import Runtime, handled_shutdown_signals
from bluetooth_2_usb.runtime.config import runtime_config_from_args
from bluetooth_2_usb.runtime.events import ShutdownRequested


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
    def _runtime(self) -> Runtime:
        return Runtime(
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

    async def test_signal_handlers_request_runtime_shutdown(self) -> None:
        runtime = self._runtime()
        event_source_started = asyncio.Event()
        supervisor_started = asyncio.Event()

        class WaitingEventSource:
            def __init__(self, *_args, **_kwargs) -> None:
                self.stop_event = asyncio.Event()

            async def run(self) -> None:
                event_source_started.set()
                await self.stop_event.wait()

            def stop(self) -> None:
                self.stop_event.set()

        class RecordingSupervisor:
            shutdown_events = []

            def __init__(self, **_kwargs) -> None:
                return

            async def run(self, events) -> None:
                supervisor_started.set()
                event = await events.get()
                self.shutdown_events.append(event)

        with patch("bluetooth_2_usb.runtime.app.HidGadgets") as hid_gadgets_cls:
            hid_gadgets_cls.return_value.enable = AsyncMock()
            with patch("bluetooth_2_usb.runtime.app.RuntimeEventSource", WaitingEventSource):
                with patch("bluetooth_2_usb.runtime.app.RelaySupervisor", RecordingSupervisor):
                    task = asyncio.create_task(runtime.run())
                    await asyncio.wait_for(event_source_started.wait(), timeout=1)
                    await asyncio.wait_for(supervisor_started.wait(), timeout=1)
                    signal.raise_signal(signal.SIGTERM)
                    await asyncio.wait_for(task, timeout=1)

        self.assertEqual(RecordingSupervisor.shutdown_events, [ShutdownRequested("SIGTERM")])

    async def test_signal_fallback_does_not_require_threadsafe_loop_bridge(self) -> None:
        runtime = self._runtime()
        registered_handlers = {}
        loop = asyncio.get_running_loop()
        event_source_started = asyncio.Event()
        supervisor_started = asyncio.Event()

        class WaitingEventSource:
            def __init__(self, *_args, **_kwargs) -> None:
                self.stop_event = asyncio.Event()

            async def run(self) -> None:
                event_source_started.set()
                await self.stop_event.wait()

            def stop(self) -> None:
                self.stop_event.set()

        class RecordingSupervisor:
            shutdown_events = []

            def __init__(self, **_kwargs) -> None:
                return

            async def run(self, events) -> None:
                supervisor_started.set()
                event = await events.get()
                self.shutdown_events.append(event)

        with patch.object(loop, "add_signal_handler", side_effect=NotImplementedError):
            with patch("bluetooth_2_usb.runtime.app.signal.getsignal", side_effect=str):
                with patch(
                    "bluetooth_2_usb.runtime.app.signal.signal",
                    side_effect=lambda sig, handler: registered_handlers.setdefault(sig, handler),
                ):
                    with patch("bluetooth_2_usb.runtime.app.HidGadgets") as hid_gadgets_cls:
                        hid_gadgets_cls.return_value.enable = AsyncMock()
                        with patch("bluetooth_2_usb.runtime.app.RuntimeEventSource", WaitingEventSource):
                            with patch("bluetooth_2_usb.runtime.app.RelaySupervisor", RecordingSupervisor):
                                task = asyncio.create_task(runtime.run())
                                await asyncio.wait_for(event_source_started.wait(), timeout=1)
                                await asyncio.wait_for(supervisor_started.wait(), timeout=1)
                                self.assertEqual(set(registered_handlers), set(handled_shutdown_signals()))
                                registered_handlers[signal.SIGTERM](signal.SIGTERM, None)
                                await asyncio.wait_for(task, timeout=1)

        self.assertEqual(RecordingSupervisor.shutdown_events, [ShutdownRequested("SIGTERM")])

    async def test_runtime_awaits_hid_gadget_enable_before_starting_tasks(self) -> None:
        runtime = self._runtime()
        hid_gadgets = AsyncMock()
        observed = {}

        class CompletingEventSource:
            async def run(self) -> None:
                return

            def stop(self) -> None:
                return

        class RecordingSupervisor:
            def __init__(self, hid_gadgets, **_kwargs) -> None:
                observed["hid_gadgets"] = hid_gadgets

            async def run(self, events) -> None:
                await events.get()

        with patch("bluetooth_2_usb.runtime.app.HidGadgets", return_value=hid_gadgets):
            with patch("bluetooth_2_usb.runtime.app.RuntimeEventSource", return_value=CompletingEventSource()):
                with patch("bluetooth_2_usb.runtime.app.RelaySupervisor", RecordingSupervisor):
                    await runtime.run()

        hid_gadgets.enable.assert_awaited_once_with()
        self.assertIs(observed["hid_gadgets"], hid_gadgets)

    async def test_runtime_builds_supervisor_inside_root_task_group(self) -> None:
        class CompletingEventSource:
            def __init__(self) -> None:
                self.stop_calls = 0

            async def run(self) -> None:
                return

            def stop(self) -> None:
                self.stop_calls += 1

        class WaitingSupervisor:
            instances = []

            def __init__(self, task_group: asyncio.TaskGroup, **_kwargs) -> None:
                self.task_group = task_group
                self.child_task_created = False
                self.shutdown_events = []
                self.stop_event = asyncio.Event()
                self.instances.append(self)

            async def run(self, events) -> None:
                self.task_group.create_task(asyncio.sleep(0), name="supervisor child")
                self.child_task_created = True
                event = await events.get()
                self.shutdown_events.append(event)
                self.stop_event.set()

        runtime = self._runtime()
        event_source = CompletingEventSource()

        with patch("bluetooth_2_usb.runtime.app.HidGadgets") as hid_gadgets_cls:
            hid_gadgets_cls.return_value.enable = AsyncMock()
            with patch("bluetooth_2_usb.runtime.app.RuntimeEventSource", return_value=event_source):
                with patch("bluetooth_2_usb.runtime.app.RelaySupervisor", WaitingSupervisor):
                    await asyncio.wait_for(runtime.run(), timeout=1)

        supervisor = WaitingSupervisor.instances[0]
        self.assertTrue(supervisor.child_task_created)
        self.assertGreaterEqual(event_source.stop_calls, 1)
        self.assertTrue(supervisor.shutdown_events)
        self.assertIsInstance(supervisor.shutdown_events[0], ShutdownRequested)
