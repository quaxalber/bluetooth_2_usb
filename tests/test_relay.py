import asyncio
import errno
import re
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import usb_hid

from bluetooth_2_usb.evdev import ecodes, evdev_to_usb_hid
from bluetooth_2_usb.extended_mouse import ExtendedMouse
from bluetooth_2_usb.gadget_config import rebuild_gadget
from bluetooth_2_usb.hid_layout import (
    DEFAULT_KEYBOARD_DESCRIPTOR,
    DEFAULT_MOUSE_DESCRIPTOR,
    GadgetHidDevice,
    build_default_layout,
)
from bluetooth_2_usb.relay import (
    DeviceRelay,
    GadgetManager,
    RelayController,
    RuntimeMonitor,
    ShortcutToggler,
)


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


class _FakeGadgetManager:
    def __init__(self) -> None:
        self.keyboard = _FakeKeyboard()
        self.mouse = _FakeMouse()

    def get_keyboard(self):
        return self.keyboard

    def get_mouse(self):
        return self.mouse


class _FakeRelayController:
    def __init__(self) -> None:
        self.added = []
        self.removed = []

    def schedule_add_device(self, device_path: str) -> None:
        self.added.append(device_path)

    def schedule_remove_device(self, device_path: str) -> None:
        self.removed.append(device_path)


class _FakeMonitor:
    def filter_by(self, *_args) -> None:
        return None


class _FakeObserver:
    def __init__(self, _monitor, _callback) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


class _FakeLoop:
    def __init__(self) -> None:
        self.soon_threadsafe_calls = []
        self.soon_calls = []

    def call_soon_threadsafe(self, callback, *args) -> None:
        self.soon_threadsafe_calls.append((callback, args))

    def call_soon(self, callback, *args) -> None:
        self.soon_calls.append((callback, args))


class _FakeTaskHandle:
    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1

    def done(self) -> bool:
        return False


class _FakeInputHandle:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _FakeGrabInputDevice:
    def __init__(self, *, ungrab_errno: int | None = None) -> None:
        self.path = "/dev/input/event-grab"
        self.name = "grab-test-device"
        self.close_calls = 0
        self.grab_calls = 0
        self.ungrab_calls = 0
        self._ungrab_errno = ungrab_errno

    def grab(self) -> None:
        self.grab_calls += 1

    def ungrab(self) -> None:
        self.ungrab_calls += 1
        if self._ungrab_errno is not None:
            raise OSError(self._ungrab_errno, "Bad file descriptor")

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

        self.assertEqual(
            device.sent,
            [
                bytes([0x00, 0x2C, 0x01, 0xD4, 0xFE, 0x01, 0xFF]),
            ],
        )

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


