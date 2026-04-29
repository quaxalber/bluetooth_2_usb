import importlib
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bluetooth_2_usb.logging as bt_logging


class LoggingConfigurationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.package_logger = logging.getLogger(bt_logging.PACKAGE_LOGGER_NAME)
        self.original_handlers = list(self.package_logger.handlers)
        self.original_level = self.package_logger.level
        self.original_propagate = self.package_logger.propagate
        for handler in list(self.package_logger.handlers):
            self.package_logger.removeHandler(handler)

    def tearDown(self) -> None:
        for handler in list(self.package_logger.handlers):
            self.package_logger.removeHandler(handler)
            if handler not in self.original_handlers:
                handler.close()
        for handler in self.original_handlers:
            self.package_logger.addHandler(handler)
        self.package_logger.setLevel(self.original_level)
        self.package_logger.propagate = self.original_propagate

    def test_get_logger_uses_named_children_with_handlers_only_on_package_root(
        self,
    ) -> None:
        child = bt_logging.get_logger("bluetooth_2_usb.input_relay")

        self.assertEqual(child.name, "bluetooth_2_usb.input_relay")
        self.assertEqual(child.handlers, [])
        self.assertTrue(child.propagate)
        self.assertGreater(len(self.package_logger.handlers), 0)
        self.assertFalse(self.package_logger.propagate)

    def test_add_file_handler_attaches_to_package_root_once(self) -> None:
        bt_logging.get_logger("bluetooth_2_usb.input_relay")

        with tempfile.TemporaryDirectory() as tmp:
            log_path = str(Path(tmp) / "relay.log")
            bt_logging.add_file_handler(log_path)
            bt_logging.add_file_handler(log_path)

            file_handlers = [
                handler
                for handler in self.package_logger.handlers
                if isinstance(handler, logging.FileHandler)
            ]

            self.assertEqual(len(file_handlers), 1)
            for handler in file_handlers:
                self.package_logger.removeHandler(handler)
                handler.close()

    def test_add_file_handler_expands_user_path_before_opening(self) -> None:
        bt_logging.get_logger("bluetooth_2_usb.input_relay")

        with tempfile.TemporaryDirectory() as tmp:
            env = {"HOME": tmp}
            if os.name == "nt":
                drive, tail = os.path.splitdrive(tmp)
                env.update(
                    {
                        "USERPROFILE": tmp,
                        "HOMEDRIVE": drive,
                        "HOMEPATH": tail or "\\",
                    }
                )
            with patch.dict(os.environ, env, clear=False):
                bt_logging.add_file_handler("~/relay.log")

            file_handlers = [
                handler
                for handler in self.package_logger.handlers
                if isinstance(handler, logging.FileHandler)
            ]

            self.assertEqual(len(file_handlers), 1)
            self.assertEqual(
                Path(file_handlers[0].baseFilename),
                (Path(tmp) / "relay.log").resolve(),
            )
            for handler in file_handlers:
                self.package_logger.removeHandler(handler)
                handler.close()


class RelayModuleBoundaryTest(unittest.TestCase):
    def test_old_runtime_module_imports_are_not_preserved(self) -> None:
        for module_name in (
            "bluetooth_2_usb.device_relay",
            "bluetooth_2_usb.gadget_config",
            "bluetooth_2_usb.gadget_manager",
            "bluetooth_2_usb.hid_layout",
            "bluetooth_2_usb.relay",
            "bluetooth_2_usb.relay_controller",
            "bluetooth_2_usb.runtime_monitor",
        ):
            with self.subTest(module_name=module_name):
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(module_name)
