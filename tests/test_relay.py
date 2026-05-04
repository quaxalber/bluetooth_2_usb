import asyncio
import errno
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from bluetooth_2_usb.evdev import KeyEvent, ecodes
from bluetooth_2_usb.hid.constants import HI_RES_WHEEL_UNITS_PER_DETENT
from bluetooth_2_usb.hid.dispatch import HidDispatcher
from bluetooth_2_usb.relay.gate import RelayGate, RelayInactiveReason
from bluetooth_2_usb.relay.input import InputRelay
from bluetooth_2_usb.relay.shortcut import ShortcutToggler
from bluetooth_2_usb.relay.supervisor import RelaySupervisor
from bluetooth_2_usb.runtime.events import DeviceAdded, DeviceRemoved, ShutdownRequested, UdcState, UdcStateChanged

UNKNOWN_KEY_CODE = 88


class _FakeKeyboard:
    def __init__(self) -> None:
        self.release_all_calls = 0
        self.presses = []
        self.releases = []

    async def release_all(self) -> None:
        self.release_all_calls += 1

    async def press(self, key_id) -> None:
        self.presses.append(key_id)

    async def release(self, key_id) -> None:
        self.releases.append(key_id)


class _FakeMouse:
    def __init__(self) -> None:
        self.release_all_calls = 0
        self.moves = []
        self.presses = []
        self.releases = []

    async def release_all(self) -> None:
        self.release_all_calls += 1

    async def move(self, x=0, y=0, wheel=0, pan=0) -> None:
        self.moves.append((x, y, wheel, pan))

    async def press(self, key_id) -> None:
        self.presses.append(key_id)

    async def release(self, key_id) -> None:
        self.releases.append(key_id)


class _FakeConsumer:
    def __init__(self) -> None:
        self.presses = []
        self.release_calls = 0

    async def press(self, key_id) -> None:
        self.presses.append(key_id)

    async def release(self) -> None:
        self.release_calls += 1


class _FakeHidGadgets:
    def __init__(self) -> None:
        self.keyboard = _FakeKeyboard()
        self.mouse = _FakeMouse()
        self.consumer = _FakeConsumer()
        self.release_all_calls = 0
        self.rebind_calls = []
        self.enable_calls = 0

    async def release_all(self) -> None:
        self.release_all_calls += 1
        await self.keyboard.release_all()
        await self.mouse.release_all()
        await self.consumer.release()

    async def rebind(self, udc_path=None, settle_sec=0.25) -> str:
        self.rebind_calls.append((udc_path, settle_sec))
        return "dummy.udc"

    async def enable(self) -> None:
        self.enable_calls += 1


class _OrderedFakeHidGadgets(_FakeHidGadgets):
    def __init__(self, order: list[tuple[str, object]]) -> None:
        super().__init__()
        self.order = order

        async def press_key(key_id) -> None:
            self.order.append(("key_down", key_id))

        async def release_key(key_id) -> None:
            self.order.append(("key_up", key_id))

        async def move_mouse(x=0, y=0, wheel=0, pan=0) -> None:
            self.order.append(("mouse", (x, y, wheel, pan)))

        self.keyboard.press = press_key
        self.keyboard.release = release_key
        self.mouse.move = move_mouse


class _FakeTaskHandle:
    def __init__(self, *, done: bool = False) -> None:
        self.cancel_calls = 0
        self._done = done
        self.done_callbacks = []

    def cancel(self) -> None:
        self.cancel_calls += 1

    def done(self) -> bool:
        return self._done

    def add_done_callback(self, callback) -> None:
        self.done_callbacks.append(callback)

    def finish(self) -> None:
        self._done = True
        for callback in list(self.done_callbacks):
            callback(self)


class _FakeTaskGroup:
    def __init__(self, task: _FakeTaskHandle | None = None) -> None:
        self.task = task or _FakeTaskHandle()
        self.created = []

    def create_task(self, coroutine, *, name: str):
        coroutine.close()
        self.created.append((coroutine, name))
        return self.task


def _relay_supervisor(**overrides):
    args = {
        "hid_gadgets": _FakeHidGadgets(),
        "relay_gate": RelayGate(),
        "task_group": _FakeTaskGroup(),
        "device_identifiers": [],
    }
    args.update(overrides)
    return RelaySupervisor(**args)


def _active_gate() -> RelayGate:
    gate = RelayGate()
    gate.set_host_configured(True)
    return gate


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition was not met")
        await asyncio.sleep(0)


class _FakeInputHandle:
    def __init__(self, path: str = "/dev/input/event7", name: str = "Fake Input") -> None:
        self.path = path
        self.name = name
        self.uniq = ""
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1

    def capabilities(self, verbose: bool = False):
        del verbose
        return {ecodes.EV_KEY: []}


