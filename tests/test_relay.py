import asyncio
import errno
import re
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import usb_hid

from bluetooth_2_usb.device_identifier import DeviceIdentifier
from bluetooth_2_usb.evdev import ecodes, evdev_to_usb_hid
from bluetooth_2_usb.extended_mouse import ExtendedMouse
from bluetooth_2_usb.hid_dispatch import dispatch_key_event_to_hid
from bluetooth_2_usb.hid_gadget_config import rebuild_gadget
from bluetooth_2_usb.hid_gadget_layout import (
    DEFAULT_KEYBOARD_DESCRIPTOR,
    DEFAULT_MOUSE_DESCRIPTOR,
    GadgetHidDevice,
    build_default_layout,
)
from bluetooth_2_usb.hid_gadgets import HidGadgets
from bluetooth_2_usb.input_relay import InputRelay
from bluetooth_2_usb.mouse_delta import MouseDelta
from bluetooth_2_usb.relay_supervisor import RelaySupervisor, _ActiveRelay, _SupervisorState
from bluetooth_2_usb.runtime_events import DeviceAdded, UdcStateChanged
from bluetooth_2_usb.shortcut_toggler import ShortcutToggler


class _FakeKeyboard:
    def __init__(self) -> None:
        self.release_all_calls = 0

    def release_all(self) -> None:
        self.release_all_calls += 1


class _FakeMouse:
    def __init__(self) -> None:
        self.release_all_calls = 0
        self.moves = []
        self.presses = []
        self.releases = []

    def release_all(self) -> None:
        self.release_all_calls += 1

    def move(self, x=0, y=0, wheel=0, pan=0) -> None:
        self.moves.append((x, y, wheel, pan))

    def press(self, key_id) -> None:
        self.presses.append(key_id)

    def release(self, key_id) -> None:
        self.releases.append(key_id)


class _FakeConsumer:
    def __init__(self) -> None:
        self.presses = []
        self.release_calls = 0

    def press(self, key_id) -> None:
        self.presses.append(key_id)

    def release(self) -> None:
        self.release_calls += 1


class _FakeHidGadgets:
    def __init__(self) -> None:
        self.keyboard = _FakeKeyboard()
        self.mouse = _FakeMouse()
        self.consumer = _FakeConsumer()
        self.release_all_calls = 0

    def release_all(self) -> None:
        self.release_all_calls += 1
        self.keyboard.release_all()
        self.mouse.release_all()
        self.consumer.release()


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
        "relaying_active": asyncio.Event(),
        "task_group": _FakeTaskGroup(),
        "device_identifiers": [],
    }
    args.update(overrides)
    return RelaySupervisor(**args)


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


