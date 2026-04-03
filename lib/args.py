from argparse import Namespace
import argparse

from usb_hid import unregister_disable


class CustomArgumentParser(argparse.ArgumentParser):
    def print_help(self) -> None:
        unregister_disable()
        super().print_help()


def parse_args() -> Namespace:
    parser = CustomArgumentParser(
        description="Bluetooth to USB HID proxy. Reads incoming mouse and keyboard events \
        (e.g., Bluetooth) and forwards them to USB using Linux's gadget mode.",
    )

    parser.add_argument(
        "--keyboards",
        "-k",
        type=lambda input: [item.strip() for item in input.split(",")],
        default=None,
        help="Comma-separated list of input device paths for keyboards to be registered and connected.\n \
          Default is None.\n \
          Example: --keyboards /dev/input/event2,/dev/input/event4",
    )
    parser.add_argument(
        "--mice",
        "-m",
        type=lambda input: [item.strip() for item in input.split(",")],
        default=None,
        help="Comma-separated list of input device paths for mice to be registered and connected.\n \
          Default is None.\n \
          Example: --mice /dev/input/event3,/dev/input/event5",
    )
    parser.add_argument(
        "--sandbox",
        "-s",
        action="store_true",
        default=False,
        help="Only read input events but do not forward them to the output devices.",
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
        help="Display the version number of this software.",
    )

    args = parser.parse_args()
    return args
