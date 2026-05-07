import unittest
from unittest.mock import patch

from bluetooth_2_usb import service_entrypoint
from bluetooth_2_usb.service_settings import ServiceSettings


class ServiceEntrypointTest(unittest.TestCase):
    def test_main_normalizes_and_runs_settings(self) -> None:
        with patch("bluetooth_2_usb.service_entrypoint.normalize_service_settings_file") as normalize:
            with patch("bluetooth_2_usb.service_entrypoint.load_service_settings", return_value=ServiceSettings()):
                with patch("bluetooth_2_usb.service_entrypoint.run", return_value=0):
                    self.assertEqual(service_entrypoint.main(), 0)

        normalize.assert_called_once_with()
