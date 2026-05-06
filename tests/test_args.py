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
