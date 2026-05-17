import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from bluetooth_2_usb.evdev import KeyEvent, ecodes
from bluetooth_2_usb.hid.absolute import PadAccumulator, PadReport, PenReport, TouchReport, TouchReportContact
from bluetooth_2_usb.hid.buttons import MouseButtons
from bluetooth_2_usb.hid.constants import (
    MOUSE_IN_REPORT_LENGTH,
    TABLET_PAD_REPORT_ID,
    TABLET_PEN_REPORT_ID,
    TOUCH_DIGITIZER_REPORT_ID,
)
from bluetooth_2_usb.hid.consumer import ConsumerControl
from bluetooth_2_usb.hid.dispatch import HidDispatcher
from bluetooth_2_usb.hid.keyboard import Keyboard
from bluetooth_2_usb.hid.mouse import Mouse
from bluetooth_2_usb.hid.tablet import TabletDigitizer
from bluetooth_2_usb.hid.touch import TouchDigitizer
from bluetooth_2_usb.inputs.profile import AbsAxisInfo, InputDeviceKind, InputDeviceProfile
from bluetooth_2_usb.relay.gate import RelayGate

NUL = 0x00
NO_BUTTONS = NUL
NO_MOVE = (NUL, NUL, NUL, NUL, NUL, NUL)
HID_I16_MAX = 32767
HID_I16_MIN = -32767
HID_I8_MAX = 127
HID_I8_MIN = -127
ADAFRUIT_HID = "adafruit_hid"
ADAFRUIT_HID_CONSUMER_CONTROL = "adafruit_hid.consumer_control"
ADAFRUIT_HID_KEYBOARD = "adafruit_hid.keyboard"
HID_CONSUMER_ASYNCIO = "bluetooth_2_usb.hid.consumer.asyncio"
HID_DISPATCH = "bluetooth_2_usb.hid.dispatch"
HID_KEYBOARD_ASYNCIO = "bluetooth_2_usb.hid.keyboard.asyncio"
HID_MOUSE_ASYNCIO = "bluetooth_2_usb.hid.mouse.asyncio"
HID_TABLET_ASYNCIO = "bluetooth_2_usb.hid.tablet.asyncio"
HID_TOUCH_ASYNCIO = "bluetooth_2_usb.hid.touch.asyncio"


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


class _FakeTouch:
    def __init__(self) -> None:
        self.reports = []
        self.release_all_calls = 0

    async def send(self, report) -> None:
        self.reports.append(report)

    async def release_all(self) -> None:
        self.release_all_calls += 1


class _FakeTablet:
    def __init__(self) -> None:
        self.pen_reports = []
        self.pad_reports = []
        self.release_all_calls = 0

    async def send_pen(self, report) -> None:
        self.pen_reports.append(report)

    async def send_pad(self, report) -> None:
        self.pad_reports.append(report)

    async def release_all(self) -> None:
        self.release_all_calls += 1


class _FakeHidGadgets:
    def __init__(self) -> None:
        self.keyboard = _FakeKeyboard()
        self.mouse = _FakeMouse()
        self.consumer = _FakeConsumer()
        self.touch = _FakeTouch()
        self.tablet = _FakeTablet()
        self.release_all_calls = 0

    async def release_all(self) -> None:
        self.release_all_calls += 1
        await self.keyboard.release_all()
        await self.mouse.release_all()
        await self.consumer.release()
        await self.touch.release_all()
        await self.tablet.release_all()


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


class _WrappedSynEvent:
    def __init__(self) -> None:
        self.event = SimpleNamespace(type=ecodes.EV_SYN, code=ecodes.SYN_REPORT, value=0)


class _TestAbsEvent:
    type = ecodes.EV_ABS

    def __init__(self, code: int, value: int) -> None:
        self.code = code
        self.value = value


class _WrappedAbsEvent:
    def __init__(self, code: int, value: int) -> None:
        self.event = SimpleNamespace(type=ecodes.EV_ABS, code=code, value=value)


class _TestMiscEvent:
    type = ecodes.EV_MSC

    def __init__(self, code: int, value: int) -> None:
        self.code = code
        self.value = value


class _WrappedMiscEvent:
    def __init__(self, code: int, value: int) -> None:
        self.event = SimpleNamespace(type=ecodes.EV_MSC, code=code, value=value)


