import unittest
from unittest.mock import patch

from bluetooth_2_usb import version


class VersionTest(unittest.TestCase):
    def test_prefers_installed_package_metadata(self) -> None:
        with patch("bluetooth_2_usb.version.package_version", return_value="1.2.3"):
            with patch("bluetooth_2_usb.version.SCM_VERSION", "9.9.9"):
                self.assertEqual(version.get_version(), "1.2.3")

    def test_falls_back_to_scm_version(self) -> None:
        with patch(
            "bluetooth_2_usb.version.package_version",
            side_effect=version.PackageNotFoundError,
        ):
            with patch("bluetooth_2_usb.version.SCM_VERSION", "2.0.0.dev1"):
                self.assertEqual(version.get_version(), "2.0.0.dev1")
