import unittest

from bluetooth_2_usb.args import parse_args


class ParseArgsTest(unittest.TestCase):
    def test_empty_args_exit_with_usage_code(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            parse_args([])

        self.assertEqual(ctx.exception.code, 2)

    def test_invalid_shortcut_key_is_rejected(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            parse_args(["--interrupt_shortcut", "CTRL+SHIFT+NOPE"])

        self.assertEqual(ctx.exception.code, 2)

    def test_shortcut_aliases_are_normalized(self) -> None:
        args = parse_args(["--interrupt_shortcut", "CTRL+SHIFT+F12"])
        self.assertEqual(
            args.interrupt_shortcut,
            ["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_F12"],
        )

    def test_boot_keyboard_profile_is_default(self) -> None:
        args = parse_args(["--version"])

        self.assertEqual(args.hid_profile, "boot_keyboard")

    def test_boot_mouse_profile_is_accepted(self) -> None:
        args = parse_args(["--hid-profile", "boot_mouse"])

        self.assertEqual(args.hid_profile, "boot_mouse")

    def test_nonboot_profile_is_accepted(self) -> None:
        args = parse_args(["--hid-profile", "nonboot"])

        self.assertEqual(args.hid_profile, "nonboot")

    def test_cherry_combo_profile_is_accepted(self) -> None:
        args = parse_args(["--hid-profile", "cherry_combo"])

        self.assertEqual(args.hid_profile, "cherry_combo")