def _touch_profile() -> InputDeviceProfile:
    return InputDeviceProfile(
        kind=InputDeviceKind.TOUCHPAD,
        abs_axes={
            ecodes.ABS_MT_SLOT: AbsAxisInfo(ecodes.ABS_MT_SLOT, 0, 15),
            ecodes.ABS_MT_POSITION_X: AbsAxisInfo(ecodes.ABS_MT_POSITION_X, -3678, 3934),
            ecodes.ABS_MT_POSITION_Y: AbsAxisInfo(ecodes.ABS_MT_POSITION_Y, -2478, 2587),
            ecodes.ABS_MT_TOUCH_MAJOR: AbsAxisInfo(ecodes.ABS_MT_TOUCH_MAJOR, 0, 1020),
            ecodes.ABS_MT_TOUCH_MINOR: AbsAxisInfo(ecodes.ABS_MT_TOUCH_MINOR, 0, 1020),
            ecodes.ABS_MT_PRESSURE: AbsAxisInfo(ecodes.ABS_MT_PRESSURE, 0, 253),
        },
    )


def _pen_profile() -> InputDeviceProfile:
    return InputDeviceProfile(
        kind=InputDeviceKind.TABLET_PEN,
        abs_axes={
            ecodes.ABS_X: AbsAxisInfo(ecodes.ABS_X, 0, 65024),
            ecodes.ABS_Y: AbsAxisInfo(ecodes.ABS_Y, 0, 40640),
            ecodes.ABS_PRESSURE: AbsAxisInfo(ecodes.ABS_PRESSURE, 0, 2047),
            ecodes.ABS_DISTANCE: AbsAxisInfo(ecodes.ABS_DISTANCE, 0, 63),
            ecodes.ABS_TILT_X: AbsAxisInfo(ecodes.ABS_TILT_X, -64, 63),
            ecodes.ABS_TILT_Y: AbsAxisInfo(ecodes.ABS_TILT_Y, -64, 63),
        },
    )


def _pad_profile() -> InputDeviceProfile:
    return InputDeviceProfile(kind=InputDeviceKind.TABLET_PAD)


class KeyboardTest(unittest.IsolatedAsyncioTestCase):
    async def test_press_release_and_release_all_do_not_sleep(self) -> None:
        keyboard_device = Mock()

        with (
            patch(f"{ADAFRUIT_HID_KEYBOARD}.Keyboard", return_value=keyboard_device),
            patch(f"{HID_KEYBOARD_ASYNCIO}.sleep") as sleep,
        ):
            keyboard = Keyboard(devices=[])
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
            patch(f"{ADAFRUIT_HID_KEYBOARD}.Keyboard", return_value=keyboard_device),
            patch(f"{HID_KEYBOARD_ASYNCIO}.sleep") as sleep,
        ):
            keyboard = Keyboard(devices=[])
            await keyboard.press(1)

        self.assertEqual(keyboard_device.press.mock_calls, [call(1), call(1)])
        sleep.assert_called_once_with(keyboard.REPORT_WRITE_RETRY_DELAY_SEC)

    async def test_release_raises_after_retry_budget_is_exhausted(self) -> None:
        keyboard_device = Mock()
        keyboard_device.release.side_effect = BlockingIOError()

        with (
            patch(f"{ADAFRUIT_HID_KEYBOARD}.Keyboard", return_value=keyboard_device),
            patch(f"{HID_KEYBOARD_ASYNCIO}.sleep") as sleep,
        ):
            keyboard = Keyboard(devices=[])
            with self.assertRaises(BlockingIOError):
                await keyboard.release(1)

        self.assertEqual(keyboard_device.release.mock_calls, [call(1)] * keyboard.REPORT_WRITE_MAX_TRIES)
        self.assertEqual(
            sleep.mock_calls, [call(keyboard.REPORT_WRITE_RETRY_DELAY_SEC)] * (keyboard.REPORT_WRITE_MAX_TRIES - 1)
        )