class ExtendedMouseTest(unittest.TestCase):
    def test_move_uses_16_bit_xy_and_8_bit_wheel_pan(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            mouse.move(x=300, y=-300, wheel=1, pan=-1)

        self.assertEqual(device.sent, [bytes([0x00, 0x2C, 0x01, 0xD4, 0xFE, 0x01, 0xFF])])

    def test_move_accumulates_fractional_pan_across_calls(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            mouse.move(pan=0.5)
            mouse.move(pan=0.5)
            mouse.move(pan=-0.5)
            mouse.move(pan=-0.5)

        self.assertEqual(
            device.sent,
            [
                bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01]),
                bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF]),
            ],
        )

    def test_move_accumulates_fractional_wheel_across_calls(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            mouse.move(wheel=0.5)
            mouse.move(wheel=0.5)
            mouse.move(wheel=-0.5)
            mouse.move(wheel=-0.5)

        self.assertEqual(
            device.sent,
            [
                bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00]),
                bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x00]),
            ],
        )

    def test_move_splits_large_xy_without_widening_wheel_pan(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            mouse.move(x=40000, y=-40000, wheel=200, pan=-200)

        self.assertEqual(
            device.sent,
            [
                bytes([0x00, 0xFF, 0x7F, 0x01, 0x80, 0x7F, 0x81]),
                bytes([0x00, 0x41, 0x1C, 0xBF, 0xE3, 0x49, 0xB7]),
            ],
        )

    def test_move_debug_logs_reports_sent_to_gadget(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            with self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs:
                mouse.move(x=40000, y=-40000, wheel=200, pan=-200)

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

    def test_button_reports_use_one_full_button_byte(self) -> None:
        device = SimpleNamespace(sent=[])

        def send_report(report) -> None:
            device.sent.append(bytes(report))

        device.send_report = send_report

        with patch("adafruit_hid.find_device", return_value=device):
            mouse = ExtendedMouse(devices=[])
            mouse.press(ExtendedMouse.TASK_BUTTON)
            mouse.release(ExtendedMouse.TASK_BUTTON)

        self.assertEqual(
            device.sent,
            [
                bytes([0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
            ],
        )


class ExtendedMouseButtonMappingTest(unittest.TestCase):
    def test_evdev_uses_extended_mouse_button_bits(self) -> None:
        expected_buttons = {
            ecodes.BTN_LEFT: ExtendedMouse.LEFT,
            ecodes.BTN_RIGHT: ExtendedMouse.RIGHT,
            ecodes.BTN_MIDDLE: ExtendedMouse.MIDDLE,
            ecodes.BTN_SIDE: ExtendedMouse.SIDE,
            ecodes.BTN_EXTRA: ExtendedMouse.EXTRA,
            ecodes.BTN_FORWARD: ExtendedMouse.FORWARD,
            ecodes.BTN_BACK: ExtendedMouse.BACK,
            ecodes.BTN_TASK: ExtendedMouse.TASK,
        }

        for scancode, button in expected_buttons.items():
            with self.subTest(scancode=scancode):
                hid_code, hid_name = evdev_to_usb_hid(
                    SimpleNamespace(scancode=scancode, keystate=1)
                )

                self.assertEqual(hid_code, button)
                self.assertIsNotNone(hid_name)


class HidDispatchTest(unittest.TestCase):
    def test_consumer_key_release_uses_consumer_control_release_api(self) -> None:
        hid_gadgets = _FakeHidGadgets()

        dispatch_key_event_to_hid(
            SimpleNamespace(scancode=ecodes.KEY_VOLUMEUP, keystate=0), hid_gadgets
        )

        self.assertEqual(hid_gadgets.consumer.release_calls, 1)
        self.assertEqual(hid_gadgets.mouse.releases, [])


class DeviceIdentifierTest(unittest.TestCase):
    def test_blank_identifier_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be blank"):
            DeviceIdentifier(" \t ")

    def test_mac_identifier_matches_hyphenated_device_uniq(self) -> None:
        identifier = DeviceIdentifier("aa:bb:cc:dd:ee:ff")
        device = SimpleNamespace(
            path="/dev/input/event7", uniq="AA-BB-CC-DD-EE-FF", name="keyboard"
        )

        self.assertTrue(identifier.matches(device))

    def test_event_like_name_without_numeric_suffix_matches_by_name(self) -> None:
        identifier = DeviceIdentifier("/dev/input/eventual")
        device = SimpleNamespace(
            path="/dev/input/event7", uniq="", name="prefix /dev/input/eventual suffix"
        )

        self.assertTrue(identifier.matches(device))


class ShortcutTogglerTest(unittest.TestCase):
    def test_shortcut_events_are_suppressed_and_toggle_relays(self) -> None:
        event_state = asyncio.Event()
        toggler = ShortcutToggler(
            shortcut_keys={"KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_F12"},
            relaying_active=event_state,
            hid_gadgets=_FakeHidGadgets(),
        )

        make_event = lambda scancode, keystate: SimpleNamespace(
            scancode=scancode, keystate=keystate
        )

        self.assertFalse(toggler.handle_key_event(make_event(29, 1)))
        self.assertFalse(toggler.handle_key_event(make_event(42, 1)))
        self.assertTrue(toggler.handle_key_event(make_event(88, 1)))
        self.assertTrue(event_state.is_set())
        self.assertTrue(toggler.handle_key_event(make_event(88, 0)))
        self.assertTrue(toggler.handle_key_event(make_event(42, 0)))
        self.assertTrue(toggler.handle_key_event(make_event(29, 0)))

        self.assertFalse(toggler.handle_key_event(make_event(29, 1)))
        self.assertFalse(toggler.handle_key_event(make_event(42, 1)))
        self.assertTrue(toggler.handle_key_event(make_event(88, 1)))
        self.assertFalse(event_state.is_set())

    def test_toggle_off_releases_consumer_control(self) -> None:
        event_state = asyncio.Event()
        event_state.set()
        hid_gadgets = _FakeHidGadgets()
        toggler = ShortcutToggler(
            shortcut_keys={"KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_F12"},
            relaying_active=event_state,
            hid_gadgets=hid_gadgets,
        )

        toggler.toggle_relaying()

        self.assertFalse(event_state.is_set())
        self.assertEqual(hid_gadgets.release_all_calls, 1)
        self.assertEqual(hid_gadgets.keyboard.release_all_calls, 1)
        self.assertEqual(hid_gadgets.mouse.release_all_calls, 1)
        self.assertEqual(hid_gadgets.consumer.release_calls, 1)


class HidGadgetsLayoutTest(unittest.TestCase):
    def test_requested_devices_use_default_layout(self) -> None:
        with patch(
            "bluetooth_2_usb.hid_gadgets.build_default_layout",
            return_value=SimpleNamespace(devices=("keyboard", "mouse", "consumer")),
        ):
            devices = HidGadgets()._requested_devices()

        self.assertEqual(devices, ["keyboard", "mouse", "consumer"])

    def test_release_all_releases_keyboard_mouse_and_consumer(self) -> None:
        manager = HidGadgets()
        manager._gadgets = {
            "keyboard": _FakeKeyboard(),
            "mouse": _FakeMouse(),
            "consumer": _FakeConsumer(),
        }

        manager.release_all()

        self.assertEqual(manager._gadgets["keyboard"].release_all_calls, 1)
        self.assertEqual(manager._gadgets["mouse"].release_all_calls, 1)
        self.assertEqual(manager._gadgets["consumer"].release_calls, 1)

    def test_release_all_continues_when_one_raises(self) -> None:
        manager = HidGadgets()
        keyboard = _FakeKeyboard()
        mouse = _FakeMouse()
        consumer = _FakeConsumer()
        keyboard.release_all = Mock(side_effect=RuntimeError("keyboard stuck"))
        manager._gadgets = {"keyboard": keyboard, "mouse": mouse, "consumer": consumer}

        manager.release_all()

        keyboard.release_all.assert_called_once_with()
        self.assertEqual(mouse.release_all_calls, 1)
        self.assertEqual(consumer.release_calls, 1)

    def test_enable_clears_published_refs_before_rebuild(self) -> None:
        manager = HidGadgets()
        manager._gadgets = {
            "keyboard": _FakeKeyboard(),
            "mouse": _FakeMouse(),
            "consumer": _FakeConsumer(),
        }
        manager._enabled = True

        with patch.object(manager, "_prune_stale_hidg_nodes"):
            with patch(
                "bluetooth_2_usb.hid_gadgets.rebuild_gadget",
                side_effect=RuntimeError("rebuild failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "rebuild failed"):
                    manager.enable()

        self.assertEqual(manager._gadgets, {"keyboard": None, "mouse": None, "consumer": None})
        self.assertFalse(manager._enabled)

    def test_expected_hidg_paths_use_declared_function_indexes(self) -> None:
        devices = (SimpleNamespace(function_index=2), SimpleNamespace(function_index=7))
        with patch(
            "bluetooth_2_usb.hid_gadgets.build_default_layout",
            return_value=SimpleNamespace(devices=devices),
        ):
            paths = HidGadgets()._expected_hidg_paths()

        self.assertEqual(paths, (Path("/dev/hidg2"), Path("/dev/hidg7")))

    def test_default_layout_uses_strict_keyboard_and_extended_mouse_consumer(self) -> None:
        layout = build_default_layout()

        self.assertEqual(len(layout.devices), 3)
        self.assertEqual(bytes(layout.devices[0].descriptor), DEFAULT_KEYBOARD_DESCRIPTOR)
        self.assertEqual(bytes(layout.devices[1].descriptor), DEFAULT_MOUSE_DESCRIPTOR)
        self.assertEqual(DEFAULT_MOUSE_DESCRIPTOR.count(bytes((0x09, 0x48))), 2)
        self.assertEqual(tuple(layout.devices[1].report_ids), (0,))
        self.assertEqual(tuple(layout.devices[1].in_report_lengths), (7,))
        self.assertEqual(tuple(layout.devices[1].out_report_lengths), (0,))
        self.assertEqual(layout.devices[1].configfs_report_length, 8)
        self.assertEqual(
            bytes(layout.devices[2].descriptor), bytes(usb_hid.Device.CONSUMER_CONTROL.descriptor)
        )
        self.assertEqual(layout.bcd_device, "0x0205")
        self.assertEqual(layout.product_name, "USB Combo Device")
        self.assertEqual(layout.serial_number, "213374badcafe")
        self.assertEqual(layout.max_power, 100)
        self.assertEqual(layout.bm_attributes, 0xA0)
        self.assertEqual(layout.max_speed, "high-speed")
        self.assertTrue(layout.devices[0].wakeup_on_write)
        self.assertFalse(layout.devices[1].wakeup_on_write)
        self.assertFalse(layout.devices[2].wakeup_on_write)

    def test_gadget_hid_device_passes_protocol_and_subclass_when_required(self) -> None:
        init_calls = []

        def fake_device_init(self, **kwargs) -> None:
            init_calls.append(kwargs)
            if "subclass" not in kwargs or "protocol" not in kwargs:
                raise TypeError(
                    "Device.__init__() missing 2 required keyword-only arguments: "
                    + "'subclass' and 'protocol'"
                )

        with patch.object(usb_hid.Device, "__init__", fake_device_init):
            GadgetHidDevice.from_existing(
                usb_hid.Device.BOOT_KEYBOARD, function_index=0, protocol=1, subclass=1
            )

        self.assertEqual(len(init_calls), 1)
        self.assertEqual(init_calls[0]["protocol"], 1)
        self.assertEqual(init_calls[0]["subclass"], 1)

    def test_prune_stale_hidg_nodes_removes_regular_files(self) -> None:
        manager = HidGadgets()
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "hidg1"
            stale.write_text("stale", encoding="utf-8")
            with patch.object(manager, "_expected_hidg_paths", return_value=(stale,)):
                manager._prune_stale_hidg_nodes()
            self.assertFalse(stale.exists())

    def test_prune_stale_hidg_nodes_ignores_unlink_race(self) -> None:
        manager = HidGadgets()
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "hidg1"
            stale.write_text("stale", encoding="utf-8")
            with patch.object(manager, "_expected_hidg_paths", return_value=(stale,)):
                with patch.object(Path, "unlink", side_effect=FileNotFoundError):
                    manager._prune_stale_hidg_nodes()

    def test_validate_hidg_nodes_rejects_regular_files(self) -> None:
        manager = HidGadgets()
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "hidg1"
            bad.write_text("not-a-device", encoding="utf-8")
            with patch.object(manager, "_expected_hidg_paths", return_value=(bad,)):
                with self.assertRaisesRegex(RuntimeError, re.escape(str(bad))):
                    manager._validate_hidg_nodes(timeout_sec=0, poll_interval_sec=0)

    def test_validate_hidg_nodes_waits_for_delayed_nodes(self) -> None:
        manager = HidGadgets()

        with patch.object(
            manager, "_collect_invalid_hidg_nodes", side_effect=[["/dev/hidg0 (missing)"], []]
        ) as collect_invalid:
            with patch("bluetooth_2_usb.hid_gadgets.time.sleep") as sleep:
                manager._validate_hidg_nodes(timeout_sec=0.1, poll_interval_sec=0.01)

        self.assertEqual(collect_invalid.call_count, 2)
        sleep.assert_called_once_with(0.01)

    def test_collect_invalid_hidg_nodes_rejects_unopenable_character_devices(self) -> None:
        manager = HidGadgets()
        path = Path("/dev/hidg0")
        stats = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_rdev=0)

        with patch.object(manager, "_expected_hidg_paths", return_value=(path,)):
            with patch.object(Path, "stat", return_value=stats):
                with patch("bluetooth_2_usb.hid_gadgets.os.minor", return_value=0, create=True):
                    with patch("bluetooth_2_usb.hid_gadgets.os.O_NONBLOCK", 0, create=True):
                        with patch(
                            "bluetooth_2_usb.hid_gadgets.os.open",
                            side_effect=OSError(errno.ENODEV, "No such device"),
                        ):
                            invalid_paths = manager._collect_invalid_hidg_nodes()

        self.assertEqual(invalid_paths, [f"{path} (No such device)"])

    def test_rebuild_gadget_writes_default_power_and_identity(self) -> None:
        layout = build_default_layout()
        with tempfile.TemporaryDirectory() as tmpdir:
            gadget_root = Path(tmpdir) / "usb_gadget" / "adafruit-blinka"
            with patch("bluetooth_2_usb.hid_gadget_config.GADGET_ROOT", gadget_root):
                with patch(
                    "bluetooth_2_usb.hid_gadget_config._resolve_udc_name", return_value="dummy.udc"
                ):
                    with patch.object(usb_hid, "gadget_root", str(gadget_root)):
                        rebuild_gadget(layout)

            self.assertEqual(
                (gadget_root / "strings/0x409/product").read_text(encoding="utf-8").strip(),
                "USB Combo Device",
            )
            self.assertEqual(
                (gadget_root / "strings/0x409/serialnumber").read_text(encoding="utf-8").strip(),
                "213374badcafe",
            )
            self.assertEqual(
                (gadget_root / "bcdDevice").read_text(encoding="utf-8").strip(), "0x0205"
            )
            self.assertEqual(
                (gadget_root / "configs/c.1/MaxPower").read_text(encoding="utf-8").strip(), "100"
            )
            self.assertEqual(
                (gadget_root / "configs/c.1/bmAttributes").read_text(encoding="utf-8").strip(),
                "0xa0",
            )
            self.assertEqual(
                (gadget_root / "configs/c.1/strings/0x409/configuration")
                .read_text(encoding="utf-8")
                .strip(),
                "Config 1: HID relay",
            )
            self.assertEqual(
                (gadget_root / "max_speed").read_text(encoding="utf-8").strip(), "high-speed"
            )
            self.assertEqual(
                (gadget_root / "functions/hid.usb0/report_length")
                .read_text(encoding="utf-8")
                .strip(),
                "8",
            )
            self.assertEqual(
                (gadget_root / "functions/hid.usb1/report_length")
                .read_text(encoding="utf-8")
                .strip(),
                "8",
            )
            self.assertEqual(
                (gadget_root / "functions/hid.usb2/report_length")
                .read_text(encoding="utf-8")
                .strip(),
                "2",
            )

    def test_rebuild_gadget_sets_wakeup_on_write_only_when_supported(self) -> None:
        layout = build_default_layout()
        with tempfile.TemporaryDirectory() as tmpdir:
            gadget_root = Path(tmpdir) / "usb_gadget" / "adafruit-blinka"
            keyboard_wakeup = gadget_root / "functions/hid.usb0/wakeup_on_write"
            mouse_wakeup = gadget_root / "functions/hid.usb1/wakeup_on_write"

            def fake_exists(path: Path) -> bool:
                if path in {keyboard_wakeup, mouse_wakeup}:
                    return True
                return original_exists(path)

            original_exists = type(keyboard_wakeup).exists

            with patch("bluetooth_2_usb.hid_gadget_config.GADGET_ROOT", gadget_root):
                with patch(
                    "bluetooth_2_usb.hid_gadget_config._resolve_udc_name", return_value="dummy.udc"
                ):
                    with patch.object(usb_hid, "gadget_root", str(gadget_root)):
                        with patch.object(type(keyboard_wakeup), "exists", fake_exists):
                            rebuild_gadget(layout)

            self.assertEqual(keyboard_wakeup.read_text(encoding="utf-8").strip(), "1")
            self.assertEqual(mouse_wakeup.read_text(encoding="utf-8").strip(), "0")
            self.assertFalse((gadget_root / "functions/hid.usb2/wakeup_on_write").exists())

    def test_from_existing_preserves_wakeup_on_write_by_default(self) -> None:
        base_device = GadgetHidDevice.from_existing(
            usb_hid.Device.BOOT_KEYBOARD,
            function_index=0,
            protocol=1,
            subclass=1,
            descriptor=DEFAULT_KEYBOARD_DESCRIPTOR,
            configfs_report_length=8,
            wakeup_on_write=True,
        )

        cloned = GadgetHidDevice.from_existing(
            base_device, function_index=1, protocol=0, subclass=0
        )

        self.assertTrue(cloned.wakeup_on_write)
        self.assertEqual(cloned.configfs_report_length, 8)


class InputRelayTest(unittest.IsolatedAsyncioTestCase):
    async def test_relay_preserves_event_order_under_slow_writer(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        seen: list[tuple[int, int]] = []
        input_device = _TestInputDevice(
            [
                _TestKeyEvent(183, _TestKeyEvent.key_down),
                _TestKeyEvent(183, _TestKeyEvent.key_up),
                _TestKeyEvent(184, _TestKeyEvent.key_down),
                _TestKeyEvent(184, _TestKeyEvent.key_up),
            ]
        )
        relay = InputRelay(input_device, _FakeHidGadgets(), relaying_active=relaying_active)

        async def _slow_process(event) -> None:
            seen.append((event.scancode, event.keystate))
            await asyncio.sleep(0.001)

        with patch("bluetooth_2_usb.input_relay.KeyEvent", _TestKeyEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                with patch.object(relay, "_process_event_with_retry", side_effect=_slow_process):
                    async with relay:
                        await relay.async_relay_events_loop()

        self.assertEqual(seen, [(183, 1), (183, 0), (184, 1), (184, 0)])

    async def test_aexit_ignores_ebadf_from_ungrab_on_disappeared_device(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _FakeGrabInputDevice(ungrab_errno=errno.EBADF)
        relay = InputRelay(
            input_device, _FakeHidGadgets(), grab_device=True, relaying_active=relaying_active
        )

        async with relay:
            self.assertTrue(relay._currently_grabbed)

        self.assertEqual(input_device.grab_calls, 1)
        self.assertEqual(input_device.ungrab_calls, 1)
        self.assertEqual(input_device.close_calls, 0)
        self.assertFalse(relay._currently_grabbed)

    async def test_aenter_defers_grab_while_relaying_is_paused(self) -> None:
        relaying_active = asyncio.Event()
        input_device = _FakeGrabInputDevice()
        relay = InputRelay(
            input_device, _FakeHidGadgets(), grab_device=True, relaying_active=relaying_active
        )

        async with relay:
            self.assertFalse(relay._currently_grabbed)

        self.assertEqual(input_device.grab_calls, 0)
        self.assertEqual(input_device.ungrab_calls, 0)
        self.assertEqual(input_device.close_calls, 0)

    async def test_aexit_does_not_release_shared_gadget_state(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        hid_gadgets = _FakeHidGadgets()
        relay = InputRelay(_FakeGrabInputDevice(), hid_gadgets, relaying_active=relaying_active)

        async with relay:
            pass

        self.assertEqual(hid_gadgets.keyboard.release_all_calls, 0)
        self.assertEqual(hid_gadgets.mouse.release_all_calls, 0)
        self.assertEqual(hid_gadgets.consumer.release_calls, 0)

    async def test_handled_shortcut_runs_pause_cleanup_before_continue(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        hid_gadgets = _FakeHidGadgets()
        toggler = ShortcutToggler(
            shortcut_keys={"KEY_F12"}, relaying_active=relaying_active, hid_gadgets=hid_gadgets
        )
        input_device = _FakeGrabInputDevice(
            [
                _TestRelEvent(ecodes.REL_X, 5),
                _TestKeyEvent(88, _TestKeyEvent.key_down),
                _TestSynEvent(),
            ]
        )
        relay = InputRelay(
            input_device,
            hid_gadgets,
            grab_device=True,
            relaying_active=relaying_active,
            shortcut_toggler=toggler,
        )

        with patch("bluetooth_2_usb.input_relay.KeyEvent", _TestKeyEvent):
            with patch("bluetooth_2_usb.input_relay.RelEvent", _TestRelEvent):
                with patch(
                    "bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event
                ):
                    async with relay:
                        await relay.async_relay_events_loop()

        self.assertFalse(relaying_active.is_set())
        self.assertEqual(input_device.grab_calls, 1)
        self.assertEqual(input_device.ungrab_calls, 1)
        self.assertEqual(hid_gadgets.mouse.moves, [])

    async def test_input_device_removal_stops_reader_without_failing_task_group(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        seen: list[tuple[int, int]] = []
        input_device = _TestInputDevice(
            [_TestKeyEvent(183, _TestKeyEvent.key_down), _TestKeyEvent(183, _TestKeyEvent.key_up)],
            removal_errno=errno.ENODEV,
        )
        relay = InputRelay(input_device, _FakeHidGadgets(), relaying_active=relaying_active)

        async def _record_process(event) -> None:
            seen.append((event.scancode, event.keystate))

        with patch("bluetooth_2_usb.input_relay.KeyEvent", _TestKeyEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                with patch.object(relay, "_process_event_with_retry", side_effect=_record_process):
                    async with relay:
                        await relay.async_relay_events_loop()

        self.assertEqual(seen, [(183, 1), (183, 0)])

    async def test_input_device_removal_ignores_final_flush_enodev(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice([], removal_errno=errno.ENODEV)
        relay = InputRelay(input_device, _FakeHidGadgets(), relaying_active=relaying_active)

        with patch.object(
            relay,
            "_flush_pending_mouse_movement",
            side_effect=OSError(errno.ENODEV, "No such device"),
        ):
            async with relay:
                await relay.async_relay_events_loop()

    async def test_final_flush_enodev_without_input_removal_still_raises(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice([])
        relay = InputRelay(input_device, _FakeHidGadgets(), relaying_active=relaying_active)

        with patch.object(
            relay,
            "_flush_pending_mouse_movement",
            side_effect=OSError(errno.ENODEV, "No such device"),
        ):
            async with relay:
                with self.assertRaises(OSError):
                    await relay.async_relay_events_loop()

    async def test_broken_pipe_clears_relaying_active_when_hid_write_fails(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice([_TestKeyEvent(183, _TestKeyEvent.key_down)])
        relay = InputRelay(input_device, _FakeHidGadgets(), relaying_active=relaying_active)

        with patch("bluetooth_2_usb.input_relay.KeyEvent", _TestKeyEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                with patch(
                    "bluetooth_2_usb.input_relay.dispatch_event_to_hid",
                    side_effect=BrokenPipeError(),
                ):
                    async with relay:
                        await relay.async_relay_events_loop()

        self.assertFalse(relaying_active.is_set())
        self.assertEqual(relay._hid_write_failures, 1)

    async def test_blocked_hid_retry_stops_after_relaying_is_cleared(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        relay = InputRelay(_TestInputDevice([]), _FakeHidGadgets(), relaying_active=relaying_active)
        action = Mock(side_effect=BlockingIOError())

        async def clear_relaying(_delay) -> None:
            relaying_active.clear()

        with patch(
            "bluetooth_2_usb.input_relay.asyncio.sleep", new=AsyncMock(side_effect=clear_relaying)
        ) as sleep:
            processed = await relay._process_hid_action_with_retry(action, "test write")

        self.assertFalse(processed)
        action.assert_called_once_with()
        sleep.assert_awaited_once_with(relay.HID_WRITE_RETRY_DELAY_SEC)
        self.assertEqual(relay._hid_write_retries, 1)
        self.assertEqual(relay._hid_write_failures, 0)

    async def test_unexpected_dispatch_error_propagates(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice([_TestKeyEvent(183, _TestKeyEvent.key_down)])
        relay = InputRelay(input_device, _FakeHidGadgets(), relaying_active=relaying_active)

        with patch("bluetooth_2_usb.input_relay.KeyEvent", _TestKeyEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                with patch(
                    "bluetooth_2_usb.input_relay.dispatch_event_to_hid",
                    side_effect=RuntimeError("dispatch bug"),
                ):
                    async with relay:
                        with self.assertRaisesRegex(RuntimeError, "dispatch bug"):
                            await relay.async_relay_events_loop()

        self.assertTrue(relaying_active.is_set())
        self.assertEqual(relay._hid_write_failures, 1)

    async def test_relative_mouse_events_are_coalesced_until_syn_report(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_X, 2),
                _TestRelEvent(ecodes.REL_Y, -3),
                _TestRelEvent(ecodes.REL_WHEEL, 1),
                _TestRelEvent(ecodes.REL_HWHEEL, 1),
                _TestSynEvent(),
            ]
        )
        manager = _FakeHidGadgets()
        relay = InputRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.input_relay.RelEvent", _TestRelEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                async with relay:
                    await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(2, -3, 1, 1)])

    async def test_pending_mouse_delta_flushes_before_later_key_event(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice(
            [_TestRelEvent(ecodes.REL_X, 5), _TestKeyEvent(183, _TestKeyEvent.key_down)]
        )
        manager = _FakeHidGadgets()
        order = []
        manager.mouse.move = lambda *args: order.append(("mouse", args))
        relay = InputRelay(input_device, manager, relaying_active=relaying_active)

        async def _record_key(event) -> None:
            order.append(("key", event.scancode))

        with patch("bluetooth_2_usb.input_relay.KeyEvent", _TestKeyEvent):
            with patch("bluetooth_2_usb.input_relay.RelEvent", _TestRelEvent):
                with patch(
                    "bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event
                ):
                    with patch.object(relay, "_process_event_with_retry", side_effect=_record_key):
                        async with relay:
                            await relay.async_relay_events_loop()

        self.assertEqual(order, [("mouse", (5, 0, 0, 0)), ("key", 183)])

    async def test_relative_mouse_events_log_normalized_values(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_X, 2),
                _TestRelEvent(ecodes.REL_Y, -3),
                _TestRelEvent(ecodes.REL_WHEEL_HI_RES, 60),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, -60),
                _TestSynEvent(),
            ]
        )
        relay = InputRelay(input_device, _FakeHidGadgets(), relaying_active=relaying_active)

        with patch("bluetooth_2_usb.input_relay.RelEvent", _TestRelEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                with self.assertLogs("bluetooth_2_usb", level="DEBUG") as logs:
                    async with relay:
                        await relay.async_relay_events_loop()

        output = "\n".join(logs.output)
        self.assertIn("Mouse REL input: code=0 value=2 -> x=2 y=0 wheel=0.0 pan=0.0", output)
        self.assertIn("Mouse REL input: code=1 value=-3 -> x=0 y=-3 wheel=0.0 pan=0.0", output)
        self.assertIn("Mouse REL input: code=11 value=60 -> x=0 y=0 wheel=0.5 pan=0.0", output)
        self.assertIn("Mouse REL input: code=12 value=-60 -> x=0 y=0 wheel=0.0 pan=-0.5", output)

    async def test_large_mouse_deltas_are_split_before_retry_boundary(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_X, 40000),
                _TestRelEvent(ecodes.REL_Y, -40000),
                _TestRelEvent(ecodes.REL_WHEEL, 200),
                _TestRelEvent(ecodes.REL_HWHEEL, -200),
                _TestSynEvent(),
            ]
        )
        manager = _FakeHidGadgets()
        relay = InputRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.input_relay.RelEvent", _TestRelEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                async with relay:
                    await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(32767, -32767, 127, -127), (7233, -7233, 73, -73)])

    async def test_large_mouse_deltas_abort_remaining_chunks_after_write_failure(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        manager = _FakeHidGadgets()
        manager.mouse.move = Mock(side_effect=BrokenPipeError())
        relay = InputRelay(_TestInputDevice([]), manager, relaying_active=relaying_active)

        await relay._process_mouse_delta_with_retry(MouseDelta(40000, -40000, 200, -200))

        manager.mouse.move.assert_called_once_with(32767, -32767, 127, -127)
        self.assertEqual(relay._hid_write_failures, 1)
        self.assertFalse(relaying_active.is_set())

    async def test_high_resolution_horizontal_wheel_accumulates_fractional_steps(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, 60),
                _TestSynEvent(),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, 60),
                _TestSynEvent(),
            ]
        )
        manager = _FakeHidGadgets()
        relay = InputRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.input_relay.RelEvent", _TestRelEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                async with relay:
                    await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(0, 0, 0, 1)])

    async def test_high_resolution_vertical_wheel_accumulates_fractional_steps(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_WHEEL_HI_RES, 60),
                _TestSynEvent(),
                _TestRelEvent(ecodes.REL_WHEEL_HI_RES, 60),
                _TestSynEvent(),
            ]
        )
        manager = _FakeHidGadgets()
        relay = InputRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.input_relay.RelEvent", _TestRelEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                async with relay:
                    await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(0, 0, 1, 0)])

    async def test_high_resolution_horizontal_wheel_suppresses_low_res_fallback(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
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
        manager = _FakeHidGadgets()
        relay = InputRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.input_relay.RelEvent", _TestRelEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                async with relay:
                    await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(0, 0, 0, 1), (0, 0, 0, -1)])

    async def test_high_resolution_vertical_wheel_suppresses_low_res_fallback(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
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
        manager = _FakeHidGadgets()
        relay = InputRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.input_relay.RelEvent", _TestRelEvent):
            with patch("bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event):
                async with relay:
                    await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(0, 0, 1, 0), (0, 0, -1, 0)])

    async def test_inactive_relay_discards_pending_mouse_events(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice(
            [
                _TestRelEvent(ecodes.REL_X, 5),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, 60),
                _TestKeyEvent(183, _TestKeyEvent.key_down),
                _TestRelEvent(ecodes.REL_HWHEEL_HI_RES, 60),
                _TestSynEvent(),
            ]
        )
        manager = _FakeHidGadgets()
        relay = InputRelay(input_device, manager, relaying_active=relaying_active)

        async def deactivate(_event) -> None:
            relaying_active.clear()

        with patch("bluetooth_2_usb.input_relay.RelEvent", _TestRelEvent):
            with patch("bluetooth_2_usb.input_relay.KeyEvent", _TestKeyEvent):
                with patch(
                    "bluetooth_2_usb.input_relay.categorize", side_effect=lambda event: event
                ):
                    with patch.object(relay, "_process_event_with_retry", side_effect=deactivate):
                        async with relay:
                            await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(5, 0, 0, 0)])


