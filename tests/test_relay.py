import asyncio
import errno
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bluetooth_2_usb.relay import (
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
    def test_compat_profile_uses_boot_mouse_then_keyboard(self) -> None:
        fake_device = SimpleNamespace(
            BOOT_KEYBOARD="boot-keyboard",
            KEYBOARD="keyboard",
            BOOT_MOUSE="boot-mouse",
            MOUSE="mouse",
            CONSUMER_CONTROL="consumer",
        )

        with patch(
            "bluetooth_2_usb.relay.import_module",
            return_value=SimpleNamespace(Device=fake_device),
        ):
            devices = GadgetManager("compat")._requested_devices()

        self.assertEqual(devices, ["boot-mouse", "keyboard", "consumer"])

    def test_extended_profile_uses_report_id_devices(self) -> None:
        fake_device = SimpleNamespace(
            BOOT_KEYBOARD="boot-keyboard",
            KEYBOARD="keyboard",
            BOOT_MOUSE="boot-mouse",
            MOUSE="mouse",
            CONSUMER_CONTROL="consumer",
        )

        with patch(
            "bluetooth_2_usb.relay.import_module",
            return_value=SimpleNamespace(Device=fake_device),
        ):
            devices = GadgetManager("extended")._requested_devices()

        self.assertEqual(devices, ["keyboard", "mouse", "consumer"])

    def test_boot_keyboard_profile_uses_boot_keyboard_then_mouse(self) -> None:
        fake_device = SimpleNamespace(
            BOOT_KEYBOARD="boot-keyboard",
            KEYBOARD="keyboard",
            BOOT_MOUSE="boot-mouse",
            MOUSE="mouse",
            CONSUMER_CONTROL="consumer",
        )

        with patch(
            "bluetooth_2_usb.relay.import_module",
            return_value=SimpleNamespace(Device=fake_device),
        ):
            devices = GadgetManager("boot_keyboard")._requested_devices()

        self.assertEqual(devices, ["boot-keyboard", "mouse", "consumer"])

    def test_prune_stale_hidg_nodes_removes_regular_files(self) -> None:
        manager = GadgetManager("compat")
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "hidg1"
            stale.write_text("stale", encoding="utf-8")
            with patch.object(manager, "_expected_hidg_paths", return_value=(stale,)):
                manager._prune_stale_hidg_nodes()
            self.assertFalse(stale.exists())

    def test_validate_hidg_nodes_rejects_regular_files(self) -> None:
        manager = GadgetManager("compat")
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "hidg1"
            bad.write_text("not-a-device", encoding="utf-8")
            with patch.object(manager, "_expected_hidg_paths", return_value=(bad,)):
                with self.assertRaisesRegex(RuntimeError, str(bad)):
                    manager._validate_hidg_nodes(
                        timeout_sec=0,
                        poll_interval_sec=0,
                    )

    def test_validate_hidg_nodes_waits_for_delayed_nodes(self) -> None:
        manager = GadgetManager("compat")

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
        manager = GadgetManager("compat")
        path = Path("/dev/hidg0")
        stats = SimpleNamespace(
            st_mode=stat.S_IFCHR | 0o600, st_rdev=os.makedev(236, 0)
        )

        with patch.object(manager, "_expected_hidg_paths", return_value=(path,)):
            with patch.object(Path, "stat", return_value=stats):
                with patch(
                    "bluetooth_2_usb.relay.os.open",
                    side_effect=OSError(errno.ENODEV, "No such device"),
                ):
                    invalid_paths = manager._collect_invalid_hidg_nodes()

        self.assertEqual(invalid_paths, ["/dev/hidg0 (No such device)"])


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

        self.assertTrue(controller._cancelled)
        self.assertFalse(controller._hotplug_ready)
        self.assertFalse(relaying_active.is_set())
        self.assertEqual(controller._pending_add_paths, [])
        self.assertEqual(task.cancel_calls, 1)
        self.assertEqual(device.close_calls, 1)