class ShortcutTogglerTest(unittest.TestCase):
    def test_shortcut_events_are_suppressed_and_toggle_relays(self) -> None:
        event_state = asyncio.Event()
        toggler = ShortcutToggler(
            shortcut_keys={"KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_F12"},
            relaying_active=event_state,
            gadget_manager=_FakeGadgetManager(),
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


class RuntimeMonitorTest(unittest.TestCase):
    def test_runtime_monitor_routes_hotplug_events(self) -> None:
        relay_controller = _FakeRelayController()
        relaying_active = asyncio.Event()

        with patch("bluetooth_2_usb.relay.pyudev.Context", return_value=object()):
            with patch(
                "bluetooth_2_usb.relay.pyudev.Monitor.from_netlink",
                return_value=_FakeMonitor(),
            ):
                with patch(
                    "bluetooth_2_usb.relay.pyudev.MonitorObserver",
                    side_effect=lambda monitor, callback: _FakeObserver(
                        monitor, callback
                    ),
                ):
                    monitor = RuntimeMonitor(
                        relay_controller=relay_controller,
                        relaying_active=relaying_active,
                    )

        monitor._udev_event_callback(
            "add", SimpleNamespace(device_node="/dev/input/event7")
        )
        monitor._udev_event_callback(
            "remove", SimpleNamespace(device_node="/dev/input/event7")
        )
        monitor._handle_state_change("configured")
        self.assertTrue(relaying_active.is_set())
        monitor._handle_state_change("not_attached")
        self.assertFalse(relaying_active.is_set())

        self.assertEqual(relay_controller.added, ["/dev/input/event7"])
        self.assertEqual(relay_controller.removed, ["/dev/input/event7"])


class GadgetManagerLayoutTest(unittest.TestCase):
    def test_requested_devices_use_default_layout(self) -> None:
        with patch(
            "bluetooth_2_usb.relay.build_default_layout",
            return_value=SimpleNamespace(devices=("keyboard", "mouse", "consumer")),
        ):
            devices = GadgetManager()._requested_devices()

        self.assertEqual(devices, ["keyboard", "mouse", "consumer"])

    def test_default_layout_uses_strict_keyboard_and_extended_mouse_consumer(
        self,
    ) -> None:
        layout = build_default_layout()

        self.assertEqual(len(layout.devices), 3)
        self.assertEqual(
            bytes(layout.devices[0].descriptor), DEFAULT_KEYBOARD_DESCRIPTOR
        )
        self.assertEqual(bytes(layout.devices[1].descriptor), DEFAULT_MOUSE_DESCRIPTOR)
        self.assertEqual(tuple(layout.devices[1].report_ids), (0,))
        self.assertEqual(tuple(layout.devices[1].in_report_lengths), (7,))
        self.assertEqual(tuple(layout.devices[1].out_report_lengths), (0,))
        self.assertEqual(layout.devices[1].configfs_report_length, 8)
        self.assertEqual(
            bytes(layout.devices[2].descriptor),
            bytes(usb_hid.Device.CONSUMER_CONTROL.descriptor),
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
                    "'subclass' and 'protocol'"
                )

        with patch.object(usb_hid.Device, "__init__", fake_device_init):
            GadgetHidDevice.from_existing(
                usb_hid.Device.BOOT_KEYBOARD,
                function_index=0,
                protocol=1,
                subclass=1,
            )

        self.assertEqual(len(init_calls), 1)
        self.assertEqual(init_calls[0]["protocol"], 1)
        self.assertEqual(init_calls[0]["subclass"], 1)

    def test_prune_stale_hidg_nodes_removes_regular_files(self) -> None:
        manager = GadgetManager()
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "hidg1"
            stale.write_text("stale", encoding="utf-8")
            with patch.object(manager, "_expected_hidg_paths", return_value=(stale,)):
                manager._prune_stale_hidg_nodes()
            self.assertFalse(stale.exists())

    def test_validate_hidg_nodes_rejects_regular_files(self) -> None:
        manager = GadgetManager()
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "hidg1"
            bad.write_text("not-a-device", encoding="utf-8")
            with patch.object(manager, "_expected_hidg_paths", return_value=(bad,)):
                with self.assertRaisesRegex(RuntimeError, re.escape(str(bad))):
                    manager._validate_hidg_nodes(
                        timeout_sec=0,
                        poll_interval_sec=0,
                    )

    def test_validate_hidg_nodes_waits_for_delayed_nodes(self) -> None:
        manager = GadgetManager()

        with patch.object(
            manager,
            "_collect_invalid_hidg_nodes",
            side_effect=[["/dev/hidg0 (missing)"], []],
        ) as collect_invalid:
            with patch("bluetooth_2_usb.relay.time.sleep") as sleep:
                manager._validate_hidg_nodes(timeout_sec=0.1, poll_interval_sec=0.01)

        self.assertEqual(collect_invalid.call_count, 2)
        sleep.assert_called_once_with(0.01)

    def test_collect_invalid_hidg_nodes_rejects_unopenable_character_devices(
        self,
    ) -> None:
        manager = GadgetManager()
        path = Path("/dev/hidg0")
        stats = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_rdev=0)

        with patch.object(manager, "_expected_hidg_paths", return_value=(path,)):
            with patch.object(Path, "stat", return_value=stats):
                with patch(
                    "bluetooth_2_usb.relay.os.minor",
                    return_value=0,
                    create=True,
                ):
                    with patch("bluetooth_2_usb.relay.os.O_NONBLOCK", 0, create=True):
                        with patch(
                            "bluetooth_2_usb.relay.os.open",
                            side_effect=OSError(errno.ENODEV, "No such device"),
                        ):
                            invalid_paths = manager._collect_invalid_hidg_nodes()

        self.assertEqual(invalid_paths, [f"{path} (No such device)"])

    def test_rebuild_gadget_writes_default_power_and_identity(self) -> None:
        layout = build_default_layout()
        with tempfile.TemporaryDirectory() as tmpdir:
            gadget_root = Path(tmpdir) / "usb_gadget" / "adafruit-blinka"
            with patch("bluetooth_2_usb.gadget_config.GADGET_ROOT", gadget_root):
                with patch(
                    "bluetooth_2_usb.gadget_config._resolve_udc_name",
                    return_value="dummy.udc",
                ):
                    with patch.object(usb_hid, "gadget_root", str(gadget_root)):
                        rebuild_gadget(layout)

            self.assertEqual(
                (gadget_root / "strings/0x409/product")
                .read_text(encoding="utf-8")
                .strip(),
                "USB Combo Device",
            )
            self.assertEqual(
                (gadget_root / "strings/0x409/serialnumber")
                .read_text(encoding="utf-8")
                .strip(),
                "213374badcafe",
            )
            self.assertEqual(
                (gadget_root / "bcdDevice").read_text(encoding="utf-8").strip(),
                "0x0205",
            )
            self.assertEqual(
                (gadget_root / "configs/c.1/MaxPower")
                .read_text(encoding="utf-8")
                .strip(),
                "100",
            )
            self.assertEqual(
                (gadget_root / "configs/c.1/bmAttributes")
                .read_text(encoding="utf-8")
                .strip(),
                "0xa0",
            )
            self.assertEqual(
                (gadget_root / "configs/c.1/strings/0x409/configuration")
                .read_text(encoding="utf-8")
                .strip(),
                "Config 1: HID relay",
            )
            self.assertEqual(
                (gadget_root / "max_speed").read_text(encoding="utf-8").strip(),
                "high-speed",
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

            with patch("bluetooth_2_usb.gadget_config.GADGET_ROOT", gadget_root):
                with patch(
                    "bluetooth_2_usb.gadget_config._resolve_udc_name",
                    return_value="dummy.udc",
                ):
                    with patch.object(usb_hid, "gadget_root", str(gadget_root)):
                        with patch.object(type(keyboard_wakeup), "exists", fake_exists):
                            rebuild_gadget(layout)

            self.assertEqual(
                keyboard_wakeup.read_text(encoding="utf-8").strip(),
                "1",
            )
            self.assertEqual(
                mouse_wakeup.read_text(encoding="utf-8").strip(),
                "0",
            )
            self.assertFalse(
                (gadget_root / "functions/hid.usb2/wakeup_on_write").exists()
            )

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
            base_device,
            function_index=1,
            protocol=0,
            subclass=0,
        )

        self.assertTrue(cloned.wakeup_on_write)
        self.assertEqual(cloned.configfs_report_length, 8)


