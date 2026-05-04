import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from bluetooth_2_usb.evdev import KeyEvent, ecodes
from bluetooth_2_usb.hid.buttons import MouseButtons
from bluetooth_2_usb.hid.constants import MOUSE_IN_REPORT_LENGTH
from bluetooth_2_usb.hid.consumer import ExtendedConsumerControl
from bluetooth_2_usb.hid.dispatch import HidDispatcher
from bluetooth_2_usb.hid.keyboard import ExtendedKeyboard
from bluetooth_2_usb.hid.mouse import ExtendedMouse
from bluetooth_2_usb.relay.gate import RelayGate

NUL = 0x00
NO_BUTTONS = NUL
NO_MOVE = (NUL, NUL, NUL, NUL, NUL, NUL)
HID_I16_MAX = 32767
HID_I16_MIN = -32767
HID_I8_MAX = 127
HID_I8_MIN = -127


def _mouse_report(buttons: int = NO_BUTTONS, x: int = 0, y: int = 0, wheel: int = 0, pan: int = 0) -> bytes:
    return bytes(
        [
            buttons,
            *x.to_bytes(2, "little", signed=True),
            *y.to_bytes(2, "little", signed=True),
            wheel & 0xFF,
            pan & 0xFF,
        ]
    )


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


def _active_gate() -> RelayGate:
    gate = RelayGate()
    gate.set_host_configured(True)
    return gate


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


class ExtendedKeyboardTest(unittest.IsolatedAsyncioTestCase):
    async def test_press_release_and_release_all_do_not_sleep(self) -> None:
        keyboard_device = Mock()

        with (
            patch("adafruit_hid.keyboard.Keyboard", return_value=keyboard_device),
            patch("bluetooth_2_usb.hid.keyboard.asyncio.sleep") as sleep,
        ):
            keyboard = ExtendedKeyboard(devices=[])
            await keyboard.press(1)
            await keyboard.release(1)
            await keyboard.release_all()

        keyboard_device.press.assert_called_once_with(1)
        keyboard_device.release.assert_called_once_with(1)
        keyboard_device.release_all.assert_called_once_with()
        sleep.assert_not_called()

    async def test_press_retries_blocked_write(self) -> None:
        keyboard_device = Mock()
        keyboard_device.press.side_effect = [BlockingIOError(), None]

        with (
            patch("adafruit_hid.keyboard.Keyboard", return_value=keyboard_device),
            patch("bluetooth_2_usb.hid.keyboard.asyncio.sleep") as sleep,
        ):
            keyboard = ExtendedKeyboard(devices=[])
            await keyboard.press(1)

        self.assertEqual(keyboard_device.press.mock_calls, [call(1), call(1)])
        sleep.assert_called_once_with(keyboard.REPORT_WRITE_RETRY_DELAY_SEC)

    async def test_release_raises_after_retry_budget_is_exhausted(self) -> None:
        keyboard_device = Mock()
        keyboard_device.release.side_effect = BlockingIOError()

        with (
            patch("adafruit_hid.keyboard.Keyboard", return_value=keyboard_device),
            patch("bluetooth_2_usb.hid.keyboard.asyncio.sleep") as sleep,
        ):
            keyboard = ExtendedKeyboard(devices=[])
            with self.assertRaises(BlockingIOError):
                await keyboard.release(1)

        self.assertEqual(keyboard_device.release.mock_calls, [call(1)] * keyboard.REPORT_WRITE_MAX_TRIES)
        self.assertEqual(
            sleep.mock_calls, [call(keyboard.REPORT_WRITE_RETRY_DELAY_SEC)] * (keyboard.REPORT_WRITE_MAX_TRIES - 1)
        )


