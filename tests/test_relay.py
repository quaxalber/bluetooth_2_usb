import asyncio
import errno
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from bluetooth_2_usb.evdev import KeyEvent, ecodes
from bluetooth_2_usb.hid.constants import HI_RES_WHEEL_UNITS_PER_DETENT
from bluetooth_2_usb.hid.dispatch import HidDispatcher
from bluetooth_2_usb.relay.gate import RelayGate, RelayInactiveReason
from bluetooth_2_usb.relay.input import InputRelay
from bluetooth_2_usb.relay.jiggler import JigglerToggler, MouseJiggler
from bluetooth_2_usb.relay.led import KeyboardLedBlinker, resolve_led_name
from bluetooth_2_usb.relay.shortcut import ShortcutToggler
from bluetooth_2_usb.relay.supervisor import RelaySupervisor
from bluetooth_2_usb.runtime.events import DeviceAdded, DeviceRemoved, ShutdownRequested, UdcState, UdcStateChanged

UNKNOWN_KEY_CODE = 88
RELAY_SUPERVISOR = "bluetooth_2_usb.relay.supervisor"
HID_DISPATCH = "bluetooth_2_usb.hid.dispatch"
RELAY_INPUT_HIDDISPATCHER = "bluetooth_2_usb.relay.input.HidDispatcher"


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
    args = {"hid_gadgets": _FakeHidGadgets(), "relay_gate": RelayGate(), "task_group": _FakeTaskGroup(), "devices": []}
    args.update(overrides)
    return RelaySupervisor(**args)


def _active_gate() -> RelayGate:
    gate = RelayGate()
    gate.set_host_configured(True)
    return gate


class RelaySupervisorConfigTest(unittest.TestCase):
    def test_auto_relay_warns_when_explicit_device_filters_are_configured(self) -> None:
        with self.assertLogs("bluetooth_2_usb", level="WARNING") as logs:
            _relay_supervisor(auto_relay=True, devices=["keyboard"])

        self.assertTrue(any("device filters are ignored" in message for message in logs.output))


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


