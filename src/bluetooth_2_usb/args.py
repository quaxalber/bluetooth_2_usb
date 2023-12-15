import argparse
import atexit
import sys
from typing import Optional

from usb_hid import disable


class CustomArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(
            *args,
            add_help=False,
            description="Bluetooth to USB HID relay. Handles Bluetooth keyboard and mouse events from multiple input devices and translates them to USB using Linux's gadget mode.",
            formatter_class=argparse.RawTextHelpFormatter,
            **kwargs,
        )
        self.register("action", "help", _HelpAction)
        self._add_arguments()

    def _add_arguments(self) -> None:
        self.add_argument(
            "--device_ids",
            "-i",
            type=lambda input: [item.strip() for item in input.split(",")],
            default=None,
            help="Comma-separated list of identifiers for input devices to be relayed.\nAn identifier is either the input device path, the MAC address or any case-insensitive substring of the device name.\nExample: --device_ids '/dev/input/event2,a1:b2:c3:d4:e5:f6,0A-1B-2C-3D-4E-5F,logi'\nDefault: None",
        )
        self.add_argument(
            "--auto_discover",
            "-a",
            action="store_true",
            default=False,
            help="Enable auto-discovery mode. All readable input devices will be relayed automatically.\nDefault: disabled",
        )
        self.add_argument(
            "--grab_devices",
            "-g",
            action="store_true",
            default=False,
            help="Grab the input devices, i.e., suppress any events on your relay device.\nDevices are not grabbed by default.",
        )
        self.add_argument(
            "--list_devices",
            "-l",
            action="store_true",
            default=False,
            help="List all available input devices and exit.",
        )
        self.add_argument(
            "--log_to_file",
            "-f",
            action="store_true",
            default=False,
            help="Add a handler that logs to file, additionally to stdout.",
        )
        self.add_argument(
            "--log_path",
            "-p",
            type=str,
            default="/var/log/bluetooth_2_usb/bluetooth_2_usb.log",
            help="The path of the log file\nDefault: /var/log/bluetooth_2_usb/bluetooth_2_usb.log",
        )
        self.add_argument(
            "--debug",
            "-d",
            action="store_true",
            default=False,
            help="Enable debug mode (Increases log verbosity)\nDefault: disabled",
        )
        self.add_argument(
            "--version",
            "-v",
            action="store_true",
            default=False,
            help="Display the version number of this software and exit.",
        )
        self.add_argument(
            "--help",
            "-h",
            action="help",
            default=argparse.SUPPRESS,
            help="Show this help message and exit.",
        )

    def print_help(self) -> None:
        """
        When the script is run with help or version flag, we need to unregister usb_hid.disable() from atexit
        because else an exception occurs if the script is already running, e.g. as service.
        """
        atexit.unregister(disable)
        super().print_help()


class _HelpAction(argparse._HelpAction):
    def __call__(self, parser, namespace, values, option_string=None) -> None:
        parser.print_help()
        parser.exit()


class Arguments:
    __slots__ = [
        "_device_ids",
        "_auto_discover",
        "_grab_devices",
        "_list_devices",
        "_log_to_file",
        "_log_path",
        "_debug",
        "_version",
    ]

    def __init__(
        self,
        device_ids: Optional[list[str]],
        auto_discover: bool,
        grab_devices: bool,
        list_devices: bool,
        log_to_file: bool,
        log_path: str,
        debug: bool,
        version: bool,
    ) -> None:
        self._device_ids = device_ids
        self._auto_discover = auto_discover
        self._grab_devices = grab_devices
        self._list_devices = list_devices
        self._log_to_file = log_to_file
        self._log_path = log_path
        self._debug = debug
        self._version = version

    @property
    def device_ids(self) -> Optional[list[str]]:
        return self._device_ids

    @property
    def auto_discover(self) -> bool:
        return self._auto_discover

    @property
    def grab_devices(self) -> bool:
        return self._grab_devices

    @property
    def list_devices(self) -> bool:
        return self._list_devices

    @property
    def log_to_file(self) -> bool:
        return self._log_to_file

    @property
    def log_path(self) -> str:
        return self._log_path

    @property
    def debug(self) -> bool:
        return self._debug

    @property
    def version(self) -> bool:
        return self._version

    def __str__(self) -> str:
        return (
            f"Arguments(device_ids={self.device_ids}, "
            f"auto_discover={self.auto_discover}, "
            f"grab_devices={self.grab_devices}, "
            f"list_devices={self.list_devices}, "
            f"log_to_file={self.log_to_file}, "
            f"log_path={self.log_path}, "
            f"debug={self.debug}, "
            f"version={self.version})"
        )


def parse_args() -> Arguments:
    parser = CustomArgumentParser()

    args = parser.parse_args()

    # Check if no arguments were provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    return Arguments(
        device_ids=args.device_ids,
        auto_discover=args.auto_discover,
        grab_devices=args.grab_devices,
        list_devices=args.list_devices,
        log_to_file=args.log_to_file,
        log_path=args.log_path,
        debug=args.debug,
        version=args.version,
    )
