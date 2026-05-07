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
    normalize_service_settings_file,
)


class ServiceSettingsTest(unittest.TestCase):
    def test_loads_structured_runtime_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    [
                        "B2U_AUTO=0",
                        "B2U_GRAB=1",
                        "B2U_SHORTCUT=CTRL+SHIFT+F12",
                        "B2U_DEBUG=1",
                        "B2U_DEVICES='mouse, keyboard'",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            settings = load_service_settings(env_file)

        self.assertFalse(settings.auto)
        self.assertTrue(settings.grab)
        self.assertTrue(settings.debug)
        self.assertEqual(settings.devices, ["mouse", "keyboard"])

    def test_loads_multiple_boolean_spellings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    ["B2U_AUTO=false", "B2U_GRAB=yes", "B2U_SHORTCUT=CTRL+SHIFT+F12", "B2U_DEBUG=no", "B2U_DEVICES="]
                )
                + "\n",
                encoding="utf-8",
            )

            settings = load_service_settings(env_file)

        self.assertFalse(settings.auto)
        self.assertTrue(settings.grab)
        self.assertFalse(settings.debug)

    def test_unknown_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("NOPE=1\n", encoding="utf-8")

            with self.assertRaises(ServiceSettingsError):
                load_service_settings(env_file)

    def test_malformed_devices_value_is_rejected_as_service_settings_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("B2U_DEVICES=', ,'\n", encoding="utf-8")

            with self.assertRaisesRegex(ServiceSettingsError, "Invalid device filter list"):
                load_service_settings(env_file)

    def test_normalize_service_settings_renames_legacy_device_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("# Settings\nB2U_DEVICE_IDS='keyboard, mouse'\n", encoding="utf-8")

            changed = normalize_service_settings_file(env_file)
            settings = load_service_settings(env_file)
            migrated_text = env_file.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertEqual(settings.devices, ["keyboard", "mouse"])
        self.assertEqual(migrated_text, "# Settings\nB2U_DEVICES='keyboard, mouse'\n")

    def test_normalize_service_settings_drops_legacy_device_ids_when_devices_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("B2U_DEVICE_IDS=keyboard\nB2U_DEVICES=mouse\n", encoding="utf-8")

            changed = normalize_service_settings_file(env_file)
            settings = load_service_settings(env_file)
            migrated_text = env_file.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertEqual(settings.devices, ["mouse"])
        self.assertEqual(migrated_text, "B2U_DEVICES=mouse\n")

    def test_normalize_service_settings_renames_legacy_device_ids_when_devices_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("B2U_DEVICES=\nB2U_DEVICE_IDS='keyboard, mouse'\n", encoding="utf-8")

            changed = normalize_service_settings_file(env_file)
            settings = load_service_settings(env_file)
            migrated_text = env_file.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertEqual(settings.devices, ["keyboard", "mouse"])
        self.assertEqual(migrated_text, "B2U_DEVICES='keyboard, mouse'\n")

    def test_normalize_service_settings_renames_old_auto_and_shortcut_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "B2U_AUTO_DISCOVER=true\nB2U_INTERRUPT_SHORTCUT='CTRL + SHIFT + F12'\n", encoding="utf-8"
            )

            changed = normalize_service_settings_file(env_file)
            settings = load_service_settings(env_file)
            migrated_text = env_file.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertTrue(settings.auto)
        self.assertEqual(settings.shortcut, "CTRL + SHIFT + F12")
        self.assertEqual(migrated_text, "B2U_AUTO=true\nB2U_SHORTCUT='CTRL + SHIFT + F12'\n")

    def test_normalize_service_settings_renames_legacy_grab_devices(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("B2U_GRAB_DEVICES=false\n", encoding="utf-8")

            changed = normalize_service_settings_file(env_file)
            settings = load_service_settings(env_file)
            migrated_text = env_file.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertFalse(settings.grab)
        self.assertEqual(migrated_text, "B2U_GRAB=false\n")

    def test_normalize_service_settings_removes_removed_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "B2U_USB_SERIAL=b2u-test\nB2U_USB_PRODUCT_SUFFIX=pi0w\nB2U_UDC_PATH=/tmp/udc\nB2U_AUTO=true\n",
                encoding="utf-8",
            )

            changed = normalize_service_settings_file(env_file)
            settings = load_service_settings(env_file)
            migrated_text = env_file.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertTrue(settings.auto)
        self.assertEqual(migrated_text, "B2U_AUTO=true\n")

    def test_builds_runtime_argv_and_shell_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    ["B2U_AUTO=1", "B2U_GRAB=1", "B2U_SHORTCUT=CTRL+SHIFT+F12", "B2U_DEBUG=0", "B2U_DEVICES='MX Keys'"]
                )
                + "\n",
                encoding="utf-8",
            )

            settings = load_service_settings(env_file)
            argv = build_runtime_argv(settings, append_debug=True)
            command = build_runtime_shell_command("python -m bluetooth_2_usb", settings=settings, append_debug=True)

        self.assertIn("--auto", argv)
        self.assertIn("--grab", argv)
        self.assertIn("--debug", argv)
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

        self.assertEqual(argv, ["--auto", "--grab", "--shortcut", "CTRL+SHIFT+F12"])

    def test_generated_runtime_argv_is_accepted_by_runtime_parser(self) -> None:
        settings = ServiceSettings(
            auto=True, devices=["MX Keys", "/dev/input/event3"], grab=True, shortcut="CTRL+SHIFT+F12", debug=True
        )
        argv = build_runtime_argv(settings)

        parsed = CustomArgumentParser().parse_args(argv)

        self.assertTrue(parsed.auto)
        self.assertEqual(parsed.devices, ["MX Keys", "/dev/input/event3"])

    def test_canonicalize_service_settings_quotes_shortcut_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text("\n".join(["B2U_SHORTCUT='CTRL + SHIFT + F12'"]) + "\n", encoding="utf-8")

            changed = canonicalize_service_settings_bools(env_file)

            self.assertTrue(changed)
            self.assertIn("B2U_SHORTCUT='CTRL + SHIFT + F12'", env_file.read_text(encoding="utf-8"))

    def test_canonicalize_service_settings_bools_rewrites_bool_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    [
                        "# Managed runtime settings",
                        "B2U_AUTO=1",
                        "",
                        "B2U_GRAB=yes",
                        "B2U_DEBUG=0",
                        "B2U_DEVICES='MX Keys'",
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
                        "B2U_AUTO=true",
                        "B2U_DEVICES='MX Keys'",
                        "B2U_GRAB=true",
                        "B2U_SHORTCUT=CTRL+SHIFT+F12",
                        "B2U_DEBUG=false",
                    ]
                )
                + "\n",
            )

    def test_canonicalize_service_settings_bools_preserves_canonical_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "bluetooth_2_usb"
            env_file.write_text(
                "\n".join(
                    ["B2U_AUTO=true", "B2U_DEVICES=", "B2U_GRAB=true", "B2U_SHORTCUT=CTRL+SHIFT+F12", "B2U_DEBUG=false"]
                )
                + "\n",
                encoding="utf-8",
            )

            changed = canonicalize_service_settings_bools(env_file)

        self.assertFalse(changed)
