import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bluetooth_2_usb.evdev.ecodes import ecodes
from bluetooth_2_usb.inputs.battery import extract_bluetooth_mac, read_device_battery_percent
from bluetooth_2_usb.inputs.mqtt import MqttConfig, build_ha_battery_messages, load_mqtt_config
from bluetooth_2_usb.relay.leds import KeyboardLedMirror


class _LedDevice:
    def __init__(self, path="/dev/input/event1", leds=(ecodes.LED_NUML, ecodes.LED_CAPSL, ecodes.LED_SCROLLL)):
        self.path = path
        self._leds = list(leds)
        self.calls = []

    def capabilities(self, verbose=False):
        return {ecodes.EV_LED: self._leds} if self._leds else {}

    def set_led(self, code, value):
        self.calls.append((code, value))


class KeyboardLedMirrorTest(unittest.TestCase):
    def test_report_is_applied_to_registered_keyboard(self):
        mirror = KeyboardLedMirror(None)
        device = _LedDevice()
        mirror.register(device)

        mirror.handle_report(bytes([0x02]))

        self.assertEqual(device.calls, [(ecodes.LED_NUML, 0), (ecodes.LED_CAPSL, 1), (ecodes.LED_SCROLLL, 0)])

    def test_unchanged_report_is_ignored_and_new_device_gets_current_state(self):
        mirror = KeyboardLedMirror(None)
        mirror.handle_report(bytes([0x01]))
        mirror.handle_report(bytes([0x01]))

        device = _LedDevice(leds=(ecodes.LED_NUML,))
        mirror.register(device)

        self.assertEqual(device.calls, [(ecodes.LED_NUML, 1)])

    def test_devices_without_leds_and_unregistered_devices_are_skipped(self):
        mirror = KeyboardLedMirror(None)
        mouse = _LedDevice(path="/dev/input/event2", leds=())
        keyboard = _LedDevice()
        mirror.register(mouse)
        mirror.register(keyboard)
        mirror.unregister(keyboard.path)

        mirror.handle_report(bytes([0x07]))

        self.assertEqual(mouse.calls, [])
        self.assertEqual(keyboard.calls, [])

    def test_blink_warning_flashes_and_restores_host_led_state(self):
        mirror = KeyboardLedMirror(None)
        device = _LedDevice(leds=(ecodes.LED_CAPSL,))
        mirror.register(device)
        mirror.handle_report(bytes([0x02]))
        device.calls.clear()

        with patch("bluetooth_2_usb.relay.leds.asyncio.sleep", new=AsyncMock()), self.assertRaises(StopIteration):
            mirror.blink_warning(count=1, interval_sec=0.0).send(None)

        self.assertEqual(device.calls, [(ecodes.LED_CAPSL, 1), (ecodes.LED_CAPSL, 0), (ecodes.LED_CAPSL, 1)])

    def test_read_device_battery_percent_from_sysfs_power_supply(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_root = Path(tmp) / "input"
            power_root = Path(tmp) / "power_supply"
            supply_dir = power_root / "hid-aa-bb-cc-dd-ee-ff-battery"
            supply_dir.mkdir(parents=True)
            (supply_dir / "capacity").write_text("12\n", encoding="utf-8")
            device = SimpleNamespace(path="/dev/input/event9", uniq="AA-BB-CC-DD-EE-FF", phys="")

            self.assertEqual(extract_bluetooth_mac(device), "aa:bb:cc:dd:ee:ff")
            battery = read_device_battery_percent(device, sys_class_input=input_root, sys_class_power_supply=power_root)
            self.assertEqual(battery, 12)

    def test_supervisor_low_battery_warns_once_and_blinks_leds(self):
        from bluetooth_2_usb.relay.gate import RelayGate
        from bluetooth_2_usb.relay.supervisor import RelaySupervisor

        task_group = SimpleNamespace(create_task=lambda coro, name=None: coro.close())
        gadgets = SimpleNamespace(keyboard_hidg_path=None)
        supervisor = RelaySupervisor(gadgets, RelayGate(), task_group)
        keyboard = _LedDevice(leds=(ecodes.LED_CAPSL,))
        supervisor._led_mirror.register(keyboard)
        mouse = SimpleNamespace(path="/dev/input/event8", name="BT Mouse", uniq="aa:bb:cc:dd:ee:ff", phys="")

        with (
            patch("bluetooth_2_usb.relay.supervisor.read_device_battery_percent", return_value=10),
            patch("bluetooth_2_usb.relay.leds.asyncio.sleep", new=AsyncMock()),
            self.assertLogs("bluetooth_2_usb", level="WARNING") as logs,
        ):
            with self.assertRaises(StopIteration):
                supervisor._check_device_battery(mouse).send(None)
            with self.assertRaises(StopIteration):
                supervisor._check_device_battery(mouse).send(None)

        self.assertEqual(len(logs.output), 1)
        self.assertIn("Low battery on BT Mouse (/dev/input/event8): 10%", logs.output[0])
        self.assertTrue(keyboard.calls)

    def test_mqtt_config_and_home_assistant_discovery_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "bluetooth_2_usb_mqtt"
            text = "B2U_MQTT_HOST=homeassistant.local\nB2U_MQTT_USERNAME=mqtt\nB2U_MQTT_PASSWORD=secret\n"
            env_file.write_text(text, encoding="utf-8")
            config = load_mqtt_config(env_file)

        self.assertEqual(config, MqttConfig(host="homeassistant.local", username="mqtt", password="secret"))
        device = SimpleNamespace(path="/dev/input/event5", name="MX Keys", uniq="AA:BB:CC:DD:EE:FF", phys="")
        messages = build_ha_battery_messages(config, device, 85)
        self.assertEqual(messages[0][0], "homeassistant/sensor/bluetooth_2_usb_aabbccddeeff/battery/config")
        self.assertIn('"unique_id":"bluetooth_2_usb_aabbccddeeff_battery"', messages[0][1])
        self.assertEqual(messages[1], ("bluetooth_2_usb/aabbccddeeff/battery", "85"))


if __name__ == "__main__":
    unittest.main()