class _FakeGrabInputDevice:
    def __init__(self, events=None, *, ungrab_errno: int | None = None) -> None:
        self.path = "/dev/input/event-grab"
        self.name = "grab-test-device"
        self.close_calls = 0
        self.grab_calls = 0
        self.ungrab_calls = 0
        self._events = list(events or [])
        self._ungrab_errno = ungrab_errno

    def grab(self) -> None:
        self.grab_calls += 1

    def ungrab(self) -> None:
        self.ungrab_calls += 1
        if self._ungrab_errno is not None:
            raise OSError(self._ungrab_errno, "Bad file descriptor")

    async def async_read_loop(self):
        for event in self._events:
            yield event

    def close(self) -> None:
        self.close_calls += 1


class _TestKeyEvent:
    key_down = KeyEvent.key_down
    key_hold = KeyEvent.key_hold
    key_up = KeyEvent.key_up

    def __init__(self, scancode: int, keystate: int) -> None:
        self.scancode = scancode
        self.keystate = keystate


class _TestRelEvent:
    def __init__(self, code: int, value: int) -> None:
        self.event = SimpleNamespace(type=ecodes.EV_REL, code=code, value=value)


class _TestSynEvent:
    type = ecodes.EV_SYN
    code = ecodes.SYN_REPORT
    value = ecodes.SYN_REPORT


class _TestInputDevice:
    def __init__(self, events, *, removal_errno: int | None = None) -> None:
        self.path = "/dev/input/event-test"
        self.name = "test-input-device"
        self._events = list(events)
        self._removal_errno = removal_errno

    async def async_read_loop(self):
        for event in self._events:
            yield event
        if self._removal_errno is not None:
            raise OSError(self._removal_errno, "No such device")

    def close(self) -> None:
        return None


class ShortcutTogglerTest(unittest.TestCase):
    def test_shortcut_events_are_suppressed_and_toggle_relays(self) -> None:
        gate = RelayGate()
        toggler = ShortcutToggler(shortcut_keys={"KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_F12"}, relay_gate=gate)

        make_event = lambda scancode, keystate: SimpleNamespace(scancode=scancode, keystate=keystate)

        self.assertFalse(toggler.handle_key_event(make_event(29, 1)))
        self.assertFalse(toggler.handle_key_event(make_event(42, 1)))
        self.assertTrue(toggler.handle_key_event(make_event(88, 1)))
        self.assertFalse(gate.state.user_enabled)
        self.assertTrue(toggler.handle_key_event(make_event(88, 0)))
        self.assertTrue(toggler.handle_key_event(make_event(42, 0)))
        self.assertTrue(toggler.handle_key_event(make_event(29, 0)))

        self.assertFalse(toggler.handle_key_event(make_event(29, 1)))
        self.assertFalse(toggler.handle_key_event(make_event(42, 1)))
        self.assertTrue(toggler.handle_key_event(make_event(88, 1)))
        self.assertTrue(gate.state.user_enabled)

    def test_toggle_only_changes_user_enabled_state(self) -> None:
        gate = _active_gate()
        toggler = ShortcutToggler(shortcut_keys={"KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_F12"}, relay_gate=gate)

        toggler.toggle_relaying()

        self.assertFalse(gate.active)
        self.assertFalse(gate.state.user_enabled)


class RelayGateTest(unittest.TestCase):
    def test_inactive_reasons_explain_current_gate_state(self) -> None:
        gate = RelayGate()

        self.assertEqual(gate.state.inactive_reasons, (RelayInactiveReason.HOST_NOT_CONFIGURED,))

        gate.set_user_enabled(False)
        gate.suspend_writes()

        self.assertEqual(
            gate.state.inactive_reasons,
            (
                RelayInactiveReason.HOST_NOT_CONFIGURED,
                RelayInactiveReason.USER_PAUSED,
                RelayInactiveReason.WRITE_SUSPENDED,
            ),
        )

    def test_user_pause_survives_host_reconnect(self) -> None:
        gate = _active_gate()

        gate.set_user_enabled(False)
        gate.set_host_configured(False)
        gate.set_host_configured(True)

        self.assertFalse(gate.active)
        self.assertFalse(gate.state.user_enabled)
        self.assertTrue(gate.state.host_configured)

    def test_fresh_host_configured_transition_clears_write_suspension(self) -> None:
        gate = _active_gate()
        gate.suspend_writes()

        self.assertFalse(gate.active)
        self.assertTrue(gate.state.write_suspended)

        gate.set_host_configured(False)
        gate.set_host_configured(True)

        self.assertTrue(gate.active)
        self.assertFalse(gate.state.write_suspended)

    def test_suspend_writes_reports_only_first_transition(self) -> None:
        gate = _active_gate()

        self.assertTrue(gate.suspend_writes())
        self.assertFalse(gate.suspend_writes())

        self.assertTrue(gate.state.write_suspended)

    def test_resume_writes_clears_only_write_suspension(self) -> None:
        gate = _active_gate()
        gate.suspend_writes()

        self.assertTrue(gate.resume_writes())
        self.assertFalse(gate.resume_writes())

        self.assertTrue(gate.active)
        self.assertFalse(gate.state.write_suspended)

    def test_resume_writes_does_not_override_user_pause_or_host_disconnect(self) -> None:
        gate = _active_gate()
        gate.set_user_enabled(False)
        gate.suspend_writes()

        self.assertTrue(gate.resume_writes())
        self.assertFalse(gate.active)
        self.assertFalse(gate.state.user_enabled)
        self.assertFalse(gate.state.write_suspended)

        gate = _active_gate()
        gate.set_host_configured(False)
        gate.suspend_writes()

        self.assertTrue(gate.resume_writes())
        self.assertFalse(gate.active)
        self.assertFalse(gate.state.host_configured)
        self.assertFalse(gate.state.write_suspended)

    def test_listeners_only_run_when_active_changes(self) -> None:
        gate = RelayGate()
        listener = Mock()
        gate.add_listener(listener)

        gate.set_user_enabled(False)
        gate.set_host_configured(True)
        gate.set_user_enabled(True)

        self.assertEqual(listener.call_args_list, [call(True)])


class InputRelayTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._event_type_patchers = [
            patch("bluetooth_2_usb.hid.dispatch.KeyEvent", _TestKeyEvent),
            patch("bluetooth_2_usb.hid.dispatch.RelEvent", _TestRelEvent),
            patch("bluetooth_2_usb.hid.dispatch.categorize", side_effect=lambda event: event),
        ]
        for patcher in self._event_type_patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_relay_preserves_event_order_under_slow_writer(self) -> None:
        gate = _active_gate()
        seen = []
        input_device = _TestInputDevice(
            [
                _TestKeyEvent(ecodes.KEY_A, _TestKeyEvent.key_down),
                _TestKeyEvent(ecodes.KEY_A, _TestKeyEvent.key_up),
                _TestKeyEvent(ecodes.KEY_B, _TestKeyEvent.key_down),
                _TestKeyEvent(ecodes.KEY_B, _TestKeyEvent.key_up),
            ]
        )
        relay = InputRelay(input_device, _OrderedFakeHidGadgets(seen), relay_gate=gate)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertEqual([event[0] for event in seen], ["key_down", "key_up", "key_down", "key_up"])

    async def test_aexit_ignores_ebadf_from_ungrab_on_disappeared_device(self) -> None:
        gate = _active_gate()
        input_device = _FakeGrabInputDevice(ungrab_errno=errno.EBADF)
        relay = InputRelay(input_device, _FakeHidGadgets(), grab_device=True, relay_gate=gate)

        async with relay:
            self.assertEqual(input_device.grab_calls, 1)

        self.assertEqual(input_device.grab_calls, 1)
        self.assertEqual(input_device.ungrab_calls, 1)
        self.assertEqual(input_device.close_calls, 0)

    async def test_aenter_defers_grab_while_relaying_is_paused(self) -> None:
        gate = RelayGate()
        input_device = _FakeGrabInputDevice()
        relay = InputRelay(input_device, _FakeHidGadgets(), grab_device=True, relay_gate=gate)

        async with relay:
            self.assertEqual(input_device.grab_calls, 0)

        self.assertEqual(input_device.grab_calls, 0)
        self.assertEqual(input_device.ungrab_calls, 0)
        self.assertEqual(input_device.close_calls, 0)

    async def test_unexpected_ungrab_error_preserves_grab_tracking_for_retry(self) -> None:
        gate = _active_gate()
        input_device = _FakeGrabInputDevice(ungrab_errno=errno.EIO)
        relay = InputRelay(input_device, _FakeHidGadgets(), grab_device=True, relay_gate=gate)

        async with relay:
            with self.assertLogs("bluetooth_2_usb", level="WARNING"):
                gate.set_user_enabled(False)
            gate.set_user_enabled(True)

        self.assertEqual(input_device.grab_calls, 1)
        self.assertEqual(input_device.ungrab_calls, 2)

    async def test_aexit_does_not_release_shared_gadget_state(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        relay = InputRelay(_FakeGrabInputDevice(), hid_gadgets, relay_gate=gate)

        async with relay:
            pass

        self.assertEqual(hid_gadgets.keyboard.release_all_calls, 0)
        self.assertEqual(hid_gadgets.mouse.release_all_calls, 0)
        self.assertEqual(hid_gadgets.consumer.release_calls, 0)

    async def test_input_relay_passes_raw_events_to_dispatcher(self) -> None:
        gate = _active_gate()
        raw_event = object()
        relay = InputRelay(_TestInputDevice([raw_event]), _FakeHidGadgets(), relay_gate=gate)

        with patch("bluetooth_2_usb.relay.input.HidDispatcher.dispatch", new=AsyncMock()) as dispatch:
            async with relay:
                await relay.async_relay_events_loop()

        dispatch.assert_awaited_once_with(raw_event)

    async def test_handled_shortcut_runs_pause_cleanup_before_continue(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        toggler = ShortcutToggler(shortcut_keys={"KEY_F12"}, relay_gate=gate)
        input_device = _FakeGrabInputDevice(
            [_TestRelEvent(ecodes.REL_X, 5), _TestKeyEvent(UNKNOWN_KEY_CODE, _TestKeyEvent.key_down), _TestSynEvent()]
        )
        relay = InputRelay(input_device, hid_gadgets, grab_device=True, relay_gate=gate, shortcut_toggler=toggler)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertFalse(gate.active)
        self.assertEqual(input_device.grab_calls, 1)
        self.assertEqual(input_device.ungrab_calls, 1)
        self.assertEqual(hid_gadgets.mouse.moves, [])

    async def test_shortcut_can_resume_when_relay_inactive(self) -> None:
        gate = _active_gate()
        gate.set_user_enabled(False)
        toggler = ShortcutToggler(shortcut_keys={"KEY_F12"}, relay_gate=gate)
        dispatcher = HidDispatcher(_FakeHidGadgets(), gate, toggler)

        await dispatcher.dispatch(_TestKeyEvent(UNKNOWN_KEY_CODE, _TestKeyEvent.key_down))

        self.assertTrue(gate.active)

    async def test_input_device_removal_stops_reader_without_failing_task_group(self) -> None:
        gate = _active_gate()
        seen = []
        input_device = _TestInputDevice(
            [_TestKeyEvent(ecodes.KEY_A, _TestKeyEvent.key_down), _TestKeyEvent(ecodes.KEY_A, _TestKeyEvent.key_up)],
            removal_errno=errno.ENODEV,
        )
        relay = InputRelay(input_device, _OrderedFakeHidGadgets(seen), relay_gate=gate)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertEqual([event[0] for event in seen], ["key_down", "key_up"])

    async def test_input_device_removal_ignores_final_flush_enodev(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([], removal_errno=errno.ENODEV)
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        with patch("bluetooth_2_usb.relay.input.HidDispatcher.flush", side_effect=OSError(errno.ENODEV, "No device")):
            async with relay:
                await relay.async_relay_events_loop()

    async def test_final_flush_enodev_without_input_removal_still_raises(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([])
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        with patch("bluetooth_2_usb.relay.input.HidDispatcher.flush", side_effect=OSError(errno.ENODEV, "No device")):
            async with relay:
                with self.assertRaises(OSError):
                    await relay.async_relay_events_loop()

    async def test_broken_pipe_suspends_relay_gate_when_hid_write_fails(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([_TestKeyEvent(ecodes.KEY_A, _TestKeyEvent.key_down)])
        hid_gadgets = _FakeHidGadgets()
        hid_gadgets.keyboard.press = Mock(side_effect=BrokenPipeError())
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertFalse(gate.active)
        self.assertTrue(gate.state.write_suspended)

    async def test_broken_pipe_observer_runs_for_each_failure_and_warning_logs_once(self) -> None:
        gate = _active_gate()
        observer = AsyncMock()
        dispatcher = HidDispatcher(_FakeHidGadgets(), gate, broken_pipe_observer=observer)

        with self.assertLogs("bluetooth_2_usb.hid.dispatch", level="DEBUG") as logs:
            await dispatcher._handle_broken_pipe("Key event", "first")
            await dispatcher._handle_broken_pipe("Key event", "second")

        output = "\n".join(logs.output)
        self.assertEqual(output.count("BrokenPipeError: USB cable likely disconnected or power-only"), 1)
        self.assertIn("already suspended", output)
        self.assertEqual(dispatcher.write_failures, 2)
        self.assertEqual(observer.await_count, 2)
        self.assertEqual(observer.await_args_list[0].kwargs["suspension_started"], True)
        self.assertEqual(observer.await_args_list[1].kwargs["suspension_started"], False)

    async def test_blocked_key_write_is_dropped_after_writer_retry_is_exhausted(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        hid_gadgets.keyboard.press = Mock(side_effect=BlockingIOError())
        dispatcher = HidDispatcher(hid_gadgets, gate)

        await dispatcher.dispatch(_TestKeyEvent(ecodes.KEY_A, _TestKeyEvent.key_down))

        hid_gadgets.keyboard.press.assert_called_once()
        self.assertEqual(dispatcher.write_failures, 1)
        self.assertTrue(gate.active)

    async def test_unexpected_dispatch_error_propagates(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([_TestKeyEvent(ecodes.KEY_A, _TestKeyEvent.key_down)])
        hid_gadgets = _FakeHidGadgets()
        hid_gadgets.keyboard.press = Mock(side_effect=RuntimeError("dispatch bug"))
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async with relay:
            with self.assertRaisesRegex(RuntimeError, "dispatch bug"):
                await relay.async_relay_events_loop()

    async def test_dispatch_enodev_is_not_treated_as_input_device_removal(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([_TestKeyEvent(ecodes.KEY_A, _TestKeyEvent.key_down)])
        hid_gadgets = _FakeHidGadgets()
        hid_gadgets.keyboard.press = Mock(side_effect=OSError(errno.ENODEV, "No device"))
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async with relay:
            with self.assertRaises(OSError):
                await relay.async_relay_events_loop()

        self.assertTrue(gate.active)

    async def test_relative_mouse_events_are_coalesced_until_syn_report(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_X, 2),
                _TestRelEvent(ecodes.REL_Y, -3),
                _TestRelEvent(ecodes.REL_WHEEL, 1),
                _TestRelEvent(ecodes.REL_HWHEEL, 1),
                _TestSynEvent(),
            ]
        )
        hid_gadgets = _FakeHidGadgets()
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertEqual(hid_gadgets.mouse.moves, [(2, -3, 1, 1)])

    async def test_pending_mouse_delta_flushes_before_later_key_event(self) -> None:
        gate = _active_gate()
        order = []
        input_device = _TestInputDevice(
            [_TestRelEvent(ecodes.REL_X, 5), _TestKeyEvent(ecodes.KEY_A, _TestKeyEvent.key_down)]
        )
        hid_gadgets = _OrderedFakeHidGadgets(order)
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertEqual([event[0] for event in order], ["mouse", "key_down"])
        self.assertEqual(order[0], ("mouse", (5, 0, 0, 0)))

    async def test_relative_mouse_events_log_normalized_values(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_X, 2),
                _TestRelEvent(ecodes.REL_Y, -3),
                _TestRelEvent(ecodes.REL_WHEEL_HI_RES, 60),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, -60),
                _TestSynEvent(),
            ]
        )
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        with self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs:
            async with relay:
                await relay.async_relay_events_loop()

        output = "\n".join(logs.output)
        self.assertIn("Mouse REL input: code=0 value=2 -> x=2 y=0 wheel=0.0 pan=0.0", output)
        self.assertIn("Mouse REL input: code=1 value=-3 -> x=0 y=-3 wheel=0.0 pan=0.0", output)
        self.assertIn("Mouse REL input: code=11 value=60 -> x=0 y=0 wheel=0.5 pan=0.0", output)
        self.assertIn("Mouse REL input: code=12 value=-60 -> x=0 y=0 wheel=0.0 pan=-0.5", output)

    async def test_large_mouse_deltas_are_passed_to_gadget_writer(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_X, 40000),
                _TestRelEvent(ecodes.REL_Y, -40000),
                _TestRelEvent(ecodes.REL_WHEEL, 200),
                _TestRelEvent(ecodes.REL_HWHEEL, -200),
                _TestSynEvent(),
            ]
        )
        hid_gadgets = _FakeHidGadgets()
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertEqual(hid_gadgets.mouse.moves, [(40000, -40000, 200, -200)])

    async def test_large_mouse_deltas_abort_remaining_chunks_after_broken_pipe(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        hid_gadgets.mouse.move = Mock(side_effect=BrokenPipeError())
        dispatcher = HidDispatcher(hid_gadgets, gate)

        await dispatcher.dispatch(_TestRelEvent(ecodes.REL_X, 40000))
        await dispatcher.dispatch(_TestRelEvent(ecodes.REL_Y, -40000))
        await dispatcher.dispatch(_TestRelEvent(ecodes.REL_WHEEL, 200))
        await dispatcher.dispatch(_TestRelEvent(ecodes.REL_HWHEEL, -200))
        await dispatcher.dispatch(_TestSynEvent())

        hid_gadgets.mouse.move.assert_called_once_with(40000, -40000, 200, -200)
        self.assertEqual(dispatcher.write_failures, 1)
        self.assertFalse(gate.active)

    async def test_high_resolution_horizontal_wheel_accumulates_fractional_steps(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, 60),
                _TestSynEvent(),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, 60),
                _TestSynEvent(),
            ]
        )
        hid_gadgets = _FakeHidGadgets()
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertEqual(hid_gadgets.mouse.moves, [(0, 0, 0, 1)])

    async def test_high_resolution_vertical_wheel_accumulates_fractional_steps(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_WHEEL_HI_RES, 60),
                _TestSynEvent(),
                _TestRelEvent(ecodes.REL_WHEEL_HI_RES, 60),
                _TestSynEvent(),
            ]
        )
        hid_gadgets = _FakeHidGadgets()
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertEqual(hid_gadgets.mouse.moves, [(0, 0, 1, 0)])

    async def test_high_resolution_horizontal_wheel_suppresses_low_res_fallback(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_HWHEEL, 1),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, HI_RES_WHEEL_UNITS_PER_DETENT),
                _TestSynEvent(),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, -HI_RES_WHEEL_UNITS_PER_DETENT),
                _TestRelEvent(ecodes.REL_HWHEEL, -1),
                _TestSynEvent(),
            ]
        )
        hid_gadgets = _FakeHidGadgets()
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertEqual(hid_gadgets.mouse.moves, [(0, 0, 0, 1), (0, 0, 0, -1)])

    async def test_high_resolution_vertical_wheel_suppresses_low_res_fallback(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_WHEEL, 1),
                _TestRelEvent(ecodes.REL_WHEEL_HI_RES, HI_RES_WHEEL_UNITS_PER_DETENT),
                _TestSynEvent(),
                _TestRelEvent(ecodes.REL_WHEEL_HI_RES, -HI_RES_WHEEL_UNITS_PER_DETENT),
                _TestRelEvent(ecodes.REL_WHEEL, -1),
                _TestSynEvent(),
            ]
        )
        hid_gadgets = _FakeHidGadgets()
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async with relay:
            await relay.async_relay_events_loop()

        self.assertEqual(hid_gadgets.mouse.moves, [(0, 0, 1, 0), (0, 0, -1, 0)])

    async def test_inactive_relay_discards_pending_mouse_events(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_X, 5),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, 60),
                _TestKeyEvent(ecodes.KEY_A, _TestKeyEvent.key_down),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, 60),
                _TestSynEvent(),
            ]
        )
        hid_gadgets = _FakeHidGadgets()
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        async def deactivate(_key_id) -> None:
            gate.set_host_configured(False)

        hid_gadgets.keyboard.press = deactivate

        async with relay:
            await relay.async_relay_events_loop()

        self.assertEqual(hid_gadgets.mouse.moves, [(5, 0, 0, 0)])


