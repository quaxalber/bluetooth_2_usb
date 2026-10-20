import unittest

from bluetooth_2_usb.args import parse_args


class ParseArgsTest(unittest.TestCase):
    def test_empty_args_exit_with_usage_code(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            parse_args([])

        self.assertEqual(ctx.exception.code, 2)

    def test_invalid_shortcut_key_is_rejected(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            parse_args(["--shortcut", "CTRL+SHIFT+NOPE"])

        self.assertEqual(ctx.exception.code, 2)

    def test_shortcut_aliases_are_normalized(self) -> None:
        args = parse_args(["--shortcut", "CTRL+SHIFT+F12"])
        self.assertEqual(args.shortcut, ["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_F12"])

    def test_version_flag_parses(self) -> None:
        args = parse_args(["--version"])

        self.assertTrue(args.version)

    def test_jiggler_led_defaults_to_scroll_lock(self) -> None:
        args = parse_args(["--version"])

        self.assertEqual(args.jiggler_led, "scroll_lock")

    def test_jiggler_led_accepts_known_choice_case_insensitively(self) -> None:
        args = parse_args(["--jiggler-led", "CAPS_LOCK", "--version"])

        self.assertEqual(args.jiggler_led, "caps_lock")

    def test_invalid_jiggler_led_is_rejected(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            parse_args(["--jiggler-led", "nope"])

        self.assertEqual(ctx.exception.code, 2)