class ConsumerControlTest(unittest.IsolatedAsyncioTestCase):
    async def test_press_and_release_delegate_without_sleep(self) -> None:
        consumer_device = Mock()

        with (
            patch(f"{ADAFRUIT_HID_CONSUMER_CONTROL}.ConsumerControl", return_value=consumer_device),
            patch(f"{HID_CONSUMER_ASYNCIO}.sleep") as sleep,
        ):
            consumer = ConsumerControl(devices=[])
            await consumer.press(1)
            await consumer.release()

        consumer_device.press.assert_called_once_with(1)
        consumer_device.release.assert_called_once_with()
        sleep.assert_not_called()

    async def test_press_retries_blocked_write(self) -> None:
        consumer_device = Mock()
        consumer_device.press.side_effect = [BlockingIOError(), None]

        with (
            patch(f"{ADAFRUIT_HID_CONSUMER_CONTROL}.ConsumerControl", return_value=consumer_device),
            patch(f"{HID_CONSUMER_ASYNCIO}.sleep") as sleep,
        ):
            consumer = ConsumerControl(devices=[])
            await consumer.press(1)

        self.assertEqual(consumer_device.press.mock_calls, [call(1), call(1)])
        sleep.assert_called_once_with(consumer.REPORT_WRITE_RETRY_DELAY_SEC)

    async def test_release_raises_after_retry_budget_is_exhausted(self) -> None:
        consumer_device = Mock()
        consumer_device.release.side_effect = BlockingIOError()

        with (
            patch(f"{ADAFRUIT_HID_CONSUMER_CONTROL}.ConsumerControl", return_value=consumer_device),
            patch(f"{HID_CONSUMER_ASYNCIO}.sleep") as sleep,
        ):
            consumer = ConsumerControl(devices=[])
            with self.assertRaises(BlockingIOError):
                await consumer.release()

        self.assertEqual(consumer_device.release.mock_calls, [call()] * consumer.REPORT_WRITE_MAX_TRIES)
        self.assertEqual(
            sleep.mock_calls, [call(consumer.REPORT_WRITE_RETRY_DELAY_SEC)] * (consumer.REPORT_WRITE_MAX_TRIES - 1)
        )


class MouseTest(unittest.IsolatedAsyncioTestCase):
    async def test_button_reports_do_not_sleep(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device), patch(f"{HID_MOUSE_ASYNCIO}.sleep") as sleep:
            mouse = Mouse(devices=[])
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

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device):
            mouse = Mouse(devices=[])
            await mouse.move(x=300, y=-300, wheel=1, pan=-1)

        self.assertEqual(device.sent, [_mouse_report(x=300, y=-300, wheel=1, pan=-1)])

    async def test_move_accumulates_fractional_pan_across_calls(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device):
            mouse = Mouse(devices=[])
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

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device):
            mouse = Mouse(devices=[])
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

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device):
            mouse = Mouse(devices=[])
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

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device), patch(f"{HID_MOUSE_ASYNCIO}.sleep") as sleep:
            mouse = Mouse(devices=[])
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

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device), patch(f"{HID_MOUSE_ASYNCIO}.sleep") as sleep:
            mouse = Mouse(devices=[])
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

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device), patch(f"{HID_MOUSE_ASYNCIO}.sleep") as sleep:
            mouse = Mouse(devices=[])
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

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device):
            mouse = Mouse(devices=[])
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

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device):
            mouse = Mouse(devices=[])
            await mouse.press(MouseButtons.TASK)
            await mouse.release(MouseButtons.TASK)

        self.assertEqual(device.sent, [_mouse_report(MouseButtons.TASK), _mouse_report()])