class RelaySupervisorHotplugTest(unittest.TestCase):
    def test_device_added_queues_until_supervisor_is_running(self) -> None:
        controller = _relay_supervisor()

        controller._device_added("/dev/input/event7")
        controller._device_added("/dev/input/event7")

        self.assertEqual(controller._pending_add_paths, {"/dev/input/event7"})

        controller._state = _SupervisorState.RUNNING
        controller._schedule_hotplug_open = Mock()

        controller._flush_pending_adds()

        self.assertEqual(controller._pending_add_paths, set())
        controller._schedule_hotplug_open.assert_called_once_with(
            "/dev/input/event7", controller.HOTPLUG_ADD_MAX_RETRIES
        )

    def test_device_removed_drops_queued_startup_add(self) -> None:
        controller = _relay_supervisor()

        controller._device_added("/dev/input/event7")
        controller._device_removed("/dev/input/event7")

        self.assertEqual(controller._pending_add_paths, set())

    def test_device_removed_cancels_active_relay_during_startup(self) -> None:
        controller = _relay_supervisor()
        task = _FakeTaskHandle()
        controller._state = _SupervisorState.STARTING
        controller._active_relays["/dev/input/event7"] = _ActiveRelay(_FakeInputHandle(), task)

        controller._device_removed("/dev/input/event7")

        self.assertEqual(task.cancel_calls, 1)

    def test_device_added_ignores_after_shutdown_requested(self) -> None:
        controller = _relay_supervisor()
        controller.request_shutdown()

        controller._device_added("/dev/input/event7")

        self.assertEqual(controller._pending_add_paths, set())

    def test_request_shutdown_cancels_active_tasks_and_closes_devices(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        hid_gadgets = _FakeHidGadgets()
        controller = _relay_supervisor(hid_gadgets=hid_gadgets, relaying_active=relaying_active)
        task = _FakeTaskHandle()
        device = _FakeInputHandle()
        controller._active_relays["/dev/input/event7"] = _ActiveRelay(device, task)
        controller._pending_add_paths.add("/dev/input/event8")
        controller._state = _SupervisorState.RUNNING

        controller.request_shutdown()

        self.assertTrue(controller._shutdown_event.is_set())
        self.assertIs(controller._state, _SupervisorState.SHUTTING_DOWN)
        self.assertFalse(relaying_active.is_set())
        self.assertEqual(hid_gadgets.release_all_calls, 1)
        self.assertEqual(controller._pending_add_paths, set())
        self.assertEqual(task.cancel_calls, 1)
        self.assertEqual(device.close_calls, 0)
        self.assertIs(controller._active_relays["/dev/input/event7"].task, task)
        self.assertIs(controller._active_relays["/dev/input/event7"].device, device)

        task.finish()

        self.assertEqual(hid_gadgets.release_all_calls, 1)
        self.assertEqual(hid_gadgets.keyboard.release_all_calls, 1)
        self.assertEqual(hid_gadgets.mouse.release_all_calls, 1)
        self.assertEqual(hid_gadgets.consumer.release_calls, 1)

    def test_udc_disconnect_releases_host_visible_hid_state_once(self) -> None:
        relaying_active = asyncio.Event()
        hid_gadgets = _FakeHidGadgets()
        controller = _relay_supervisor(hid_gadgets=hid_gadgets, relaying_active=relaying_active)

        controller._handle_runtime_event(UdcStateChanged("configured"))
        self.assertTrue(relaying_active.is_set())

        controller._handle_runtime_event(UdcStateChanged("not_attached"))
        controller._handle_runtime_event(UdcStateChanged("not_attached"))

        self.assertFalse(relaying_active.is_set())
        self.assertEqual(hid_gadgets.release_all_calls, 1)

    def test_cancel_active_relay_removes_done_task_and_closes_handle(self) -> None:
        controller = _relay_supervisor()
        task = _FakeTaskHandle(done=True)
        device = _FakeInputHandle()
        controller._active_relays["/dev/input/event7"] = _ActiveRelay(device, task)

        controller._cancel_active_relay("/dev/input/event7")

        self.assertEqual(task.cancel_calls, 0)
        self.assertEqual(device.close_calls, 1)
        self.assertNotIn("/dev/input/event7", controller._active_relays)

    def test_relay_task_done_ignores_stale_task(self) -> None:
        controller = _relay_supervisor()
        current_task = _FakeTaskHandle(done=True)
        stale_task = _FakeTaskHandle(done=True)
        device = _FakeInputHandle()
        controller._active_relays["/dev/input/event7"] = _ActiveRelay(device, current_task)

        controller._relay_task_done("/dev/input/event7", stale_task)

        self.assertEqual(device.close_calls, 0)
        self.assertIn("/dev/input/event7", controller._active_relays)

    def test_start_open_device_closes_duplicate_handle(self) -> None:
        controller = _relay_supervisor()
        controller._state = _SupervisorState.RUNNING
        active_device = _FakeInputHandle()
        duplicate_device = _FakeInputHandle()
        controller._active_relays["/dev/input/event7"] = _ActiveRelay(
            active_device, _FakeTaskHandle()
        )

        controller._start_open_device(duplicate_device)

        self.assertEqual(active_device.close_calls, 0)
        self.assertEqual(duplicate_device.close_calls, 1)

    def test_hotplug_open_opens_matching_device_once_and_starts_relay(self) -> None:
        task = _FakeTaskHandle()
        task_group = _FakeTaskGroup(task)
        controller = _relay_supervisor(task_group=task_group, auto_discover=True)
        controller._state = _SupervisorState.RUNNING
        device = _FakeInputHandle()

        with patch(
            "bluetooth_2_usb.relay_supervisor.InputDevice", return_value=device
        ) as input_device:
            controller._schedule_hotplug_open("/dev/input/event7", retries_remaining=0)

        input_device.assert_called_once_with("/dev/input/event7")
        self.assertEqual(device.close_calls, 0)
        self.assertIs(controller._active_relays["/dev/input/event7"].device, device)
        self.assertIs(controller._active_relays["/dev/input/event7"].task, task)
        self.assertEqual(len(task.done_callbacks), 1)

    def test_hotplug_open_retries_until_filters_match(self) -> None:
        task_group = _FakeTaskGroup()
        controller = _relay_supervisor(task_group=task_group, device_identifiers=["target"])
        controller._state = _SupervisorState.RUNNING
        device = _FakeInputHandle(name="not ready")

        with patch("bluetooth_2_usb.relay_supervisor.InputDevice", return_value=device):
            controller._schedule_hotplug_open("/dev/input/event7", retries_remaining=2)

        self.assertEqual(device.close_calls, 1)
        self.assertEqual(len(task_group.created), 1)
        _coroutine, task_name = task_group.created[0]
        self.assertEqual(task_name, "hotplug open retry /dev/input/event7")
        self.assertIn("/dev/input/event7", controller._pending_hotplug_open_tasks)
        self.assertEqual(controller._active_relays, {})

    def test_device_removed_cancels_delayed_hotplug_open(self) -> None:
        task_group = _FakeTaskGroup()
        controller = _relay_supervisor(task_group=task_group, device_identifiers=["target"])
        controller._state = _SupervisorState.RUNNING
        device = _FakeInputHandle(name="not ready")

        with patch("bluetooth_2_usb.relay_supervisor.InputDevice", return_value=device):
            controller._schedule_hotplug_open("/dev/input/event7", retries_remaining=2)

        controller._device_removed("/dev/input/event7")

        self.assertEqual(task_group.task.cancel_calls, 1)
        self.assertNotIn("/dev/input/event7", controller._pending_hotplug_open_tasks)


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

        with patch("bluetooth_2_usb.relay_supervisor.list_input_devices", return_value=[device]):
            with patch(
                "bluetooth_2_usb.relay_supervisor.InputDevice",
                side_effect=AssertionError("startup device was reopened"),
            ):
                with patch("bluetooth_2_usb.relay_supervisor.InputRelay", WaitingInputRelay):
                    events: asyncio.Queue = asyncio.Queue()
                    async with asyncio.TaskGroup() as task_group:
                        controller = _relay_supervisor(task_group=task_group, auto_discover=True)
                        relay_task = task_group.create_task(controller.run(events))
                        await asyncio.wait_for(relay_ready.wait(), timeout=1)
                        controller.request_shutdown()
                        await asyncio.wait_for(relay_task, timeout=1)

        self.assertEqual(device.close_calls, 1)
        self.assertEqual(controller._active_relays, {})
        self.assertIs(controller._state, _SupervisorState.STOPPED)

    async def test_run_returns_when_shutdown_requested_before_start(self) -> None:
        with patch("bluetooth_2_usb.relay_supervisor.list_input_devices") as list_devices:
            async with asyncio.TaskGroup() as task_group:
                controller = _relay_supervisor(task_group=task_group, auto_discover=True)
                controller.request_shutdown()
                await controller.run(asyncio.Queue())

        list_devices.assert_not_called()
        self.assertIs(controller._state, _SupervisorState.STOPPED)

    async def test_run_cannot_restart_after_stop(self) -> None:
        async with asyncio.TaskGroup() as task_group:
            controller = _relay_supervisor(task_group=task_group, auto_discover=True)
            controller.request_shutdown()
            await controller.run(asyncio.Queue())

        with self.assertRaisesRegex(RuntimeError, "cannot be restarted"):
            await controller.run(asyncio.Queue())

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

        controller = _relay_supervisor()
        device = SimpleNamespace(path="/dev/input/event7", name="failure device", close=Mock())

        with patch("bluetooth_2_usb.relay_supervisor.InputRelay", FailingInputRelay):
            with self.assertRaises(OSError) as raised:
                await controller._run_input_relay(device)

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

        controller = _relay_supervisor()
        device = SimpleNamespace(path="/dev/input/event7", name="removed device", close=Mock())

        with patch("bluetooth_2_usb.relay_supervisor.InputRelay", FailingInputRelay):
            await controller._run_input_relay(device)

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

        controller = _relay_supervisor()
        device = SimpleNamespace(path="/dev/input/event7", name="failure device", close=Mock())

        with patch("bluetooth_2_usb.relay_supervisor.InputRelay", FailingInputRelay):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await controller._run_input_relay(device)

        device.close.assert_not_called()

    async def test_task_group_failures_are_reraised_after_logging(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        hid_gadgets = _FakeHidGadgets()

        with patch("bluetooth_2_usb.relay_supervisor.list_input_devices", return_value=[]):
            with self.assertRaises(ExceptionGroup) as raised:
                events: asyncio.Queue = asyncio.Queue()
                await events.put(DeviceAdded("/dev/input/event7"))
                async with asyncio.TaskGroup() as task_group:
                    controller = _relay_supervisor(
                        hid_gadgets=hid_gadgets,
                        relaying_active=relaying_active,
                        task_group=task_group,
                    )
                    controller._handle_runtime_event = Mock(side_effect=RuntimeError("boom"))
                    await controller.run(events)

        self.assertIsInstance(raised.exception.exceptions[0], RuntimeError)
        self.assertEqual(str(raised.exception.exceptions[0]), "boom")
        self.assertFalse(relaying_active.is_set())
        self.assertEqual(hid_gadgets.release_all_calls, 1)
