from argparse import Namespace
import argparse
import atexit
import sys

from usb_hid import disable


class CustomArgumentParser(argparse.ArgumentParser):
    def print_help(self) -> None:
        """
        When the script is run with help or version flag, we need to unregister usb_hid.disable() from atexit
        because else an exception occurs if the script is already running, e.g. as service.
        """
        atexit.unregister(disable)
        super().print_help()


def parse_args() -> Namespace:
    parser = CustomArgumentParser(
        description="Bluetooth to USB HID relay. Handles Bluetooth keyboard and mouse events from multiple input devices and translates them to USB using Linux's gadget mode.",
    )

    parser.add_argument(
        "--device_ids",
        "-i",
        type=lambda input: [item.strip() for item in input.split(",")],
        default=None,
        help="Comma-separated list of identifiers for input devices to be relayed.\n\n \
          An identifier is either the input device path, the MAC address or any case-insensitive substring of the device name.\n\n \
          Default is None.\n\n \
          Example: --device_ids '/dev/input/event2,a1:b2:c3:d4:e5:f6,0A-1B-2C-3D-4E-5F,logi'",
    )
    parser.add_argument(
        "--auto_discover",
        "-a",
        action="store_true",
        default=False,
        help="Enable auto-discovery mode. All readable input devices will be relayed automatically.",
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        default=False,
        help="Enable debug mode. Increases log verbosity",
    )
    parser.add_argument(
        "--log_to_file",
        "-f",
        action="store_true",
        default=False,
        help="Add a handler that logs to file additionally to stdout. ",
    )
    parser.add_argument(
        "--log_path",
        "-p",
        type=str,
        default="/var/log/bluetooth_2_usb/bluetooth_2_usb.log",
        help="The path of the log file. Default is /var/log/bluetooth_2_usb/bluetooth_2_usb.log.",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="store_true",
        default=False,
        help="Display the version number of this software and exit.",
    )
    parser.add_argument(
        "--list_devices",
        "-l",
        action="store_true",
        default=False,
        help="List all available input devices and exit.",
    )

    args = parser.parse_args()

    # Check if no arguments were provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    return args