class DigitizerTest(unittest.IsolatedAsyncioTestCase):
    async def test_touch_and_tablet_digitizers_use_provided_shared_lock(self) -> None:
        device = SimpleNamespace(sent=[])
        device.send_report = lambda report, report_id=None: device.sent.append((report_id, bytes(report)))
        report_lock = asyncio.Lock()

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device):
            touch = TouchDigitizer(devices=[], report_lock=report_lock)
            tablet = TabletDigitizer(devices=[], report_lock=report_lock)

        self.assertIs(touch._report_lock, report_lock)
        self.assertIs(tablet._report_lock, report_lock)

    async def test_touch_digitizer_packs_contact_report(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report, report_id=None) -> None:
            device.sent.append((report_id, bytes(report)))

        device.send_report = send_report
        touch_report = TouchReport(
            contacts=(TouchReportContact(report_id=3, active=True, x=1000, y=2000, width=12, height=13, pressure=14),),
            button=True,
            scan_time=99,
        )

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device), patch(f"{HID_TOUCH_ASYNCIO}.sleep") as sleep:
            touch = TouchDigitizer(devices=[])
            await touch.send(touch_report)

        self.assertEqual(device.sent[0][0], TOUCH_DIGITIZER_REPORT_ID)
        self.assertEqual(device.sent[0][1][0:9], bytes([0x03, 0x03, 0xE8, 0x03, 0xD0, 0x07, 12, 13, 14]))
        self.assertEqual(device.sent[0][1][45:49], bytes([1, 1, 99, 0]))
        sleep.assert_not_called()

    async def test_tablet_digitizer_packs_pen_and_pad_reports(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report, report_id=None) -> None:
            device.sent.append((report_id, bytes(report)))

        device.send_report = send_report

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device), patch(f"{HID_TABLET_ASYNCIO}.sleep") as sleep:
            tablet = TabletDigitizer(devices=[])
            await tablet.send_pen(
                PenReport(
                    in_range=True,
                    tip=True,
                    eraser=False,
                    barrel=True,
                    barrel2=False,
                    x=300,
                    y=400,
                    pressure=500,
                    distance=6,
                    tilt_x=-7,
                    tilt_y=8,
                    serial=9,
                )
            )
            await tablet.send_pad(PadReport(buttons=0x0102, wheel=-3))

        self.assertEqual(device.sent[0][0], TABLET_PEN_REPORT_ID)
        self.assertEqual(device.sent[0][1], bytes([0x0B, 0x2C, 0x01, 0x90, 0x01, 0xF4, 0x01, 6, 0, 249, 8, 9, 0, 0, 0]))
        self.assertEqual(device.sent[1], (TABLET_PAD_REPORT_ID, bytes([0x02, 0x01, 253])))
        sleep.assert_not_called()

    async def test_tablet_digitizer_pads_reports_for_combined_configfs_function(self) -> None:
        device = SimpleNamespace(sent=[], configfs_report_length=53)

        def send_report(report, report_id=None) -> None:
            device.sent.append((report_id, bytes(report)))

        device.send_report = send_report

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device):
            tablet = TabletDigitizer(devices=[])
            await tablet.send_pad(PadReport(buttons=0x0001, wheel=2))

        self.assertEqual(device.sent[0][0], TABLET_PAD_REPORT_ID)
        self.assertEqual(len(device.sent[0][1]), 52)
        self.assertEqual(device.sent[0][1][:3], bytes([0x01, 0x00, 0x02]))

    async def test_tablet_digitizer_release_all_holds_lock_across_pen_and_pad_reports(self) -> None:
        class RecordingAsyncLock:
            def __init__(self) -> None:
                self.active = False
                self.enter_count = 0
                self.exit_count = 0

            async def __aenter__(self):
                if self.active:
                    raise AssertionError("lock re-entered")
                self.active = True
                self.enter_count += 1

            async def __aexit__(self, exc_type, exc, tb):
                if not self.active:
                    raise AssertionError("lock exited without entering")
                self.active = False
                self.exit_count += 1

        lock = RecordingAsyncLock()
        device = SimpleNamespace(sent=[])

        def send_report(report, report_id=None) -> None:
            device.sent.append((report_id, bytes(report), lock.active))

        device.send_report = send_report

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device):
            tablet = TabletDigitizer(devices=[], report_lock=lock)
            await tablet.release_all()

        self.assertEqual(lock.enter_count, 1)
        self.assertEqual(lock.exit_count, 1)
        self.assertEqual([sent[0] for sent in device.sent], [TABLET_PEN_REPORT_ID, TABLET_PAD_REPORT_ID])
        self.assertEqual([sent[2] for sent in device.sent], [True, True])

    async def test_pad_accumulator_emits_relative_wheel_once(self) -> None:
        pad = PadAccumulator()

        pad.add_event(_TestAbsEvent(ecodes.ABS_WHEEL, -3))
        self.assertEqual(pad.flush(), PadReport(buttons=0, wheel=-3))
        pad.add_key(_TestKeyEvent(ecodes.BTN_LEFT, _TestKeyEvent.key_down))

        self.assertEqual(pad.flush(), PadReport(buttons=0x01, wheel=0))

    async def test_pad_accumulator_release_all_clears_wheel_only_state(self) -> None:
        pad = PadAccumulator()

        pad.add_event(_TestAbsEvent(ecodes.ABS_WHEEL, 4))

        self.assertEqual(pad.release_all(), PadReport(buttons=0, wheel=0))
        self.assertIsNone(pad.flush())


class HidDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_consumer_key_release_uses_consumer_control_release_api(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
        ):
            await dispatcher.dispatch(_TestKeyEvent(ecodes.KEY_VOLUMEUP, _TestKeyEvent.key_up))

        self.assertEqual(hid_gadgets.consumer.release_calls, 1)
        self.assertEqual(hid_gadgets.mouse.releases, [])

    async def test_dispatch_categorizes_raw_event(self) -> None:
        dispatcher = HidDispatcher(_FakeHidGadgets(), _active_gate())
        raw_event = object()
        categorized = _TestSynEvent()

        with patch(f"{HID_DISPATCH}.categorize", return_value=categorized) as categorize:
            await dispatcher.dispatch(raw_event)

        categorize.assert_called_once_with(raw_event)

    async def test_dispatch_accepts_single_syn_event_and_flushes_mouse(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.RelEvent", _TestRelEvent),
            self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs,
        ):
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_X, 7))
            await dispatcher.dispatch(_TestSynEvent())

        self.assertEqual(hid_gadgets.mouse.moves, [(7, 0, 0, 0)])
        self.assertTrue(any("coalesced_events=1" in message and "emitted=True" in message for message in logs.output))

    async def test_dispatch_logs_coalesced_mouse_count_on_flush(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.RelEvent", _TestRelEvent),
            self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs,
        ):
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_X, 7))
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_Y, -3))
            await dispatcher.dispatch(_TestSynEvent())

        self.assertEqual(hid_gadgets.mouse.moves, [(7, -3, 0, 0)])
        self.assertTrue(any("coalesced_events=2" in message and "emitted=True" in message for message in logs.output))

    async def test_dispatch_logs_fractional_mouse_flush_without_report(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.RelEvent", _TestRelEvent),
            self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs,
        ):
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_WHEEL_HI_RES, 60))
            await dispatcher.dispatch(_TestSynEvent())

        self.assertEqual(hid_gadgets.mouse.moves, [])
        self.assertTrue(any("coalesced_events=1" in message and "emitted=False" in message for message in logs.output))

    async def test_dispatch_inactive_gate_discards_coalesced_count(self) -> None:
        gate = _active_gate()
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, gate)

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.RelEvent", _TestRelEvent),
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
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.RelEvent", _TestRelEvent),
        ):
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_X, 40000))
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_Y, -40000))
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_WHEEL, 200))
            await dispatcher.dispatch(_TestRelEvent(ecodes.REL_HWHEEL, -200))
            await dispatcher.flush()

        hid_gadgets.mouse.move.assert_called_once_with(40000, -40000, 200, -200)
        self.assertEqual(dispatcher.write_failures, 1)
        self.assertTrue(gate.active)

    async def test_dispatch_routes_touchpad_absolute_frame_to_touch_digitizer(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate(), source_profile=_touch_profile())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
        ):
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_MT_SLOT, 0))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_MT_TRACKING_ID, 42))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_MT_POSITION_X, -3678))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_MT_POSITION_Y, 2587))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_MT_TOUCH_MAJOR, 510))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_MT_TOUCH_MINOR, 1020))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_MT_PRESSURE, 253))
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_LEFT, _TestKeyEvent.key_down))
            await dispatcher.dispatch(_TestSynEvent())

        self.assertEqual(len(hid_gadgets.touch.reports), 1)
        report = hid_gadgets.touch.reports[0]
        self.assertTrue(report.button)
        self.assertEqual(len(report.contacts), 1)
        self.assertEqual(report.contacts[0].x, 0)
        self.assertEqual(report.contacts[0].y, 32767)
        self.assertEqual(report.contacts[0].width, 128)
        self.assertEqual(report.contacts[0].height, 255)
        self.assertEqual(report.contacts[0].pressure, 255)

    async def test_dispatch_routes_evdev_wrapped_touch_frame_to_touch_digitizer(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate(), source_profile=_touch_profile())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
        ):
            await dispatcher.dispatch(_WrappedAbsEvent(ecodes.ABS_MT_SLOT, 0))
            await dispatcher.dispatch(_WrappedAbsEvent(ecodes.ABS_MT_TRACKING_ID, 42))
            await dispatcher.dispatch(_WrappedAbsEvent(ecodes.ABS_MT_POSITION_X, -3678))
            await dispatcher.dispatch(_WrappedAbsEvent(ecodes.ABS_MT_POSITION_Y, 2587))
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_LEFT, _TestKeyEvent.key_down))
            await dispatcher.dispatch(_WrappedSynEvent())

        self.assertEqual(len(hid_gadgets.touch.reports), 1)
        report = hid_gadgets.touch.reports[0]
        self.assertTrue(report.button)
        self.assertEqual(len(report.contacts), 1)
        self.assertEqual(report.contacts[0].x, 0)
        self.assertEqual(report.contacts[0].y, 32767)

    async def test_dispatch_routes_button_lifetime_touch_frame_to_touch_digitizer(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate(), source_profile=_touch_profile())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
        ):
            await dispatcher.dispatch(_WrappedAbsEvent(ecodes.ABS_MT_SLOT, 0))
            await dispatcher.dispatch(_WrappedAbsEvent(ecodes.ABS_MT_POSITION_X, -3678))
            await dispatcher.dispatch(_WrappedAbsEvent(ecodes.ABS_MT_POSITION_Y, 2587))
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_TOUCH, _TestKeyEvent.key_down))
            await dispatcher.dispatch(_WrappedSynEvent())
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_TOUCH, _TestKeyEvent.key_up))
            await dispatcher.dispatch(_WrappedSynEvent())

        self.assertEqual(len(hid_gadgets.touch.reports), 2)
        press_report, release_report = hid_gadgets.touch.reports
        self.assertEqual(len(press_report.contacts), 1)
        self.assertTrue(press_report.contacts[0].active)
        self.assertEqual(press_report.contacts[0].x, 0)
        self.assertEqual(press_report.contacts[0].y, 32767)
        self.assertEqual(len(release_report.contacts), 1)
        self.assertFalse(release_report.contacts[0].active)

    async def test_dispatch_routes_pen_frame_to_tablet_digitizer(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate(), source_profile=_pen_profile())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
        ):
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_TOOL_PEN, _TestKeyEvent.key_down))
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_TOUCH, _TestKeyEvent.key_down))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_X, 65024))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_Y, 40640))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_PRESSURE, 2047))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_TILT_X, -64))
            await dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_TILT_Y, 63))
            await dispatcher.dispatch(_TestMiscEvent(ecodes.MSC_SERIAL, 123))
            await dispatcher.dispatch(_TestSynEvent())

        self.assertEqual(len(hid_gadgets.tablet.pen_reports), 1)
        report = hid_gadgets.tablet.pen_reports[0]
        self.assertTrue(report.in_range)
        self.assertTrue(report.tip)
        self.assertEqual(report.x, 32767)
        self.assertEqual(report.y, 32767)
        self.assertEqual(report.pressure, 4095)
        self.assertEqual(report.tilt_x, -127)
        self.assertEqual(report.tilt_y, 127)
        self.assertEqual(report.serial, 123)

    async def test_dispatch_consumes_all_classified_pen_tool_keys(self) -> None:
        for tool_key in (
            ecodes.BTN_TOOL_BRUSH,
            ecodes.BTN_TOOL_PENCIL,
            ecodes.BTN_TOOL_AIRBRUSH,
            ecodes.BTN_TOOL_MOUSE,
            ecodes.BTN_TOOL_LENS,
        ):
            with self.subTest(tool_key=tool_key):
                hid_gadgets = _FakeHidGadgets()
                dispatcher = HidDispatcher(hid_gadgets, _active_gate(), source_profile=_pen_profile())

                with (
                    patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
                    patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
                ):
                    await dispatcher.dispatch(_TestKeyEvent(tool_key, _TestKeyEvent.key_down))
                    await dispatcher.dispatch(_TestSynEvent())

                self.assertEqual(hid_gadgets.keyboard.presses, [])
                self.assertEqual(hid_gadgets.tablet.pen_reports[-1].in_range, True)

    async def test_dispatch_rubber_tool_release_clears_pen_range_state(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate(), source_profile=_pen_profile())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
        ):
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_TOOL_RUBBER, _TestKeyEvent.key_down))
            await dispatcher.dispatch(_TestSynEvent())
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_TOOL_RUBBER, _TestKeyEvent.key_up))
            await dispatcher.dispatch(_TestSynEvent())

        self.assertTrue(hid_gadgets.tablet.pen_reports[0].in_range)
        self.assertTrue(hid_gadgets.tablet.pen_reports[0].eraser)
        self.assertFalse(hid_gadgets.tablet.pen_reports[1].in_range)
        self.assertFalse(hid_gadgets.tablet.pen_reports[1].eraser)

    async def test_dispatch_routes_evdev_wrapped_pen_frame_to_tablet_digitizer(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate(), source_profile=_pen_profile())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
        ):
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_TOOL_PEN, _TestKeyEvent.key_down))
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_TOUCH, _TestKeyEvent.key_down))
            await dispatcher.dispatch(_WrappedAbsEvent(ecodes.ABS_X, 65024))
            await dispatcher.dispatch(_WrappedAbsEvent(ecodes.ABS_Y, 40640))
            await dispatcher.dispatch(_WrappedAbsEvent(ecodes.ABS_PRESSURE, 2047))
            await dispatcher.dispatch(_WrappedMiscEvent(ecodes.MSC_SERIAL, 123))
            await dispatcher.dispatch(_WrappedSynEvent())

        self.assertEqual(len(hid_gadgets.tablet.pen_reports), 1)
        report = hid_gadgets.tablet.pen_reports[0]
        self.assertTrue(report.in_range)
        self.assertTrue(report.tip)
        self.assertEqual(report.x, 32767)
        self.assertEqual(report.y, 32767)
        self.assertEqual(report.pressure, 4095)
        self.assertEqual(report.serial, 123)

    async def test_dispatch_routes_wacom_pt_pad_buttons_to_tablet_pad_report(self) -> None:
        hid_gadgets = _FakeHidGadgets()
        dispatcher = HidDispatcher(hid_gadgets, _active_gate(), source_profile=_pad_profile())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
        ):
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_LEFT, _TestKeyEvent.key_down))
            await dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_BACK, _TestKeyEvent.key_down))
            await dispatcher.dispatch(_TestSynEvent())

        self.assertEqual(len(hid_gadgets.tablet.pad_reports), 1)
        self.assertEqual(hid_gadgets.tablet.pad_reports[0].buttons, 0x09)

    async def test_release_active_digitizers_releases_touch_pen_and_pad_state(self) -> None:
        touch_gadgets = _FakeHidGadgets()
        touch_dispatcher = HidDispatcher(touch_gadgets, _active_gate(), source_profile=_touch_profile())
        pen_gadgets = _FakeHidGadgets()
        pen_dispatcher = HidDispatcher(pen_gadgets, _active_gate(), source_profile=_pen_profile())
        pad_gadgets = _FakeHidGadgets()
        pad_dispatcher = HidDispatcher(pad_gadgets, _active_gate(), source_profile=_pad_profile())

        with (
            patch(f"{HID_DISPATCH}.categorize", side_effect=lambda event: event),
            patch(f"{HID_DISPATCH}.KeyEvent", _TestKeyEvent),
        ):
            await touch_dispatcher.dispatch(_TestAbsEvent(ecodes.ABS_MT_TRACKING_ID, 42))
            await touch_dispatcher.dispatch(_TestSynEvent())
            await pen_dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_TOOL_PEN, _TestKeyEvent.key_down))
            await pen_dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_TOUCH, _TestKeyEvent.key_down))
            await pen_dispatcher.dispatch(_TestSynEvent())
            await pad_dispatcher.dispatch(_TestKeyEvent(ecodes.BTN_LEFT, _TestKeyEvent.key_down))
            await pad_dispatcher.dispatch(_TestSynEvent())

        await touch_dispatcher.release_active_digitizers()
        await pen_dispatcher.release_active_digitizers()
        await pad_dispatcher.release_active_digitizers()

        self.assertFalse(touch_gadgets.touch.reports[-1].contacts[0].active)
        self.assertFalse(pen_gadgets.tablet.pen_reports[-1].in_range)
        self.assertFalse(pen_gadgets.tablet.pen_reports[-1].tip)
        self.assertEqual(pad_gadgets.tablet.pad_reports[-1].buttons, 0)


class HidDescriptorContractTest(unittest.TestCase):
    def test_mouse_report_writer_uses_descriptor_report_length(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch(f"{ADAFRUIT_HID}.find_device", return_value=device):
            mouse = Mouse(devices=[])

        self.assertEqual(len(mouse.report), MOUSE_IN_REPORT_LENGTH)