class _FakeLedInputDevice:
    def __init__(
        self,
        path: str = "/dev/input/event-led",
        name: str = "led-test-device",
        *,
        leds: set[int] | None = None,
        supported: bool = True,
    ) -> None:
        self.path = path
        self.name = name
        self._supported = supported
        self._leds = set(leds or ())
        self.set_led_calls: list[tuple[int, int]] = []

    def capabilities(self, verbose: bool = False):
        del verbose
        return {ecodes.EV_LED: [ecodes.LED_SCROLLL]} if self._supported else {}

    def leds(self):
        return list(self._leds)

    def set_led(self, led_num: int, value: int) -> None:
        self.set_led_calls.append((led_num, value))
        if value:
            self._leds.add(led_num)
        else:
            self._leds.discard(led_num)


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
        self.assertTrue(toggler.handle_key_event(make_event(88, 1)))  # trigger key-down is suppressed
        self.assertTrue(gate.state.user_enabled)  # toggle fires on last key-up, not key-down
        self.assertTrue(toggler.handle_key_event(make_event(88, 0)))  # trigger key-up is suppressed
        # CTRL/SHIFT key-ups were already forwarded on press, so their releases
        # must be forwarded too, instead of leaving them stuck "down" on the host.
        self.assertFalse(toggler.handle_key_event(make_event(42, 0)))
        self.assertFalse(toggler.handle_key_event(make_event(29, 0)))
        self.assertFalse(gate.state.user_enabled)  # toggle fired when last key released

        self.assertFalse(toggler.handle_key_event(make_event(29, 1)))
        self.assertFalse(toggler.handle_key_event(make_event(42, 1)))
        self.assertTrue(toggler.handle_key_event(make_event(88, 1)))
        self.assertFalse(gate.state.user_enabled)  # still waiting for key-ups
        self.assertTrue(toggler.handle_key_event(make_event(88, 0)))
        self.assertFalse(toggler.handle_key_event(make_event(42, 0)))
        self.assertFalse(toggler.handle_key_event(make_event(29, 0)))
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
            patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
            patch(f"{HID_DISPATCH}.RelEvent", _TestRelEvent),
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
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
        relay = InputRelay(input_device, _FakeHidGadgets(), grab=True, relay_gate=gate)

        async with relay:
            self.assertEqual(input_device.grab_calls, 1)

        self.assertEqual(input_device.grab_calls, 1)
        self.assertEqual(input_device.ungrab_calls, 1)
        self.assertEqual(input_device.close_calls, 0)

    async def test_aenter_defers_grab_while_relaying_is_paused(self) -> None:
        gate = RelayGate()
        input_device = _FakeGrabInputDevice()
        relay = InputRelay(input_device, _FakeHidGadgets(), grab=True, relay_gate=gate)

        async with relay:
            self.assertEqual(input_device.grab_calls, 0)

        self.assertEqual(input_device.grab_calls, 0)
        self.assertEqual(input_device.ungrab_calls, 0)
        self.assertEqual(input_device.close_calls, 0)

    async def test_unexpected_ungrab_error_preserves_grab_tracking_for_retry(self) -> None:
        gate = _active_gate()
        input_device = _FakeGrabInputDevice(ungrab_errno=errno.EIO)
        relay = InputRelay(input_device, _FakeHidGadgets(), grab=True, relay_gate=gate)

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

        with patch(f"{RELAY_INPUT_HIDDISPATCHER}.dispatch", new=AsyncMock()) as dispatch:
            async with relay:
                await relay.async_relay_events_loop()

        dispatch.assert_awaited_once_with(raw_event)

    async def test_handled_shortcut_runs_pause_cleanup_before_continue(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        toggler = ShortcutToggler(shortcut_keys={"KEY_F12"}, relay_gate=gate)
        input_device = _FakeGrabInputDevice(
            [
                _TestRelEvent(ecodes.REL_X, 5),
                _TestKeyEvent(UNKNOWN_KEY_CODE, _TestKeyEvent.key_down),
                _TestKeyEvent(UNKNOWN_KEY_CODE, _TestKeyEvent.key_up),
                _TestSynEvent(),
            ]
        )
        relay = InputRelay(input_device, hid_gadgets, grab=True, relay_gate=gate, shortcut_toggler=toggler)

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
        await dispatcher.dispatch(_TestKeyEvent(UNKNOWN_KEY_CODE, _TestKeyEvent.key_up))

        self.assertTrue(gate.active)

    async def test_shortcut_pause_forwards_final_modifier_release(self) -> None:
        # Natural usage: hold CTRL+SHIFT, tap F12, release F12 first, then the
        # modifiers. The last modifier released (CTRL) is also the event whose
        # processing flips the relay gate inactive. That release must still
        # reach the host - its press already did - or CTRL is left stuck down.
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        toggler = ShortcutToggler(shortcut_keys={"KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_F12"}, relay_gate=gate)
        dispatcher = HidDispatcher(hid_gadgets, gate, toggler)

        async def send(scancode, keystate):
            await dispatcher.dispatch(_TestKeyEvent(scancode, keystate))

        await send(ecodes.KEY_LEFTCTRL, _TestKeyEvent.key_down)
        await send(ecodes.KEY_LEFTSHIFT, _TestKeyEvent.key_down)
        await send(ecodes.KEY_F12, _TestKeyEvent.key_down)
        await send(ecodes.KEY_F12, _TestKeyEvent.key_up)
        await send(ecodes.KEY_LEFTSHIFT, _TestKeyEvent.key_up)
        await send(ecodes.KEY_LEFTCTRL, _TestKeyEvent.key_up)

        self.assertFalse(gate.active)
        self.assertEqual(len(hid_gadgets.keyboard.presses), 2)  # CTRL, SHIFT (F12 never forwarded)
        self.assertEqual(len(hid_gadgets.keyboard.releases), 2)  # both CTRL and SHIFT released

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

        with patch(f"{RELAY_INPUT_HIDDISPATCHER}.flush", side_effect=OSError(errno.ENODEV, "No device")):
            async with relay:
                await relay.async_relay_events_loop()

    async def test_final_flush_enodev_without_input_removal_still_raises(self) -> None:
        gate = _active_gate()
        input_device = _TestInputDevice([])
        relay = InputRelay(input_device, _FakeHidGadgets(), relay_gate=gate)

        with patch(f"{RELAY_INPUT_HIDDISPATCHER}.flush", side_effect=OSError(errno.ENODEV, "No device")):
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

        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[]),
            patch(f"{RELAY_SUPERVISOR}.InputDevice", return_value=device),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", WaitingInputRelay),
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(task_group=task_group, devices=["target"])
                run_task = task_group.create_task(supervisor.run(events))
                events.put_nowait(DeviceAdded("/dev/input/event7"))
                await asyncio.wait_for(relay_started.wait(), timeout=1)
                events.put_nowait(DeviceRemoved("/dev/input/event7"))
                await asyncio.wait_for(relay_exited.wait(), timeout=1)
                events.put_nowait(ShutdownRequested("test"))
                await asyncio.wait_for(run_task, timeout=1)

        self.assertEqual(device.close_calls, 1)

    async def test_device_removed_while_active_releases_host_visible_hid_state(self) -> None:
        events: asyncio.Queue = asyncio.Queue()
        hid_gadgets = _FakeHidGadgets()
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

        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[]),
            patch(f"{RELAY_SUPERVISOR}.InputDevice", return_value=device),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", WaitingInputRelay),
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(hid_gadgets=hid_gadgets, task_group=task_group, devices=["target"])
                run_task = task_group.create_task(supervisor.run(events))
                events.put_nowait(DeviceAdded("/dev/input/event7"))
                await asyncio.wait_for(relay_started.wait(), timeout=1)

                # The BT source vanishes (e.g. it switched to a different host)
                # mid-press, with no chance to relay the matching key-up.
                events.put_nowait(DeviceRemoved("/dev/input/event7"))
                await asyncio.wait_for(relay_exited.wait(), timeout=1)
                events.put_nowait(ShutdownRequested("test"))
                await asyncio.wait_for(run_task, timeout=1)

        self.assertEqual(hid_gadgets.release_all_calls, 1)
        self.assertEqual(hid_gadgets.keyboard.release_all_calls, 1)

    async def test_device_removed_for_unrelated_device_does_not_release_hid_state(self) -> None:
        events: asyncio.Queue = asyncio.Queue()
        hid_gadgets = _FakeHidGadgets()

        with patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[]):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(hid_gadgets=hid_gadgets, task_group=task_group)
                run_task = task_group.create_task(supervisor.run(events))
                events.put_nowait(DeviceRemoved("/dev/input/event-not-active"))
                events.put_nowait(ShutdownRequested("test"))
                await asyncio.wait_for(run_task, timeout=1)

        self.assertEqual(hid_gadgets.release_all_calls, 0)

    async def test_device_removed_while_another_device_still_active_does_not_release_hid_state(self) -> None:
        # Regression test: gadget state is shared across all relayed devices,
        # so proactively releasing on disconnect must not fire while another
        # device is still actively relaying - that would release keys/buttons
        # that device is legitimately holding down.
        events: asyncio.Queue = asyncio.Queue()
        hid_gadgets = _FakeHidGadgets()
        device_a = _FakeInputHandle(path="/dev/input/event7", name="keyboard-a")
        device_b = _FakeInputHandle(path="/dev/input/event8", name="keyboard-b")
        relay_started = {device_a.path: asyncio.Event(), device_b.path: asyncio.Event()}

        class WaitingInputRelay:
            def __init__(self, input_device, *_args, **_kwargs) -> None:
                self.input_device = input_device

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                return False

            async def async_relay_events_loop(self) -> None:
                relay_started[self.input_device.path].set()
                await asyncio.Event().wait()

        devices_by_path = {device_a.path: device_a, device_b.path: device_b}

        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[]),
            patch(f"{RELAY_SUPERVISOR}.InputDevice", side_effect=lambda path: devices_by_path[path]),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", WaitingInputRelay),
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(hid_gadgets=hid_gadgets, task_group=task_group, devices=["keyboard"])
                run_task = task_group.create_task(supervisor.run(events))
                events.put_nowait(DeviceAdded(device_a.path))
                events.put_nowait(DeviceAdded(device_b.path))
                await asyncio.wait_for(relay_started[device_a.path].wait(), timeout=1)
                await asyncio.wait_for(relay_started[device_b.path].wait(), timeout=1)

                # device_a vanishes while device_b is still actively relaying.
                events.put_nowait(DeviceRemoved(device_a.path))
                events.put_nowait(ShutdownRequested("test"))
                await asyncio.wait_for(run_task, timeout=1)

        self.assertEqual(hid_gadgets.release_all_calls, 0)

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

        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[device]),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", WaitingInputRelay),
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(
                    hid_gadgets=hid_gadgets, relay_gate=gate, task_group=task_group, auto_relay=True
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

        with patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[]):
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

        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[device]),
            patch(f"{RELAY_SUPERVISOR}.InputDevice", side_effect=AssertionError("startup device was reopened")),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", WaitingInputRelay),
        ):
            events: asyncio.Queue = asyncio.Queue()
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(task_group=task_group, auto_relay=True)
                relay_task = task_group.create_task(supervisor.run(events))
                await asyncio.wait_for(relay_ready.wait(), timeout=1)
                events.put_nowait(ShutdownRequested("test"))
                await asyncio.wait_for(relay_task, timeout=1)

        self.assertEqual(device.close_calls, 1)

    async def test_run_cannot_restart_after_stop(self) -> None:
        with patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[]):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(task_group=task_group, auto_relay=True)
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
        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[device]),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", FailingInputRelay),
            self.assertRaises(ExceptionGroup) as raised,
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(task_group=task_group, auto_relay=True)
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
        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[device]),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", FailingInputRelay),
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(task_group=task_group, auto_relay=True)
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
        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[device]),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", FailingInputRelay),
            self.assertRaises(ExceptionGroup) as raised,
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(task_group=task_group, auto_relay=True)
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
        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[device]),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", FailingInputRelay),
            self.assertRaises(ExceptionGroup) as raised,
        ):
            events: asyncio.Queue = asyncio.Queue()
            del events
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(
                    hid_gadgets=hid_gadgets, relay_gate=gate, task_group=task_group, auto_relay=True
                )
                await supervisor.run(asyncio.Queue())

        self.assertIsInstance(raised.exception.exceptions[0], RuntimeError)
        self.assertEqual(str(raised.exception.exceptions[0]), "boom")
        self.assertFalse(gate.active)
        self.assertEqual(hid_gadgets.release_all_calls, 1)