class ExtendedConsumerControlTest(unittest.IsolatedAsyncioTestCase):
    async def test_press_and_release_delegate_without_sleep(self) -> None:
        consumer_device = Mock()

        with (
            patch("adafruit_hid.consumer_control.ConsumerControl", return_value=consumer_device),
            patch("bluetooth_2_usb.hid.consumer.asyncio.sleep") as sleep,
        ):
            consumer = ExtendedConsumerControl(devices=[])
            await consumer.press(1)
            await consumer.release()

        consumer_device.press.assert_called_once_with(1)
        consumer_device.release.assert_called_once_with()
        sleep.assert_not_called()

    async def test_press_retries_blocked_write(self) -> None:
        consumer_device = Mock()
        consumer_device.press.side_effect = [BlockingIOError(), None]

        with (
            patch("adafruit_hid.consumer_control.ConsumerControl", return_value=consumer_device),
            patch("bluetooth_2_usb.hid.consumer.asyncio.sleep") as sleep,
        ):
            consumer = ExtendedConsumerControl(devices=[])
            await consumer.press(1)

        self.assertEqual(consumer_device.press.mock_calls, [call(1), call(1)])
        sleep.assert_called_once_with(consumer.REPORT_WRITE_RETRY_DELAY_SEC)

    async def test_release_raises_after_retry_budget_is_exhausted(self) -> None:
        consumer_device = Mock()
        consumer_device.release.side_effect = BlockingIOError()

        with (
            patch("adafruit_hid.consumer_control.ConsumerControl", return_value=consumer_device),
            patch("bluetooth_2_usb.hid.consumer.asyncio.sleep") as sleep,
        ):
            consumer = ExtendedConsumerControl(devices=[])
            with self.assertRaises(BlockingIOError):
                await consumer.release()

        self.assertEqual(consumer_device.release.mock_calls, [call()] * consumer.REPORT_WRITE_MAX_TRIES)
        self.assertEqual(
            sleep.mock_calls, [call(consumer.REPORT_WRITE_RETRY_DELAY_SEC)] * (consumer.REPORT_WRITE_MAX_TRIES - 1)
        )