class RelaySupervisorHotplugTest(unittest.IsolatedAsyncioTestCase):
    async def test_hotplug_add_starts_matching_relay_and_remove_stops_it(self) -> None:
        events: asyncio.Queue = asyncio.Queue()
        relay_started = asyncio.Event()
        relay_exited = asyncio.Event()
        device = _FakeInputHandle(path="/dev/input/event7", name="target keyboard")

        class WaitingInputRelay:
            def __init__(self, input_device, *_args, **_kwargs) -> None:
                self.input_device = input_device

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                relay_exited.set()
                return False

            async def async_relay_events_loop(self) -> None:
                relay_started.set()
                await asyncio.Event().wait()

        with patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[]):
            with patch("bluetooth_2_usb.relay.supervisor.InputDevice", return_value=device):
                with patch("bluetooth_2_usb.relay.supervisor.InputRelay", WaitingInputRelay):
                    async with asyncio.TaskGroup() as task_group:
                        supervisor = _relay_supervisor(task_group=task_group, device_identifiers=["target"])
                        run_task = task_group.create_task(supervisor.run(events))
                        events.put_nowait(DeviceAdded("/dev/input/event7"))
                        await asyncio.wait_for(relay_started.wait(), timeout=1)
                        events.put_nowait(DeviceRemoved("/dev/input/event7"))
                        await asyncio.wait_for(relay_exited.wait(), timeout=1)
                        events.put_nowait(ShutdownRequested("test"))
                        await asyncio.wait_for(run_task, timeout=1)

        self.assertEqual(device.close_calls, 1)

    async def test_shutdown_request_releases_and_stops_active_relay(self) -> None:
        events: asyncio.Queue = asyncio.Queue()
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        relay_started = asyncio.Event()
        relay_exited = asyncio.Event()
        device = _FakeInputHandle(name="target keyboard")

        class WaitingInputRelay:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                relay_exited.set()
                return False

            async def async_relay_events_loop(self) -> None:
                relay_started.set()
                await asyncio.Event().wait()

        with patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[device]):
            with patch("bluetooth_2_usb.relay.supervisor.InputRelay", WaitingInputRelay):
                async with asyncio.TaskGroup() as task_group:
                    supervisor = _relay_supervisor(
                        hid_gadgets=hid_gadgets, relay_gate=gate, task_group=task_group, auto_discover=True
                    )
                    run_task = task_group.create_task(supervisor.run(events))
                    await asyncio.wait_for(relay_started.wait(), timeout=1)
                    events.put_nowait(ShutdownRequested("test"))
                    await asyncio.wait_for(relay_exited.wait(), timeout=1)
                    await asyncio.wait_for(run_task, timeout=1)

        self.assertFalse(gate.active)
        self.assertEqual(device.close_calls, 1)
        self.assertEqual(hid_gadgets.release_all_calls, 1)
        self.assertEqual(hid_gadgets.keyboard.release_all_calls, 1)
        self.assertEqual(hid_gadgets.mouse.release_all_calls, 1)
        self.assertEqual(hid_gadgets.consumer.release_calls, 1)

    async def test_udc_disconnect_releases_host_visible_hid_state(self) -> None:
        events: asyncio.Queue = asyncio.Queue()
        gate = RelayGate()
        hid_gadgets = _FakeHidGadgets()

        with patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[]):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(hid_gadgets=hid_gadgets, relay_gate=gate, task_group=task_group)
                run_task = task_group.create_task(supervisor.run(events))
                events.put_nowait(UdcStateChanged(UdcState.CONFIGURED))
                await asyncio.sleep(0)
                self.assertTrue(gate.active)
                events.put_nowait(UdcStateChanged(UdcState.NOT_ATTACHED))
                events.put_nowait(UdcStateChanged(UdcState.NOT_ATTACHED))
                events.put_nowait(ShutdownRequested("test"))
                await asyncio.wait_for(run_task, timeout=1)

        self.assertFalse(gate.active)
        self.assertEqual(hid_gadgets.release_all_calls, 1)

    async def test_user_pause_and_write_suspension_do_not_release_global_hid_state(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()

        gate.set_user_enabled(False)
        gate.suspend_writes()

        self.assertFalse(gate.active)
        self.assertEqual(hid_gadgets.release_all_calls, 0)

    async def test_broken_pipe_experiment_polling_recovers_when_udc_is_configured(self) -> None:
        events: asyncio.Queue = asyncio.Queue()
        gate = RelayGate()
        hid_gadgets = _FakeHidGadgets()

        with tempfile.TemporaryDirectory() as tmpdir:
            udc_path = Path(tmpdir) / "dummy.udc" / "state"
            udc_path.parent.mkdir()
            udc_path.write_text("configured\n", encoding="utf-8")
            log_path = Path(tmpdir) / "recovery.log"

            with (
                patch("bluetooth_2_usb.relay.supervisor.BROKEN_PIPE_EXPERIMENT_LOG_PATH", log_path),
                patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[]),
            ):
                async with asyncio.TaskGroup() as task_group:
                    supervisor = _relay_supervisor(
                        hid_gadgets=hid_gadgets,
                        relay_gate=gate,
                        task_group=task_group,
                        udc_path=udc_path,
                        broken_pipe_poll_interval_sec=0.01,
                    )
                    run_task = task_group.create_task(supervisor.run(events))
                    events.put_nowait(UdcStateChanged(UdcState.CONFIGURED))
                    await asyncio.sleep(0)

                    gate.suspend_writes()
                    await supervisor._record_broken_pipe(
                        description="Key event", context="A", write_failures=1, suspension_started=True
                    )
                    await _wait_until(lambda: gate.active and not gate.state.write_suspended)

                    events.put_nowait(ShutdownRequested("test"))
                    await asyncio.wait_for(run_task, timeout=1)

            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(
                [entry["event"] for entry in entries], ["broken_pipe", "polling_started", "polling_recovered"]
            )
            self.assertEqual(hid_gadgets.rebind_calls, [])
            self.assertEqual(hid_gadgets.enable_calls, 0)

    async def test_broken_pipe_experiment_runs_rebind_then_rebuild_after_grace_periods(self) -> None:
        events: asyncio.Queue = asyncio.Queue()
        gate = RelayGate()
        hid_gadgets = _FakeHidGadgets()

        with tempfile.TemporaryDirectory() as tmpdir:
            udc_path = Path(tmpdir) / "dummy.udc" / "state"
            udc_path.parent.mkdir()
            udc_path.write_text("not attached\n", encoding="utf-8")
            log_path = Path(tmpdir) / "recovery.log"

            with (
                patch("bluetooth_2_usb.relay.supervisor.BROKEN_PIPE_EXPERIMENT_LOG_PATH", log_path),
                patch("bluetooth_2_usb.relay.supervisor.BROKEN_PIPE_POLL_GRACE_SEC", 0.01),
                patch("bluetooth_2_usb.relay.supervisor.BROKEN_PIPE_SOFT_REBIND_WAIT_SEC", 0.01),
                patch("bluetooth_2_usb.relay.supervisor.BROKEN_PIPE_FULL_REBUILD_WAIT_SEC", 0.01),
                patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[]),
            ):
                async with asyncio.TaskGroup() as task_group:
                    supervisor = _relay_supervisor(
                        hid_gadgets=hid_gadgets,
                        relay_gate=gate,
                        task_group=task_group,
                        udc_path=udc_path,
                        broken_pipe_poll_interval_sec=0.01,
                    )
                    run_task = task_group.create_task(supervisor.run(events))
                    events.put_nowait(UdcStateChanged(UdcState.CONFIGURED))
                    await asyncio.sleep(0)

                    gate.suspend_writes()
                    await supervisor._record_broken_pipe(
                        description="Key event", context="A", write_failures=1, suspension_started=True
                    )
                    await _wait_until(lambda: hid_gadgets.enable_calls == 1)
                    await asyncio.sleep(0.03)

                    events.put_nowait(ShutdownRequested("test"))
                    await asyncio.wait_for(run_task, timeout=1)

            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            events_seen = [entry["event"] for entry in entries]
            self.assertIn("broken_pipe", events_seen)
            self.assertIn("polling_timeout", events_seen)
            self.assertIn("soft_rebind_started", events_seen)
            self.assertIn("soft_rebind_succeeded", events_seen)
            self.assertIn("soft_rebind_timeout", events_seen)
            self.assertIn("full_rebuild_started", events_seen)
            self.assertIn("full_rebuild_succeeded", events_seen)
            self.assertIn("full_rebuild_timeout", events_seen)
            self.assertEqual(len(hid_gadgets.rebind_calls), 1)
            self.assertEqual(hid_gadgets.enable_calls, 1)


class RelaySupervisorTaskGroupTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_uses_startup_handles_without_reopening(self) -> None:
        relay_ready = asyncio.Event()

        class WaitingInputRelay:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                return False

            async def async_relay_events_loop(self) -> None:
                relay_ready.set()
                await asyncio.Event().wait()

        device = _FakeInputHandle()

        with patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[device]):
            with patch(
                "bluetooth_2_usb.relay.supervisor.InputDevice",
                side_effect=AssertionError("startup device was reopened"),
            ):
                with patch("bluetooth_2_usb.relay.supervisor.InputRelay", WaitingInputRelay):
                    events: asyncio.Queue = asyncio.Queue()
                    async with asyncio.TaskGroup() as task_group:
                        supervisor = _relay_supervisor(task_group=task_group, auto_discover=True)
                        relay_task = task_group.create_task(supervisor.run(events))
                        await asyncio.wait_for(relay_ready.wait(), timeout=1)
                        events.put_nowait(ShutdownRequested("test"))
                        await asyncio.wait_for(relay_task, timeout=1)

        self.assertEqual(device.close_calls, 1)

    async def test_run_cannot_restart_after_stop(self) -> None:
        with patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[]):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(task_group=task_group, auto_discover=True)
                events: asyncio.Queue = asyncio.Queue()
                events.put_nowait(ShutdownRequested("test"))
                await supervisor.run(events)

        with self.assertRaisesRegex(RuntimeError, "cannot be restarted"):
            await supervisor.run(asyncio.Queue())

    async def test_unexpected_input_relay_os_errors_are_reraised(self) -> None:
        class FailingInputRelay:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                return False

            async def async_relay_events_loop(self) -> None:
                raise OSError(errno.EIO, "I/O error")

        device = _FakeInputHandle(name="failure device")
        with patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[device]):
            with patch("bluetooth_2_usb.relay.supervisor.InputRelay", FailingInputRelay):
                with self.assertRaises(ExceptionGroup) as raised:
                    async with asyncio.TaskGroup() as task_group:
                        supervisor = _relay_supervisor(task_group=task_group, auto_discover=True)
                        await supervisor.run(asyncio.Queue())

        error = raised.exception.exceptions[0]
        self.assertIsInstance(error, OSError)
        self.assertEqual(error.errno, errno.EIO)
        self.assertEqual(device.close_calls, 1)

    async def test_input_relay_disconnect_os_errors_are_not_reraised(self) -> None:
        relay_stopped = asyncio.Event()

        class FailingInputRelay:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                return False

            async def async_relay_events_loop(self) -> None:
                relay_stopped.set()
                raise OSError(errno.ENODEV, "No such device")

        device = _FakeInputHandle(name="removed device")
        events: asyncio.Queue = asyncio.Queue()
        with patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[device]):
            with patch("bluetooth_2_usb.relay.supervisor.InputRelay", FailingInputRelay):
                async with asyncio.TaskGroup() as task_group:
                    supervisor = _relay_supervisor(task_group=task_group, auto_discover=True)
                    run_task = task_group.create_task(supervisor.run(events))
                    await asyncio.wait_for(relay_stopped.wait(), timeout=1)
                    events.put_nowait(ShutdownRequested("test"))
                    await asyncio.wait_for(run_task, timeout=1)

        self.assertEqual(device.close_calls, 1)

    async def test_unexpected_input_relay_failures_are_reraised(self) -> None:
        class FailingInputRelay:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                return False

            async def async_relay_events_loop(self) -> None:
                raise RuntimeError("boom")

        device = _FakeInputHandle(name="failure device")
        with patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[device]):
            with patch("bluetooth_2_usb.relay.supervisor.InputRelay", FailingInputRelay):
                with self.assertRaises(ExceptionGroup) as raised:
                    async with asyncio.TaskGroup() as task_group:
                        supervisor = _relay_supervisor(task_group=task_group, auto_discover=True)
                        await supervisor.run(asyncio.Queue())

        self.assertIsInstance(raised.exception.exceptions[0], RuntimeError)
        self.assertEqual(str(raised.exception.exceptions[0]), "boom")
        self.assertEqual(device.close_calls, 1)

    async def test_task_group_failures_are_reraised_after_logging(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()

        class FailingInputRelay:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                return False

            async def async_relay_events_loop(self) -> None:
                raise RuntimeError("boom")

        device = _FakeInputHandle()
        with patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[device]):
            with patch("bluetooth_2_usb.relay.supervisor.InputRelay", FailingInputRelay):
                events: asyncio.Queue = asyncio.Queue()
                del events
                with self.assertRaises(ExceptionGroup) as raised:
                    async with asyncio.TaskGroup() as task_group:
                        supervisor = _relay_supervisor(
                            hid_gadgets=hid_gadgets, relay_gate=gate, task_group=task_group, auto_discover=True
                        )
                        await supervisor.run(asyncio.Queue())

        self.assertIsInstance(raised.exception.exceptions[0], RuntimeError)
        self.assertEqual(str(raised.exception.exceptions[0]), "boom")
        self.assertFalse(gate.active)
        self.assertEqual(hid_gadgets.release_all_calls, 1)