class DeviceRelayTest(unittest.IsolatedAsyncioTestCase):
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
        relay = DeviceRelay(
            input_device,
            _FakeGadgetManager(),
            relaying_active=relaying_active,
        )

        async def _slow_process(event) -> None:
            seen.append((event.scancode, event.keystate))
            await asyncio.sleep(0.001)

        with patch("bluetooth_2_usb.relay.KeyEvent", _TestKeyEvent):
            with patch(
                "bluetooth_2_usb.relay.categorize", side_effect=lambda event: event
            ):
                with patch.object(
                    relay, "_process_event_with_retry", side_effect=_slow_process
                ):
                    async with relay:
                        await relay.async_relay_events_loop()

        self.assertEqual(seen, [(183, 1), (183, 0), (184, 1), (184, 0)])

    async def test_aexit_ignores_ebadf_from_ungrab_on_disappeared_device(self) -> None:
        input_device = _FakeGrabInputDevice(ungrab_errno=errno.EBADF)
        relay = DeviceRelay(
            input_device,
            _FakeGadgetManager(),
            grab_device=True,
            relaying_active=asyncio.Event(),
        )

        async with relay:
            self.assertTrue(relay._currently_grabbed)

        self.assertEqual(input_device.grab_calls, 1)
        self.assertEqual(input_device.ungrab_calls, 1)
        self.assertEqual(input_device.close_calls, 1)
        self.assertFalse(relay._currently_grabbed)

    async def test_input_device_removal_stops_reader_without_failing_task_group(
        self,
    ) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        seen: list[tuple[int, int]] = []
        input_device = _TestInputDevice(
            [
                _TestKeyEvent(183, _TestKeyEvent.key_down),
                _TestKeyEvent(183, _TestKeyEvent.key_up),
            ],
            removal_errno=errno.ENODEV,
        )
        relay = DeviceRelay(
            input_device,
            _FakeGadgetManager(),
            relaying_active=relaying_active,
        )

        async def _record_process(event) -> None:
            seen.append((event.scancode, event.keystate))

        with patch("bluetooth_2_usb.relay.KeyEvent", _TestKeyEvent):
            with patch(
                "bluetooth_2_usb.relay.categorize", side_effect=lambda event: event
            ):
                with patch.object(
                    relay, "_process_event_with_retry", side_effect=_record_process
                ):
                    async with relay:
                        await relay.async_relay_events_loop()

        self.assertEqual(seen, [(183, 1), (183, 0)])

    async def test_broken_pipe_clears_relaying_active_when_hid_write_fails(
        self,
    ) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        input_device = _TestInputDevice([_TestKeyEvent(183, _TestKeyEvent.key_down)])
        relay = DeviceRelay(
            input_device,
            _FakeGadgetManager(),
            relaying_active=relaying_active,
        )

        with patch("bluetooth_2_usb.relay.KeyEvent", _TestKeyEvent):
            with patch(
                "bluetooth_2_usb.relay.categorize", side_effect=lambda event: event
            ):
                with patch(
                    "bluetooth_2_usb.relay.relay_event",
                    side_effect=BrokenPipeError(),
                ):
                    async with relay:
                        await relay.async_relay_events_loop()

        self.assertFalse(relaying_active.is_set())
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
        manager = _FakeGadgetManager()
        relay = DeviceRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.relay.RelEvent", _TestRelEvent):
            with patch(
                "bluetooth_2_usb.relay.categorize", side_effect=lambda event: event
            ):
                async with relay:
                    await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(2, -3, 1, 1)])

    async def test_high_resolution_horizontal_wheel_accumulates_fractional_steps(
        self,
    ) -> None:
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
        manager = _FakeGadgetManager()
        relay = DeviceRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.relay.RelEvent", _TestRelEvent):
            with patch(
                "bluetooth_2_usb.relay.categorize", side_effect=lambda event: event
            ):
                async with relay:
                    await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(0, 0, 0, 1)])

    async def test_high_resolution_vertical_wheel_accumulates_fractional_steps(
        self,
    ) -> None:
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
        manager = _FakeGadgetManager()
        relay = DeviceRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.relay.RelEvent", _TestRelEvent):
            with patch(
                "bluetooth_2_usb.relay.categorize", side_effect=lambda event: event
            ):
                async with relay:
                    await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(0, 0, 1, 0)])

    async def test_high_resolution_horizontal_wheel_suppresses_low_res_fallback(
        self,
    ) -> None:
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
        manager = _FakeGadgetManager()
        relay = DeviceRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.relay.RelEvent", _TestRelEvent):
            with patch(
                "bluetooth_2_usb.relay.categorize", side_effect=lambda event: event
            ):
                async with relay:
                    await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(0, 0, 0, 1), (0, 0, 0, -1)])

    async def test_high_resolution_vertical_wheel_suppresses_low_res_fallback(
        self,
    ) -> None:
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
        manager = _FakeGadgetManager()
        relay = DeviceRelay(input_device, manager, relaying_active=relaying_active)

        with patch("bluetooth_2_usb.relay.RelEvent", _TestRelEvent):
            with patch(
                "bluetooth_2_usb.relay.categorize", side_effect=lambda event: event
            ):
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
        manager = _FakeGadgetManager()
        relay = DeviceRelay(input_device, manager, relaying_active=relaying_active)

        async def deactivate(_event) -> None:
            relaying_active.clear()

        with patch("bluetooth_2_usb.relay.RelEvent", _TestRelEvent):
            with patch("bluetooth_2_usb.relay.KeyEvent", _TestKeyEvent):
                with patch(
                    "bluetooth_2_usb.relay.categorize", side_effect=lambda event: event
                ):
                    with patch.object(
                        relay, "_process_event_with_retry", side_effect=deactivate
                    ):
                        async with relay:
                            await relay.async_relay_events_loop()

        self.assertEqual(manager.mouse.moves, [(5, 0, 0, 0)])


