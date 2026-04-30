import builtins
import importlib
import unittest
from unittest.mock import patch

import bluetooth_2_usb
from bluetooth_2_usb import version


class VersionTest(unittest.TestCase):
    def test_package_import_does_not_eagerly_import_args(self) -> None:
        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "bluetooth_2_usb.args":
                raise AssertionError("bluetooth_2_usb.args should not be imported")
            return original_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=guarded_import):
            importlib.reload(bluetooth_2_usb)

    def test_prefers_installed_package_metadata(self) -> None:
        with patch("bluetooth_2_usb.version.package_version", return_value="1.2.3"):
            with patch("bluetooth_2_usb.version.SCM_VERSION", "9.9.9"):
                self.assertEqual(version.get_version(), "1.2.3")

    def test_falls_back_to_scm_version(self) -> None:
        with patch(
            "bluetooth_2_usb.version.package_version", side_effect=version.PackageNotFoundError
        ):
            with patch("bluetooth_2_usb.version.SCM_VERSION", "2.0.0.dev1"):
                self.assertEqual(version.get_version(), "2.0.0.dev1")
