import asyncio
import errno
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from bluetooth_2_usb.evdev import ecodes
from bluetooth_2_usb.hid.dispatch import HidDispatcher
from bluetooth_2_usb.hid.mouse_delta import MouseDelta
from bluetooth_2_usb.relay.gate import RelayGate, RelayInactiveReason
from bluetooth_2_usb.relay.input import InputRelay
from bluetooth_2_usb.relay.shortcut import ShortcutToggler
from bluetooth_2_usb.relay.supervisor import RelaySupervisor, _ActiveRelay, _SupervisorState
from bluetooth_2_usb.runtime.events import DeviceAdded, ShutdownRequested, UdcState, UdcStateChanged


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

    async def release_all(self) -> None:
        self.release_all_calls += 1
        await self.keyboard.release_all()
        await self.mouse.release_all()
        await self.consumer.release()


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
    key_down = 1
    key_hold = 2
    key_up = 0

    def __init__(self, scancode: int, keystate: int) -> None:
        self.scancode = scancode
        self.keystate = keystate


class _TestRelEvent:
    def __init__(self, code: int, value: int) -> None:
        self.event = SimpleNamespace(type=2, code=code, value=value)


class _TestSynEvent:
    type = 0
    code = 0
    value = 0


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
        seen: list[tuple[int, int]] = []
        input_device = _TestInputDevice(
            [
                _TestKeyEvent(183, _TestKeyEvent.key_down),
                _TestKeyEvent(183, _TestKeyEvent.key_up),
                _TestKeyEvent(184, _TestKeyEvent.key_down),
                _TestKeyEvent(184, _TestKeyEvent.key_up),
            ]
        )
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        def _slow_process(event) -> None:
            seen.append((event.scancode, event.keystate))

        with patch.object(relay._dispatcher, "_process_key_event", side_effect=_slow_process):
            async with relay:
                await relay.async_relay_events_loop()

        self.assertEqual(seen, [(183, 1), (183, 0), (184, 1), (184, 0)])

    async def test_aexit_ignores_ebadf_from_ungrab_on_disappeared_device(self) -> None:
        gate = _active_gate()
        input_device = _FakeGrabInputDevice(ungrab_errno=errno.EBADF)
        relay = InputRelay(input_device, _FakeHidGadgets(), grab_device=True, relay_gate=gate)

        async with relay:
            self.assertTrue(relay._currently_grabbed)

        self.assertEqual(input_device.grab_calls, 1)
        self.assertEqual(input_device.ungrab_calls, 1)
        self.assertEqual(input_device.close_calls, 0)
        self.assertFalse(relay._currently_grabbed)

    async def test_aenter_defers_grab_while_relaying_is_paused(self) -> None:
        gate = RelayGate()
        input_device = _FakeGrabInputDevice()
        relay = InputRelay(input_device, _FakeHidGadgets(), grab_device=True, relay_gate=gate)

        async with relay:
            self.assertFalse(relay._currently_grabbed)

        self.assertEqual(input_device.grab_calls, 0)
        self.assertEqual(input_device.ungrab_calls, 0)
        self.assertEqual(input_device.close_calls, 0)

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

        with patch.object(relay._dispatcher, "dispatch", new=AsyncMock()) as dispatch:
            async with relay:
                await relay.async_relay_events_loop()

        dispatch.assert_awaited_once_with(raw_event)

    async def test_handled_shortcut_runs_pause_cleanup_before_continue(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        toggler = ShortcutToggler(shortcut_keys={"KEY_F12"}, relay_gate=gate)
        input_device = _FakeGrabInputDevice(
            [_TestRelEvent(ecodes.REL_X, 5), _TestKeyEvent(88, _TestKeyEvent.key_down), _TestSynEvent()]
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

        await dispatcher.dispatch(_TestKeyEvent(88, _TestKeyEvent.key_down))

        self.assertTrue(gate.active)

    async def test_input_device_removal_stops_reader_without_failing_task_group(self) -> None:
        gate = _active_gate()
        seen: list[tuple[int, int]] = []
        input_device = _TestInputDevice(
            [_TestKeyEvent(183, _TestKeyEvent.key_down), _TestKeyEvent(183, _TestKeyEvent.key_up)],
            removal_errno=errno.ENODEV,
        )
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        def _record_process(event) -> None:
            seen.append((event.scancode, event.keystate))

        with patch.object(relay._dispatcher, "_process_key_event", side_effect=_record_process):
            async with relay:
                await relay.async_relay_events_loop()

        self.assertEqual(seen, [(183, 1), (183, 0)])

    async def test_input_device_removal_ignores_final_flush_enodev(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([], removal_errno=errno.ENODEV)
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        with patch.object(relay._dispatcher, "flush", side_effect=OSError(errno.ENODEV, "No such device")):
            async with relay:
                await relay.async_relay_events_loop()

    async def test_final_flush_enodev_without_input_removal_still_raises(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([])
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        with patch.object(relay._dispatcher, "flush", side_effect=OSError(errno.ENODEV, "No such device")):
            async with relay:
                with self.assertRaises(OSError):
                    await relay.async_relay_events_loop()

    async def test_broken_pipe_suspends_relay_gate_when_hid_write_fails(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([_TestKeyEvent(183, _TestKeyEvent.key_down)])
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        with patch.object(relay._dispatcher, "_dispatch_key_event", side_effect=BrokenPipeError()):
            async with relay:
                await relay.async_relay_events_loop()

        self.assertFalse(gate.active)
        self.assertTrue(gate.state.write_suspended)
        self.assertEqual(relay._dispatcher.write_failures, 1)

    async def test_blocked_key_write_is_dropped_after_writer_retry_is_exhausted(self) -> None:
        gate = _active_gate()
        dispatcher = HidDispatcher(_FakeHidGadgets(), gate)
        event = _TestKeyEvent(183, _TestKeyEvent.key_down)

        with patch.object(dispatcher, "_dispatch_key_event", side_effect=BlockingIOError()) as dispatch:
            await dispatcher._process_key_event(event)

        dispatch.assert_called_once_with(event)
        self.assertEqual(dispatcher.write_failures, 1)
        self.assertTrue(gate.active)

    async def test_unexpected_dispatch_error_propagates(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([_TestKeyEvent(183, _TestKeyEvent.key_down)])
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        with patch.object(relay._dispatcher, "_dispatch_key_event", side_effect=RuntimeError("dispatch bug")):
            async with relay:
                with self.assertRaisesRegex(RuntimeError, "dispatch bug"):
                    await relay.async_relay_events_loop()

    async def test_dispatch_enodev_is_not_treated_as_input_device_removal(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([_TestKeyEvent(183, _TestKeyEvent.key_down)])
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        with patch.object(relay._dispatcher, "_dispatch_key_event", side_effect=OSError(errno.ENODEV, "No device")):
            async with relay:
                with self.assertRaises(OSError):
                    await relay.async_relay_events_loop()

        self.assertTrue(gate.active)
        self.assertEqual(relay._dispatcher.write_failures, 1)

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
        input_device = _TestInputDevice([_TestRelEvent(ecodes.REL_X, 5), _TestKeyEvent(183, _TestKeyEvent.key_down)])
        hid_gadgets = _FakeHidGadgets()
        order = []

        async def _record_mouse(*args) -> None:
            order.append(("mouse", args))

        hid_gadgets.mouse.move = _record_mouse
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        def _record_key(event) -> None:
            order.append(("key", event.scancode))

        with patch.object(relay._dispatcher, "_process_key_event", side_effect=_record_key):
            async with relay:
                await relay.async_relay_events_loop()

        self.assertEqual(order, [("mouse", (5, 0, 0, 0)), ("key", 183)])

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

        await dispatcher._process_mouse_delta(MouseDelta(40000, -40000, 200, -200))

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
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, 120),
                _TestSynEvent(),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, -120),
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
                _TestRelEvent(ecodes.REL_WHEEL_HI_RES, 120),
                _TestSynEvent(),
                _TestRelEvent(ecodes.REL_WHEEL_HI_RES, -120),
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
                _TestKeyEvent(183, _TestKeyEvent.key_down),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, 60),
                _TestSynEvent(),
            ]
        )
        hid_gadgets = _FakeHidGadgets()
        relay = InputRelay(input_device, hid_gadgets, relay_gate=gate)

        def deactivate(_event) -> None:
            gate.set_host_configured(False)

        with patch.object(relay._dispatcher, "_process_key_event", side_effect=deactivate):
            async with relay:
                await relay.async_relay_events_loop()

        self.assertEqual(hid_gadgets.mouse.moves, [(5, 0, 0, 0)])


class RelaySupervisorHotplugTest(unittest.IsolatedAsyncioTestCase):
    def test_device_added_ignored_until_supervisor_is_running(self) -> None:
        supervisor = _relay_supervisor()

        supervisor._device_added("/dev/input/event7")
        supervisor._device_added("/dev/input/event7")

        self.assertEqual(supervisor._hotplug_probe_tasks, {})

        supervisor._state = _SupervisorState.RUNNING
        supervisor._schedule_hotplug_probe = Mock()

        supervisor._device_added("/dev/input/event7")

        supervisor._schedule_hotplug_probe.assert_called_once_with("/dev/input/event7")

    def test_device_removed_cancels_active_relay_while_running(self) -> None:
        supervisor = _relay_supervisor()
        task = _FakeTaskHandle()
        supervisor._state = _SupervisorState.RUNNING
        supervisor._active_relays["/dev/input/event7"] = _ActiveRelay(_FakeInputHandle(), task)

        supervisor._device_removed("/dev/input/event7")

        self.assertEqual(task.cancel_calls, 1)

    async def test_device_added_ignores_after_shutdown_requested(self) -> None:
        supervisor = _relay_supervisor()
        await supervisor._handle_runtime_event(ShutdownRequested("test"))

        supervisor._device_added("/dev/input/event7")

        self.assertEqual(supervisor._hotplug_probe_tasks, {})

    async def test_shutdown_event_cancels_active_tasks_and_closes_devices(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        supervisor = _relay_supervisor(hid_gadgets=hid_gadgets, relay_gate=gate)
        task = _FakeTaskHandle()
        device = _FakeInputHandle()
        supervisor._active_relays["/dev/input/event7"] = _ActiveRelay(device, task)
        supervisor._state = _SupervisorState.RUNNING

        await supervisor._handle_runtime_event(ShutdownRequested("test"))

        self.assertTrue(supervisor._shutdown_event.is_set())
        self.assertIs(supervisor._state, _SupervisorState.STOPPING)
        self.assertFalse(gate.active)
        self.assertEqual(hid_gadgets.release_all_calls, 1)
        self.assertEqual(task.cancel_calls, 1)
        self.assertEqual(device.close_calls, 0)
        self.assertIs(supervisor._active_relays["/dev/input/event7"].task, task)
        self.assertIs(supervisor._active_relays["/dev/input/event7"].device, device)

        task.finish()

        self.assertEqual(hid_gadgets.release_all_calls, 1)
        self.assertEqual(hid_gadgets.keyboard.release_all_calls, 1)
        self.assertEqual(hid_gadgets.mouse.release_all_calls, 1)
        self.assertEqual(hid_gadgets.consumer.release_calls, 1)

    async def test_udc_disconnect_releases_host_visible_hid_state_once(self) -> None:
        gate = RelayGate()
        hid_gadgets = _FakeHidGadgets()
        supervisor = _relay_supervisor(hid_gadgets=hid_gadgets, relay_gate=gate)
        gate.add_listener(supervisor._relay_gate_changed)

        await supervisor._handle_runtime_event(UdcStateChanged(UdcState.CONFIGURED))
        self.assertTrue(gate.active)

        await supervisor._handle_runtime_event(UdcStateChanged(UdcState.NOT_ATTACHED))
        await supervisor._handle_runtime_event(UdcStateChanged(UdcState.NOT_ATTACHED))

        self.assertFalse(gate.active)
        self.assertEqual(len(supervisor._task_group.created), 1)
        gate.remove_listener(supervisor._relay_gate_changed)

    def test_failed_scheduled_release_does_not_mark_gadgets_released(self) -> None:
        class RejectingTaskGroup:
            def create_task(self, coroutine, *, name: str):
                raise RuntimeError("closing")

        supervisor = _relay_supervisor(task_group=RejectingTaskGroup())

        supervisor._schedule_release_all_once()

        self.assertFalse(supervisor._gadgets_released)

    def test_cancel_active_relay_removes_done_task_and_closes_handle(self) -> None:
        supervisor = _relay_supervisor()
        task = _FakeTaskHandle(done=True)
        device = _FakeInputHandle()
        supervisor._active_relays["/dev/input/event7"] = _ActiveRelay(device, task)

        supervisor._cancel_active_relay("/dev/input/event7")

        self.assertEqual(task.cancel_calls, 0)
        self.assertEqual(device.close_calls, 1)
        self.assertNotIn("/dev/input/event7", supervisor._active_relays)

    def test_relay_task_done_ignores_stale_task(self) -> None:
        supervisor = _relay_supervisor()
        current_task = _FakeTaskHandle(done=True)
        stale_task = _FakeTaskHandle(done=True)
        device = _FakeInputHandle()
        supervisor._active_relays["/dev/input/event7"] = _ActiveRelay(device, current_task)

        supervisor._relay_task_done("/dev/input/event7", stale_task)

        self.assertEqual(device.close_calls, 0)
        self.assertIn("/dev/input/event7", supervisor._active_relays)

    def test_start_open_device_closes_duplicate_handle(self) -> None:
        supervisor = _relay_supervisor()
        supervisor._state = _SupervisorState.RUNNING
        active_device = _FakeInputHandle()
        duplicate_device = _FakeInputHandle()
        supervisor._active_relays["/dev/input/event7"] = _ActiveRelay(active_device, _FakeTaskHandle())

        supervisor._start_open_device(duplicate_device)

        self.assertEqual(active_device.close_calls, 0)
        self.assertEqual(duplicate_device.close_calls, 1)

    def test_schedule_hotplug_probe_creates_one_task_per_path(self) -> None:
        task = _FakeTaskHandle()
        task_group = _FakeTaskGroup(task)
        supervisor = _relay_supervisor(task_group=task_group, auto_discover=True)
        supervisor._state = _SupervisorState.RUNNING

        supervisor._schedule_hotplug_probe("/dev/input/event7")
        supervisor._schedule_hotplug_probe("/dev/input/event7")

        self.assertEqual(len(task_group.created), 1)
        self.assertEqual(task_group.created[0][1], "hotplug probe /dev/input/event7")
        self.assertIs(supervisor._hotplug_probe_tasks["/dev/input/event7"], task)

    def test_hotplug_probe_opens_matching_device_once_and_starts_relay(self) -> None:
        task = _FakeTaskHandle()
        task_group = _FakeTaskGroup(task)
        supervisor = _relay_supervisor(task_group=task_group, auto_discover=True)
        supervisor._state = _SupervisorState.RUNNING
        device = _FakeInputHandle()

        with patch("bluetooth_2_usb.relay.supervisor.InputDevice", return_value=device) as input_device:
            asyncio.run(supervisor._run_hotplug_probe("/dev/input/event7"))

        input_device.assert_called_once_with("/dev/input/event7")
        self.assertEqual(device.close_calls, 0)
        self.assertIs(supervisor._active_relays["/dev/input/event7"].device, device)
        self.assertIs(supervisor._active_relays["/dev/input/event7"].task, task)
        self.assertEqual(len(task.done_callbacks), 1)

    def test_hotplug_probe_retries_until_filters_match(self) -> None:
        supervisor = _relay_supervisor(device_identifiers=["target"])
        supervisor._state = _SupervisorState.RUNNING
        device = _FakeInputHandle(name="not ready")

        with patch("bluetooth_2_usb.relay.supervisor.InputDevice", return_value=device):
            with patch("bluetooth_2_usb.relay.supervisor.asyncio.sleep", new=AsyncMock()):
                asyncio.run(supervisor._run_hotplug_probe("/dev/input/event7"))

        self.assertEqual(device.close_calls, supervisor.HOTPLUG_ADD_MAX_RETRIES + 1)
        self.assertEqual(supervisor._active_relays, {})

    def test_device_removed_cancels_delayed_hotplug_probe(self) -> None:
        task_group = _FakeTaskGroup()
        supervisor = _relay_supervisor(task_group=task_group, device_identifiers=["target"])
        supervisor._state = _SupervisorState.RUNNING
        device = _FakeInputHandle(name="not ready")

        with patch("bluetooth_2_usb.relay.supervisor.InputDevice", return_value=device):
            supervisor._schedule_hotplug_probe("/dev/input/event7")

        supervisor._device_removed("/dev/input/event7")

        self.assertEqual(task_group.task.cancel_calls, 1)
        self.assertNotIn("/dev/input/event7", supervisor._hotplug_probe_tasks)


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
        self.assertEqual(supervisor._active_relays, {})
        self.assertIs(supervisor._state, _SupervisorState.STOPPED)

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

        supervisor = _relay_supervisor()
        device = SimpleNamespace(path="/dev/input/event7", name="failure device", close=Mock())

        with patch("bluetooth_2_usb.relay.supervisor.InputRelay", FailingInputRelay):
            with self.assertRaises(OSError) as raised:
                await supervisor._run_input_relay(device)

        self.assertEqual(raised.exception.errno, errno.EIO)
        device.close.assert_not_called()

    async def test_input_relay_disconnect_os_errors_are_not_reraised(self) -> None:
        class FailingInputRelay:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                return False

            async def async_relay_events_loop(self) -> None:
                raise OSError(errno.ENODEV, "No such device")

        supervisor = _relay_supervisor()
        device = SimpleNamespace(path="/dev/input/event7", name="removed device", close=Mock())

        with patch("bluetooth_2_usb.relay.supervisor.InputRelay", FailingInputRelay):
            await supervisor._run_input_relay(device)

        device.close.assert_not_called()

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

        supervisor = _relay_supervisor()
        device = SimpleNamespace(path="/dev/input/event7", name="failure device", close=Mock())

        with patch("bluetooth_2_usb.relay.supervisor.InputRelay", FailingInputRelay):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await supervisor._run_input_relay(device)

        device.close.assert_not_called()

    async def test_task_group_failures_are_reraised_after_logging(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()

        with patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[]):
            with self.assertRaises(ExceptionGroup) as raised:
                events: asyncio.Queue = asyncio.Queue()
                await events.put(DeviceAdded("/dev/input/event7"))
                async with asyncio.TaskGroup() as task_group:
                    supervisor = _relay_supervisor(hid_gadgets=hid_gadgets, relay_gate=gate, task_group=task_group)
                    supervisor._handle_runtime_event = Mock(side_effect=RuntimeError("boom"))
                    await supervisor.run(events)

        self.assertIsInstance(raised.exception.exceptions[0], RuntimeError)
        self.assertEqual(str(raised.exception.exceptions[0]), "boom")
        self.assertFalse(gate.active)
        self.assertEqual(hid_gadgets.release_all_calls, 1)
