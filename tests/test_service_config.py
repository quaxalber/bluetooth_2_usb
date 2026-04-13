import tempfile
import unittest
from pathlib import Path

from bluetooth_2_usb.service_config import (
    ServiceConfigError,
    build_cli_argv,
    build_shell_command,
    load_service_config,
)


class ServiceConfigTest(unittest.TestCase):
    def test_loads_structured_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    [
                        "B2U_AUTO_DISCOVER=0",
                        "B2U_GRAB_DEVICES=1",
                        "B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12",
                        "B2U_HID_PROFILE=nonboot",
                        "B2U_LOG_TO_FILE=1",
                        "B2U_LOG_PATH='/tmp/custom log.txt'",
                        "B2U_DEBUG=1",
                        "B2U_DEVICE_IDS='mouse, keyboard'",
                        "B2U_UDC_PATH=/tmp/udc",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_service_config(env_file)

        self.assertFalse(config.auto_discover)
        self.assertTrue(config.grab_devices)
        self.assertEqual(config.hid_profile, "nonboot")
        self.assertTrue(config.log_to_file)
        self.assertEqual(config.log_path, "/tmp/custom log.txt")
        self.assertTrue(config.debug)
        self.assertEqual(config.device_ids, ["mouse", "keyboard"])
        self.assertEqual(config.udc_path, "/tmp/udc")

    def test_unknown_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("NOPE=1\n", encoding="utf-8")

            with self.assertRaises(ServiceConfigError):
                load_service_config(env_file)

    def test_builds_cli_argv_and_shell_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    [
                        "B2U_AUTO_DISCOVER=1",
                        "B2U_GRAB_DEVICES=1",
                        "B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12",
                        "B2U_HID_PROFILE=boot_mouse",
                        "B2U_LOG_TO_FILE=1",
                        "B2U_LOG_PATH='/tmp/debug log.txt'",
                        "B2U_DEBUG=0",
                        "B2U_DEVICE_IDS='MX Keys'",
                        "B2U_UDC_PATH=",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_service_config(env_file)
            argv = build_cli_argv(config, append_debug=True)
            command = build_shell_command(
                "python -m bluetooth_2_usb", env_file=env_file, append_debug=True
            )

        self.assertIn("--auto_discover", argv)
        self.assertIn("--grab_devices", argv)
        self.assertIn("--debug", argv)
        self.assertIn("/tmp/debug log.txt", argv)
        self.assertIn("'MX Keys'", command)

    def test_accepts_boot_keyboard_hid_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "B2U_HID_PROFILE=boot_keyboard\n",
                encoding="utf-8",
            )

            config = load_service_config(env_file)
            argv = build_cli_argv(config)

        self.assertEqual(config.hid_profile, "boot_keyboard")
        self.assertIn("boot_keyboard", argv)

    def test_defaults_to_boot_keyboard_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "missing"

            config = load_service_config(env_file)

        self.assertEqual(config.hid_profile, "boot_keyboard")
