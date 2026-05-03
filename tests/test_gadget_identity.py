import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from bluetooth_2_usb.gadgets.identity import (
    USB_GADGET_PID_COMBO,
    USB_GADGET_VID_LINUX,
    usb_configfs_hex_u16,
    usb_udev_hex_u16,
)
from bluetooth_2_usb.ops.hid_udev_rule import install_hid_udev_rule


class GadgetIdentityTest(unittest.TestCase):
    def test_usb_identity_formatters_match_configfs_and_udev_shapes(self) -> None:
        self.assertEqual(usb_configfs_hex_u16(USB_GADGET_VID_LINUX), "0x1d6b")
        self.assertEqual(usb_configfs_hex_u16(USB_GADGET_PID_COMBO), "0x0104")
        self.assertEqual(usb_udev_hex_u16(USB_GADGET_VID_LINUX), "1d6b")
        self.assertEqual(usb_udev_hex_u16(USB_GADGET_PID_COMBO), "0104")

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

            with patch("bluetooth_2_usb.ops.hid_udev_rule.RULE_DST", rule_dst):
                with patch("bluetooth_2_usb.ops.hid_udev_rule.run", return_value=SimpleNamespace(returncode=0)) as run:
                    install_hid_udev_rule(repo_root)

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