class MouseJigglerListenerTest(unittest.TestCase):
    def test_toggle_notifies_listeners_with_new_state(self) -> None:
        gate = _active_gate()
        jiggler = MouseJiggler(hid_gadgets=_FakeHidGadgets(), relay_gate=gate)
        seen: list[bool] = []
        jiggler.add_listener(seen.append)

        jiggler.toggle()
        jiggler.toggle()

        self.assertEqual(seen, [False, True])

    def test_removed_listener_is_not_notified(self) -> None:
        gate = _active_gate()
        jiggler = MouseJiggler(hid_gadgets=_FakeHidGadgets(), relay_gate=gate)
        seen: list[bool] = []
        jiggler.add_listener(seen.append)
        jiggler.remove_listener(seen.append)

        jiggler.toggle()

        self.assertEqual(seen, [])


class JigglerTogglerTest(unittest.TestCase):
    def test_shortcut_toggles_jiggler_on_last_key_up(self) -> None:
        gate = _active_gate()
        mouse_jiggler = MouseJiggler(hid_gadgets=_FakeHidGadgets(), relay_gate=gate)
        toggler = JigglerToggler(
            shortcut_keys={"KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_F11"}, mouse_jiggler=mouse_jiggler
        )

        make_event = lambda scancode, keystate: SimpleNamespace(scancode=scancode, keystate=keystate)

        self.assertFalse(toggler.handle_key_event(make_event(29, 1)))  # CTRL down
        self.assertFalse(toggler.handle_key_event(make_event(42, 1)))  # SHIFT down
        self.assertTrue(toggler.handle_key_event(make_event(87, 1)))  # F11 down (trigger) is suppressed
        self.assertTrue(mouse_jiggler.enabled)  # toggle fires on last key-up, not key-down
        self.assertTrue(toggler.handle_key_event(make_event(87, 0)))  # trigger key-up is suppressed
        self.assertFalse(toggler.handle_key_event(make_event(42, 0)))  # SHIFT up forwarded
        self.assertFalse(toggler.handle_key_event(make_event(29, 0)))  # CTRL up forwarded
        self.assertFalse(mouse_jiggler.enabled)  # toggled off once every key was released

    def test_retapping_a_held_modifier_does_not_double_toggle(self) -> None:
        # Regression test: JigglerToggler used to re-arm on release of *any*
        # shortcut key (not just the trigger), so releasing and re-pressing a
        # modifier while the rest of the chord was still held caused a
        # spurious second toggle.
        gate = _active_gate()
        mouse_jiggler = MouseJiggler(hid_gadgets=_FakeHidGadgets(), relay_gate=gate)
        toggler = JigglerToggler(
            shortcut_keys={"KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_F11"}, mouse_jiggler=mouse_jiggler
        )

        make_event = lambda scancode, keystate: SimpleNamespace(scancode=scancode, keystate=keystate)

        toggler.handle_key_event(make_event(29, 1))  # CTRL down
        toggler.handle_key_event(make_event(42, 1))  # SHIFT down
        toggler.handle_key_event(make_event(87, 1))  # F11 down, chord complete
        self.assertTrue(mouse_jiggler.enabled)  # not toggled yet, waiting for releases

        toggler.handle_key_event(make_event(42, 0))  # SHIFT up
        toggler.handle_key_event(make_event(42, 1))  # SHIFT down again, chord still held
        self.assertTrue(mouse_jiggler.enabled)  # must not have toggled from the bounce

        toggler.handle_key_event(make_event(87, 0))  # F11 up
        toggler.handle_key_event(make_event(42, 0))  # SHIFT up
        toggler.handle_key_event(make_event(29, 0))  # CTRL up

        self.assertFalse(mouse_jiggler.enabled)  # exactly one toggle for the whole gesture


