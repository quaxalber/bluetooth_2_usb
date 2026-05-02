import os
import unittest
from unittest.mock import patch

from bluetooth_2_usb import service_entrypoint
from bluetooth_2_usb.service_settings import ServiceSettings


class ServiceEntrypointTest(unittest.TestCase):
    def test_main_clears_stale_udc_path_env_when_setting_is_empty(self) -> None:
        env = {"BLUETOOTH_2_USB_UDC_PATH": "/stale"}

        with patch.dict(os.environ, env, clear=True):
            with patch("bluetooth_2_usb.service_entrypoint.load_service_settings", return_value=ServiceSettings()):
                with patch("bluetooth_2_usb.service_entrypoint.run", return_value=0):
                    self.assertEqual(service_entrypoint.main(), 0)

            self.assertNotIn("BLUETOOTH_2_USB_UDC_PATH", os.environ)

    def test_main_sets_udc_path_env_from_settings(self) -> None:
        settings = ServiceSettings(udc_path="/tmp/udc-state")

        with patch.dict(os.environ, {}, clear=True):
            with patch("bluetooth_2_usb.service_entrypoint.load_service_settings", return_value=settings):
                with patch("bluetooth_2_usb.service_entrypoint.run", return_value=0):
                    self.assertEqual(service_entrypoint.main(), 0)

            self.assertEqual(os.environ["BLUETOOTH_2_USB_UDC_PATH"], "/tmp/udc-state")
