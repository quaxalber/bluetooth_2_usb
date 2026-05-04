import tempfile
import unittest
from pathlib import Path

from bluetooth_2_usb.args import CustomArgumentParser
from bluetooth_2_usb.service_settings import (
    ServiceSettings,
    ServiceSettingsError,
    build_runtime_argv,
    build_runtime_shell_command,
    canonicalize_service_settings_bools,
    load_service_settings,
)


class ServiceSettingsTest(unittest.TestCase):
    def test_loads_structured_runtime_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    [
                        "B2U_AUTO_DISCOVER=0",
                        "B2U_GRAB_DEVICES=1",
                        "B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12",
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

            settings = load_service_settings(env_file)

        self.assertFalse(settings.auto_discover)
        self.assertTrue(settings.grab_devices)
        self.assertTrue(settings.log_to_file)
        self.assertEqual(settings.log_path, "/tmp/custom log.txt")
        self.assertTrue(settings.debug)
        self.assertEqual(settings.device_ids, ["mouse", "keyboard"])
        self.assertEqual(settings.udc_path, "/tmp/udc")

    def test_loads_multiple_boolean_spellings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    [
                        "B2U_AUTO_DISCOVER=false",
                        "B2U_GRAB_DEVICES=yes",
                        "B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12",
                        "B2U_LOG_TO_FILE=on",
                        "B2U_LOG_PATH=/tmp/debug.log",
                        "B2U_DEBUG=no",
                        "B2U_DEVICE_IDS=",
                        "B2U_UDC_PATH=",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            settings = load_service_settings(env_file)

        self.assertFalse(settings.auto_discover)
        self.assertTrue(settings.grab_devices)
        self.assertTrue(settings.log_to_file)
        self.assertFalse(settings.debug)

    def test_unknown_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("NOPE=1\n", encoding="utf-8")

            with self.assertRaises(ServiceSettingsError):
                load_service_settings(env_file)

    def test_builds_runtime_argv_and_shell_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    [
                        "B2U_AUTO_DISCOVER=1",
                        "B2U_GRAB_DEVICES=1",
                        "B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12",
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

            settings = load_service_settings(env_file)
            argv = build_runtime_argv(settings, append_debug=True)
            command = build_runtime_shell_command("python -m bluetooth_2_usb", settings=settings, append_debug=True)

        self.assertIn("--auto_discover", argv)
        self.assertIn("--grab_devices", argv)
        self.assertIn("--debug", argv)
        self.assertIn("/tmp/debug log.txt", argv)
        self.assertIn("'MX Keys'", command)

    def test_unknown_runtime_setting_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("B2U_UNKNOWN_SETTING=1\n", encoding="utf-8")

            with self.assertRaises(ServiceSettingsError):
                load_service_settings(env_file)

    def test_default_runtime_argv_matches_default_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "missing"

            settings = load_service_settings(env_file)
            argv = build_runtime_argv(settings)

        self.assertEqual(
            argv,
            [
                "--auto_discover",
                "--grab_devices",
                "--interrupt_shortcut",
                "CTRL+SHIFT+F12",
                "--log_path",
                "/var/log/bluetooth_2_usb/bluetooth_2_usb.log",
            ],
        )

    def test_builds_runtime_argv_does_not_emit_internal_udc_path(self) -> None:
        argv = build_runtime_argv(ServiceSettings(udc_path="/tmp/udc-state"))

        self.assertNotIn("--udc_path", argv)
        self.assertNotIn("/tmp/udc-state", argv)

    def test_shell_command_emits_internal_udc_path_as_environment_assignment(self) -> None:
        command = build_runtime_shell_command("bluetooth_2_usb", settings=ServiceSettings(udc_path="/tmp/udc-state"))

        self.assertTrue(command.startswith("BLUETOOTH_2_USB_UDC_PATH=/tmp/udc-state "))
        self.assertNotIn("--udc_path", command)

    def test_generated_runtime_argv_is_accepted_by_runtime_parser(self) -> None:
        settings = ServiceSettings(
            auto_discover=True,
            device_ids=["MX Keys", "/dev/input/event3"],
            grab_devices=True,
            interrupt_shortcut="CTRL+SHIFT+F12",
            log_to_file=True,
            log_path="/tmp/bluetooth 2 usb.log",
            debug=True,
            udc_path="/tmp/internal-udc-state",
        )
        argv = build_runtime_argv(settings)

        parsed = CustomArgumentParser().parse_args(argv)

        self.assertTrue(parsed.auto_discover)
        self.assertEqual(parsed.device_ids, ["MX Keys", "/dev/input/event3"])

    def test_canonicalize_service_settings_quotes_interrupt_shortcut_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("\n".join(["B2U_INTERRUPT_SHORTCUT='CTRL + SHIFT + F12'"]) + "\n", encoding="utf-8")

            changed = canonicalize_service_settings_bools(env_file)

            self.assertTrue(changed)
            self.assertIn("B2U_INTERRUPT_SHORTCUT='CTRL + SHIFT + F12'", env_file.read_text(encoding="utf-8"))

    def test_canonicalize_service_settings_bools_rewrites_bool_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    [
                        "# Managed runtime settings",
                        "B2U_AUTO_DISCOVER=1",
                        "",
                        "B2U_GRAB_DEVICES=yes",
                        "B2U_LOG_TO_FILE=off",
                        "B2U_DEBUG=0",
                        "B2U_DEVICE_IDS='MX Keys'",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            changed = canonicalize_service_settings_bools(env_file)

            self.assertTrue(changed)
            self.assertEqual(
                env_file.read_text(encoding="utf-8"),
                "\n".join(
                    [
                        "# Managed runtime settings",
                        "B2U_AUTO_DISCOVER=true",
                        "B2U_DEVICE_IDS='MX Keys'",
                        "B2U_GRAB_DEVICES=true",
                        "B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12",
                        "B2U_LOG_TO_FILE=false",
                        "B2U_LOG_PATH=/var/log/bluetooth_2_usb/bluetooth_2_usb.log",
                        "B2U_DEBUG=false",
                        "B2U_UDC_PATH=",
                    ]
                )
                + "\n",
            )

    def test_canonicalize_service_settings_bools_preserves_canonical_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    [
                        "B2U_AUTO_DISCOVER=true",
                        "B2U_DEVICE_IDS=",
                        "B2U_GRAB_DEVICES=true",
                        "B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12",
                        "B2U_LOG_TO_FILE=false",
                        "B2U_LOG_PATH=/var/log/bluetooth_2_usb/bluetooth_2_usb.log",
                        "B2U_DEBUG=false",
                        "B2U_UDC_PATH=",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            changed = canonicalize_service_settings_bools(env_file)

        self.assertFalse(changed)