class ExtendedMouseTest(unittest.IsolatedAsyncioTestCase):
    async def test_button_reports_do_not_sleep(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with (
            patch("adafruit_hid.find_device", return_value=device),
            patch("bluetooth_2_usb.hid.mouse.asyncio.sleep") as sleep,
        ):
            mouse = ExtendedMouse(devices=[])
            await mouse.press(MouseButtons.LEFT)
            await mouse.release(MouseButtons.LEFT)
            await mouse.release_all()

        self.assertEqual(device.sent, [_mouse_report(MouseButtons.LEFT), _mouse_report(), _mouse_report()])
        sleep.assert_not_called()

    async def test_move_uses_16_bit_xy_and_8_bit_wheel_pan(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            await mouse.move(x=300, y=-300, wheel=1, pan=-1)

        self.assertEqual(device.sent, [_mouse_report(x=300, y=-300, wheel=1, pan=-1)])

    async def test_move_accumulates_fractional_pan_across_calls(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            await mouse.move(pan=0.5)
            await mouse.move(pan=0.5)
            await mouse.move(pan=-0.5)
            await mouse.move(pan=-0.5)

        self.assertEqual(device.sent, [_mouse_report(pan=1), _mouse_report(pan=-1)])

    async def test_move_accumulates_fractional_wheel_across_calls(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            await mouse.move(wheel=0.5)
            await mouse.move(wheel=0.5)
            await mouse.move(wheel=-0.5)
            await mouse.move(wheel=-0.5)

        self.assertEqual(device.sent, [_mouse_report(wheel=1), _mouse_report(wheel=-1)])

    async def test_move_splits_large_xy_without_widening_wheel_pan(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            await mouse.move(x=40000, y=-40000, wheel=200, pan=-200)

        self.assertEqual(
            device.sent,
            [
                _mouse_report(x=HID_I16_MAX, y=HID_I16_MIN, wheel=HID_I8_MAX, pan=HID_I8_MIN),
                _mouse_report(x=7233, y=-7233, wheel=73, pan=-73),
            ],
        )

    async def test_move_chunks_large_reports_without_sleep(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with (
            patch("adafruit_hid.find_device", return_value=device),
            patch("bluetooth_2_usb.hid.mouse.asyncio.sleep") as sleep,
        ):
            mouse = ExtendedMouse(devices=[])
            await mouse.move(x=40000)
            await mouse.move(x=1)

        sleep.assert_not_called()
        self.assertEqual(device.sent, [_mouse_report(x=HID_I16_MAX), _mouse_report(x=7233), _mouse_report(x=1)])

    async def test_move_retries_blocked_report_before_advancing(self) -> None:
        device = SimpleNamespace(sent=[])
        attempts = []

        def send_report(report) -> None:
            attempts.append(bytes(report))
            if len(attempts) == 1:
                raise BlockingIOError()
            device.sent.append(bytes(report))

        device.send_report = send_report

        with (
            patch("adafruit_hid.find_device", return_value=device),
            patch("bluetooth_2_usb.hid.mouse.asyncio.sleep") as sleep,
        ):
            mouse = ExtendedMouse(devices=[])
            await mouse.move(x=1)

        expected_report = _mouse_report(x=1)
        self.assertEqual(attempts, [expected_report, expected_report])
        self.assertEqual(device.sent, [expected_report])
        sleep.assert_called_once_with(mouse.REPORT_WRITE_RETRY_DELAY_SEC)

    async def test_move_raises_after_report_retry_budget_is_exhausted(self) -> None:
        device = SimpleNamespace(attempts=[])

        def send_report(report) -> None:
            device.attempts.append(bytes(report))
            raise BlockingIOError()

        device.send_report = send_report

        with (
            patch("adafruit_hid.find_device", return_value=device),
            patch("bluetooth_2_usb.hid.mouse.asyncio.sleep") as sleep,
        ):
            mouse = ExtendedMouse(devices=[])
            with self.assertRaises(BlockingIOError):
                await mouse.move(x=1)

        expected_report = _mouse_report(x=1)
        self.assertEqual(device.attempts, [expected_report] * mouse.REPORT_WRITE_MAX_TRIES)
        self.assertEqual(
            sleep.mock_calls, [call(mouse.REPORT_WRITE_RETRY_DELAY_SEC)] * (mouse.REPORT_WRITE_MAX_TRIES - 1)
        )

    async def test_move_debug_logs_reports_sent_to_gadget(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            with self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs:
                await mouse.move(x=40000, y=-40000, wheel=200, pan=-200)

        self.assertEqual(len(device.sent), 2)
        self.assertIn(
            "Sending mouse movement to gadget: buttons=0x00 "
            + "x=32767 y=-32767 wheel=127 pan=-127 "
            + "report=00 ff 7f 01 80 7f 81",
            logs.output[0],
        )
        self.assertIn(
            "Sending mouse movement to gadget: buttons=0x00 "
            + "x=7233 y=-7233 wheel=73 pan=-73 "
            + "report=00 41 1c bf e3 49 b7",
            logs.output[1],
        )

    async def test_button_reports_use_one_full_button_byte(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            await mouse.press(MouseButtons.TASK)
            await mouse.release(MouseButtons.TASK)

        self.assertEqual(device.sent, [_mouse_report(MouseButtons.TASK), _mouse_report()])


class HidDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_consumer_key_release_uses_consumer_control_release_api(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate())

        with (
            patch("bluetooth_2_usb.hid.dispatch.categorize", side_effect=lambda event: event),
            patch("bluetooth_2_usb.hid.dispatch.KeyEvent", _TestKeyEvent),
        ):
            await dispatcher.dispatch(_TestKeyEvent(ecodes.KEY_VOLUMEUP, _TestKeyEvent.key_up))

        self.assertEqual(hid_gadgets.consumer.release_calls, 1)
        self.assertEqual(hid_gadgets.mouse.releases, [])

    async def test_dispatch_categorizes_raw_event(self) -> None:
        dispatcher = HidDispatcher(_FakeHidGadgets(), _active_gate())
        raw_event = object()
        categorized = _TestSynEvent()

        with patch("bluetooth_2_usb.hid.dispatch.categorize", return_value=categorized) as categorize:
            await dispatcher.dispatch(raw_event)

        categorize.assert_called_once_with(raw_event)

    async def test_dispatch_accepts_single_syn_event_and_flushes_mouse_delta(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate())

        with (
            patch("bluetooth_2_usb.hid.dispatch.categorize", side_effect=lambda event: event),
            patch("bluetooth_2_usb.hid.dispatch.RelEvent", _TestRelEvent),
        ):
            with self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs:
                await dispatcher.dispatch(_TestRelEvent(ecodes.REL_X, 7))
                await dispatcher.dispatch(_TestSynEvent())

        self.assertEqual(hid_gadgets.mouse.moves, [(7, 0, 0, 0)])
        self.assertTrue(any("coalesced_events=1" in message and "emitted=True" in message for message in logs.output))

    async def test_dispatch_logs_coalesced_mouse_delta_count_on_flush(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate())

        with (
            patch("bluetooth_2_usb.hid.dispatch.categorize", side_effect=lambda event: event),
            patch("bluetooth_2_usb.hid.dispatch.RelEvent", _TestRelEvent),
        ):
            with self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs:
                await dispatcher.dispatch(_TestRelEvent(ecodes.REL_X, 7))
                await dispatcher.dispatch(_TestRelEvent(ecodes.REL_Y, -3))
                await dispatcher.dispatch(_TestSynEvent())

        self.assertEqual(hid_gadgets.mouse.moves, [(7, -3, 0, 0)])
        self.assertTrue(any("coalesced_events=2" in message and "emitted=True" in message for message in logs.output))

    async def test_dispatch_logs_fractional_mouse_delta_flush_without_report(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate())

        with (
            patch("bluetooth_2_usb.hid.dispatch.categorize", side_effect=lambda event: event),
            patch("bluetooth_2_usb.hid.dispatch.RelEvent", _TestRelEvent),
        ):
            with self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs:
                await dispatcher.dispatch(_TestRelEvent(ecodes.REL_WHEEL_HI_RES, 60))
                await dispatcher.dispatch(_TestSynEvent())

        self.assertEqual(hid_gadgets.mouse.moves, [])
        self.assertTrue(any("coalesced_events=1" in message and "emitted=False" in message for message in logs.output))

    async def test_dispatch_inactive_gate_discards_coalesced_count(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, gate)

        with (
            patch("bluetooth_2_usb.hid.dispatch.categorize", side_effect=lambda event: event),
            patch("bluetooth_2_usb.hid.dispatch.RelEvent", _TestRelEvent),
        ):
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_X, 7))
            gate.set_host_configured(False)
            await dispatcher.flush()
            gate.set_host_configured(True)
            with self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs:
                await dispatcher.dispatch(_TestRelEvent(ecodes.REL_Y, -3))
                await dispatcher.flush()

        self.assertEqual(hid_gadgets.mouse.moves, [(0, -3, 0, 0)])
        self.assertTrue(any("coalesced_events=1" in message for message in logs.output))

    async def test_mouse_blocking_write_drops_delta_without_retrying(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        hid_gadgets.mouse.move = Mock(side_effect=BlockingIOError())
        dispatcher = HidDispatcher(hid_gadgets, gate)

        with (
            patch("bluetooth_2_usb.hid.dispatch.categorize", side_effect=lambda event: event),
            patch("bluetooth_2_usb.hid.dispatch.RelEvent", _TestRelEvent),
        ):
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_X, 40000))
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_Y, -40000))
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_WHEEL, 200))
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_HWHEEL, -200))
            await dispatcher.flush()

        hid_gadgets.mouse.move.assert_called_once_with(40000, -40000, 200, -200)
        self.assertEqual(dispatcher.write_failures, 1)
        self.assertTrue(gate.active)


class HidDescriptorContractTest(unittest.TestCase):
    def test_mouse_report_writer_uses_descriptor_report_length(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])

        self.assertEqual(len(mouse.report), MOUSE_IN_REPORT_LENGTH)