class RelayControllerHotplugTest(unittest.TestCase):
    def test_schedule_add_device_queues_until_controller_is_ready(self) -> None:
        controller = RelayController(
            gadget_manager=_FakeGadgetManager(),
            device_identifiers=[],
        )

        controller.schedule_add_device("/dev/input/event7")

        self.assertEqual(controller._pending_add_paths, ["/dev/input/event7"])

        fake_loop = _FakeLoop()
        controller._loop = fake_loop
        controller._task_group = object()
        controller._hotplug_ready = True

        controller._flush_pending_adds()

        self.assertEqual(controller._pending_add_paths, [])
        self.assertEqual(len(fake_loop.soon_calls), 1)
        callback, args = fake_loop.soon_calls[0]
        self.assertIs(callback.__func__, controller._schedule_add_retry.__func__)
        self.assertEqual(
            args,
            ("/dev/input/event7", controller.HOTPLUG_ADD_MAX_RETRIES),
        )

    def test_schedule_remove_device_drops_queued_startup_add(self) -> None:
        controller = RelayController(
            gadget_manager=_FakeGadgetManager(),
            device_identifiers=[],
        )

        controller.schedule_add_device("/dev/input/event7")
        controller.schedule_remove_device("/dev/input/event7")

        self.assertEqual(controller._pending_add_paths, [])

    def test_request_shutdown_cancels_active_tasks_and_closes_devices(self) -> None:
        relaying_active = asyncio.Event()
        relaying_active.set()
        controller = RelayController(
            gadget_manager=_FakeGadgetManager(),
            device_identifiers=[],
            relaying_active=relaying_active,
        )
        task = _FakeTaskHandle()
        device = _FakeInputHandle()
        controller._active_tasks["/dev/input/event7"] = task
        controller._active_devices["/dev/input/event7"] = device
        controller._pending_add_paths.append("/dev/input/event8")
        controller._hotplug_ready = True

        controller.request_shutdown()

        self.assertTrue(controller._shutdown_event.is_set())
        self.assertFalse(controller._hotplug_ready)
        self.assertFalse(relaying_active.is_set())
        self.assertEqual(controller._pending_add_paths, [])
        self.assertEqual(task.cancel_calls, 1)
        self.assertEqual(device.close_calls, 0)
