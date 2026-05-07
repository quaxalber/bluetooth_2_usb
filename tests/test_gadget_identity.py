import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from bluetooth_2_usb.gadgets.identity import (
    USB_GADGET_PID_COMBO,
    USB_GADGET_VID_LINUX,
    USB_MANUFACTURER,
    USB_PRODUCT_NAME,
    USB_SERIAL_NUMBER,
    load_or_create_usb_identity,
    product_name_with_suffix,
    usb_configfs_hex_u16,
    usb_udev_hex_u16,
    validate_usb_product_suffix,
    validate_usb_serial,
)
from bluetooth_2_usb.ops.hid_udev_rule import install_hid_udev_rule


class GadgetIdentityTest(unittest.TestCase):
    def test_usb_identity_formatters_match_configfs_and_udev_shapes(self) -> None:
        self.assertEqual(usb_configfs_hex_u16(USB_GADGET_VID_LINUX), "0x1d6b")
        self.assertEqual(usb_configfs_hex_u16(USB_GADGET_PID_COMBO), "0x0104")
        self.assertEqual(usb_udev_hex_u16(USB_GADGET_VID_LINUX), "1d6b")
        self.assertEqual(usb_udev_hex_u16(USB_GADGET_PID_COMBO), "0104")

    def test_usb_identity_strings_are_stable_host_visible_values(self) -> None:
        self.assertEqual(USB_MANUFACTURER, "quaxalber")
        self.assertEqual(USB_PRODUCT_NAME, "USB Combo Device")
        self.assertEqual(USB_SERIAL_NUMBER, "213374badcafe")

    def test_load_or_create_usb_identity_persists_generated_serial(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "usb_identity.json"

            first = load_or_create_usb_identity(product_suffix="pi0w", state_path=state_path)
            second = load_or_create_usb_identity(product_suffix="pi0w", state_path=state_path)

        self.assertEqual(first.product_name, "USB Combo Device pi0w")
        self.assertEqual(first.serial_number, second.serial_number)
        self.assertRegex(first.serial_number, r"^b2u[0-9a-f]{16}$")

    def test_load_or_create_usb_identity_prefers_explicit_serial(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "usb_identity.json"

            identity = load_or_create_usb_identity(
                serial_override="b2upi4b", product_suffix="pi4b", state_path=state_path
            )

        self.assertEqual(identity.product_name, "USB Combo Device pi4b")
        self.assertEqual(identity.serial_number, "b2upi4b")
        self.assertFalse(state_path.exists())

    def test_usb_identity_validation_rejects_unsafe_values(self) -> None:
        with self.assertRaises(ValueError):
            validate_usb_serial("not ok")
        with self.assertRaises(ValueError):
            validate_usb_product_suffix("pi4b\nbad")

    def test_product_name_with_suffix_keeps_default_when_suffix_is_empty(self) -> None:
        self.assertEqual(product_name_with_suffix(""), USB_PRODUCT_NAME)
        self.assertEqual(product_name_with_suffix("pi4b"), "USB Combo Device pi4b")

    def test_static_udev_rule_uses_canonical_usb_identity(self) -> None:
        rule_text = (Path(__file__).parents[1] / "udev/70-bluetooth_2_usb_hidapi.rules").read_text(encoding="utf-8")

        self.assertIn(f'ATTRS{{idVendor}}=="{usb_udev_hex_u16(USB_GADGET_VID_LINUX)}"', rule_text)
        self.assertIn(f'ATTRS{{idProduct}}=="{usb_udev_hex_u16(USB_GADGET_PID_COMBO)}"', rule_text)

    def test_udev_install_triggers_canonical_usb_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            (repo_root / "udev").mkdir(parents=True)
            (repo_root / "udev/70-bluetooth_2_usb_hidapi.rules").write_text("rule\n", encoding="utf-8")
            rule_dst = Path(tmpdir) / "rules.d/70-bluetooth_2_usb_hidapi.rules"

            with (
                patch("bluetooth_2_usb.ops.hid_udev_rule.PATHS", SimpleNamespace(install_dir=repo_root)),
                patch("bluetooth_2_usb.ops.hid_udev_rule.RULE_DST", rule_dst),
                patch("bluetooth_2_usb.ops.hid_udev_rule.run", return_value=SimpleNamespace(returncode=0)) as run,
            ):
                install_hid_udev_rule()

        self.assertIn(
            call(
                [
                    "udevadm",
                    "trigger",
                    "--subsystem-match=usb",
                    f"--attr-match=idVendor={usb_udev_hex_u16(USB_GADGET_VID_LINUX)}",
                    f"--attr-match=idProduct={usb_udev_hex_u16(USB_GADGET_PID_COMBO)}",
                ]
            ),
            run.mock_calls,
        )