class MouseJigglerPerformJiggleTest(unittest.IsolatedAsyncioTestCase):
    async def test_blocking_io_error_drops_jiggle_without_suspending_writes(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        hid_gadgets.mouse.move = AsyncMock(side_effect=BlockingIOError())
        jiggler = MouseJiggler(hid_gadgets=hid_gadgets, relay_gate=gate)

        await jiggler._perform_jiggle()

        self.assertFalse(gate.state.write_suspended)
        self.assertTrue(gate.active)

    async def test_broken_pipe_error_suspends_writes(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        hid_gadgets.mouse.move = AsyncMock(side_effect=BrokenPipeError())
        jiggler = MouseJiggler(hid_gadgets=hid_gadgets, relay_gate=gate)

        await jiggler._perform_jiggle()

        self.assertTrue(gate.state.write_suspended)
        self.assertFalse(gate.active)


class ResolveLedNameTest(unittest.TestCase):
    def test_resolves_known_names(self) -> None:
        self.assertEqual(resolve_led_name("caps_lock"), ecodes.LED_CAPSL)
        self.assertEqual(resolve_led_name("num_lock"), ecodes.LED_NUML)
        self.assertEqual(resolve_led_name("scroll_lock"), ecodes.LED_SCROLLL)

    def test_unknown_name_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            resolve_led_name("caps-lock")


class KeyboardLedBlinkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_blink_restores_originally_off_led_state(self) -> None:
        blinker = KeyboardLedBlinker(pulse_seconds=0, pulse_count=2)
        device = _FakeLedInputDevice()

        await blinker.blink([device])

        self.assertEqual(
            device.set_led_calls,
            [(ecodes.LED_SCROLLL, 1), (ecodes.LED_SCROLLL, 0), (ecodes.LED_SCROLLL, 1), (ecodes.LED_SCROLLL, 0)],
        )
        self.assertEqual(device.leds(), [])

    async def test_blink_restores_originally_on_led_state(self) -> None:
        blinker = KeyboardLedBlinker(pulse_seconds=0, pulse_count=1)
        device = _FakeLedInputDevice(leds={ecodes.LED_SCROLLL})

        await blinker.blink([device])

        self.assertEqual(device.set_led_calls, [(ecodes.LED_SCROLLL, 0), (ecodes.LED_SCROLLL, 1)])
        self.assertEqual(device.leds(), [ecodes.LED_SCROLLL])

    async def test_blink_skips_device_without_led_capability(self) -> None:
        blinker = KeyboardLedBlinker(pulse_seconds=0)
        device = _FakeLedInputDevice(supported=False)

        await blinker.blink([device])

        self.assertEqual(device.set_led_calls, [])

    async def test_blink_continues_after_one_device_fails(self) -> None:
        blinker = KeyboardLedBlinker(pulse_seconds=0, pulse_count=1)
        failing_device = _FakeLedInputDevice(path="/dev/input/event-fail")
        failing_device.set_led = Mock(side_effect=OSError("gone"))
        working_device = _FakeLedInputDevice(path="/dev/input/event-ok")

        await blinker.blink([failing_device, working_device])

        self.assertEqual(working_device.set_led_calls, [(ecodes.LED_SCROLLL, 1), (ecodes.LED_SCROLLL, 0)])

    async def test_cancelled_blink_restores_original_led_state(self) -> None:
        blinker = KeyboardLedBlinker(pulse_seconds=10, pulse_count=3)
        device = _FakeLedInputDevice()

        task = asyncio.create_task(blinker.blink([device]))
        for _ in range(3):
            await asyncio.sleep(0)
        self.assertEqual(device.leds(), [ecodes.LED_SCROLLL])
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(device.set_led_calls, [(ecodes.LED_SCROLLL, 1), (ecodes.LED_SCROLLL, 0)])
        self.assertEqual(device.leds(), [])

    async def test_blink_pulse_count_argument_overrides_configured_default(self) -> None:
        blinker = KeyboardLedBlinker(pulse_seconds=0, pulse_count=5)
        device = _FakeLedInputDevice()

        await blinker.blink([device], pulse_count=1)

        self.assertEqual(device.set_led_calls, [(ecodes.LED_SCROLLL, 1), (ecodes.LED_SCROLLL, 0)])


class RelaySupervisorJigglerLedTest(unittest.IsolatedAsyncioTestCase):
    async def test_jiggler_toggle_blinks_active_relayed_devices(self) -> None:
        events: asyncio.Queue = asyncio.Queue()
        hid_gadgets = _FakeHidGadgets()
        gate = _active_gate()
        mouse_jiggler = MouseJiggler(hid_gadgets=hid_gadgets, relay_gate=gate)
        led_blinker = KeyboardLedBlinker(pulse_seconds=0, pulse_count=1)
        relay_started = asyncio.Event()
        device = _FakeLedInputDevice(name="target keyboard")

        class WaitingInputRelay:
            def __init__(self, input_device, *_args, **_kwargs) -> None:
                self.input_device = input_device

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                return False

            async def async_relay_events_loop(self) -> None:
                relay_started.set()
                await asyncio.Event().wait()

        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[]),
            patch(f"{RELAY_SUPERVISOR}.InputDevice", return_value=device),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", WaitingInputRelay),
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(
                    hid_gadgets=hid_gadgets,
                    relay_gate=gate,
                    task_group=task_group,
                    devices=["target"],
                    mouse_jiggler=mouse_jiggler,
                    led_blinker=led_blinker,
                )
                run_task = task_group.create_task(supervisor.run(events))
                events.put_nowait(DeviceAdded(device.path))
                await asyncio.wait_for(relay_started.wait(), timeout=1)

                mouse_jiggler.toggle()
                await asyncio.sleep(0)
                await asyncio.sleep(0)

                events.put_nowait(ShutdownRequested("test"))
                await asyncio.wait_for(run_task, timeout=1)

        self.assertIn((ecodes.LED_SCROLLL, 1), device.set_led_calls)
        self.assertIn((ecodes.LED_SCROLLL, 0), device.set_led_calls)

    async def test_jiggler_toggle_uses_long_glow_on_enable_and_slow_blinks_on_disable(self) -> None:
        events: asyncio.Queue = asyncio.Queue()
        hid_gadgets = _FakeHidGadgets()
        gate = _active_gate()
        mouse_jiggler = MouseJiggler(hid_gadgets=hid_gadgets, relay_gate=gate)
        led_blinker = KeyboardLedBlinker()
        led_blinker.blink = AsyncMock()
        relay_started = asyncio.Event()
        device = _FakeLedInputDevice(name="target keyboard")

        class WaitingInputRelay:
            def __init__(self, input_device, *_args, **_kwargs) -> None:
                self.input_device = input_device

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                return False

            async def async_relay_events_loop(self) -> None:
                relay_started.set()
                await asyncio.Event().wait()

        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[]),
            patch(f"{RELAY_SUPERVISOR}.InputDevice", return_value=device),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", WaitingInputRelay),
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(
                    hid_gadgets=hid_gadgets,
                    relay_gate=gate,
                    task_group=task_group,
                    devices=["target"],
                    mouse_jiggler=mouse_jiggler,
                    led_blinker=led_blinker,
                )
                run_task = task_group.create_task(supervisor.run(events))
                events.put_nowait(DeviceAdded(device.path))
                await asyncio.wait_for(relay_started.wait(), timeout=1)

                mouse_jiggler.toggle()  # starts enabled, so this disables it
                await asyncio.sleep(0)
                mouse_jiggler.toggle()  # and this re-enables it
                await asyncio.sleep(0)

                events.put_nowait(ShutdownRequested("test"))
                await asyncio.wait_for(run_task, timeout=1)

        patterns = [
            (call_args.kwargs["pulse_count"], call_args.kwargs["pulse_seconds"])
            for call_args in led_blinker.blink.call_args_list
        ]
        self.assertEqual(patterns, [(3, 0.5), (1, 1.5)])

    async def test_new_jiggler_toggle_supersedes_running_blink_and_restores_led(self) -> None:
        events: asyncio.Queue = asyncio.Queue()
        hid_gadgets = _FakeHidGadgets()
        gate = _active_gate()
        mouse_jiggler = MouseJiggler(hid_gadgets=hid_gadgets, relay_gate=gate)
        led_blinker = KeyboardLedBlinker()
        relay_started = asyncio.Event()
        device = _FakeLedInputDevice(name="target keyboard")

        class WaitingInputRelay:
            def __init__(self, input_device, *_args, **_kwargs) -> None:
                self.input_device = input_device

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> bool:
                return False

            async def async_relay_events_loop(self) -> None:
                relay_started.set()
                await asyncio.Event().wait()

        with (
            patch(f"{RELAY_SUPERVISOR}.list_input_devices", return_value=[]),
            patch(f"{RELAY_SUPERVISOR}.InputDevice", return_value=device),
            patch(f"{RELAY_SUPERVISOR}.InputRelay", WaitingInputRelay),
            patch(f"{RELAY_SUPERVISOR}.JIGGLER_DISABLED_LED_PULSE_SEC", 10),
            patch(f"{RELAY_SUPERVISOR}.JIGGLER_ENABLED_LED_PULSE_SEC", 0),
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = _relay_supervisor(
                    hid_gadgets=hid_gadgets,
                    relay_gate=gate,
                    task_group=task_group,
                    devices=["target"],
                    mouse_jiggler=mouse_jiggler,
                    led_blinker=led_blinker,
                )
                run_task = task_group.create_task(supervisor.run(events))
                events.put_nowait(DeviceAdded(device.path))
                await asyncio.wait_for(relay_started.wait(), timeout=1)

                mouse_jiggler.toggle()  # disable: slow blink, now stuck mid-pulse with the LED on
                for _ in range(3):
                    await asyncio.sleep(0)
                self.assertEqual(device.leds(), [ecodes.LED_SCROLLL])

                mouse_jiggler.toggle()  # enable: must cancel the slow blink first
                for _ in range(10):
                    await asyncio.sleep(0)

                events.put_nowait(ShutdownRequested("test"))
                await asyncio.wait_for(run_task, timeout=1)

        self.assertEqual(
            device.set_led_calls,
            [
                (ecodes.LED_SCROLLL, 1),  # slow blink starts
                (ecodes.LED_SCROLLL, 0),  # restored on cancellation
                (ecodes.LED_SCROLLL, 1),  # glow
                (ecodes.LED_SCROLLL, 0),
            ],
        )
        self.assertEqual(device.leds(), [])

    async def test_jiggler_toggle_before_supervisor_running_schedules_no_blink(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        mouse_jiggler = MouseJiggler(hid_gadgets=hid_gadgets, relay_gate=gate)
        led_blinker = KeyboardLedBlinker()
        task_group = _FakeTaskGroup()
        supervisor = _relay_supervisor(
            hid_gadgets=hid_gadgets,
            relay_gate=gate,
            task_group=task_group,
            mouse_jiggler=mouse_jiggler,
            led_blinker=led_blinker,
        )
        del supervisor

        mouse_jiggler.toggle()

        self.assertEqual(task_group.created, [])
