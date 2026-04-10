import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bluetooth_2_usb.relay import GadgetManager, RuntimeMonitor, ShortcutToggler


class _FakeKeyboard:
    def __init__(self) -> None:
        self.release_all_calls = 0

    def release_all(self) -> None:
        self.release_all_calls += 1


class _FakeMouse:
    def __init__(self) -> None:
        self.release_all_calls = 0

    def release_all(self) -> None:
        self.release_all_calls += 1


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


class GadgetManagerProfileTest(unittest.TestCase):
    def test_compat_profile_keeps_boot_keyboard_and_real_mouse(self) -> None:
        fake_device = SimpleNamespace(
            BOOT_KEYBOARD="boot-keyboard",
            KEYBOARD="keyboard",
            MOUSE="mouse",
            CONSUMER_CONTROL="consumer",
        )

        with patch(
            "bluetooth_2_usb.relay.import_module",
            return_value=SimpleNamespace(Device=fake_device),
        ):
            devices = GadgetManager("compat")._requested_devices()

        self.assertEqual(devices, ["boot-keyboard", "mouse", "consumer"])

    def test_extended_profile_uses_report_id_devices(self) -> None:
        fake_device = SimpleNamespace(
            BOOT_KEYBOARD="boot-keyboard",
            KEYBOARD="keyboard",
            MOUSE="mouse",
            CONSUMER_CONTROL="consumer",
        )

        with patch(
            "bluetooth_2_usb.relay.import_module",
            return_value=SimpleNamespace(Device=fake_device),
        ):
            devices = GadgetManager("extended")._requested_devices()

        self.assertEqual(devices, ["keyboard", "mouse", "consumer"])
