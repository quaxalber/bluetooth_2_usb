import asyncio
import atexit
from logging import DEBUG
import signal
import sys
from typing import NoReturn

import usb_hid

from src.bluetooth_2_usb.args import parse_args
from src.bluetooth_2_usb.logging import add_file_handler, get_logger
from src.bluetooth_2_usb.relay import RelayController, async_list_input_devices


logger = get_logger()
VERSION = "0.8.0"
VERSIONED_NAME = f"Bluetooth 2 USB v{VERSION}"


def signal_handler(sig, frame) -> None:
    sig_name = signal.Signals(sig).name
    logger.info(f"Received signal: {sig_name}, frame: {frame}")
    sys.exit(0)


for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
    signal.signal(sig, signal_handler)


async def main() -> NoReturn:
    """
    Parses command-line arguments, sets up logging and starts the event loop which
    reads events from the input devices and forwards them to the corresponding USB
    gadget device.
    """
    args = parse_args()
    if args.debug:
        logger.setLevel(DEBUG)
    if args.version:
        print_version()
    if args.list_devices:
        await async_list_devices()

    log_handlers_message = "Logging to stdout"
    if args.log_to_file:
        add_file_handler(args.log_path)
        log_handlers_message += f" and to {args.log_path}"
    logger.debug(f"CLI args: {args}")
    logger.debug(log_handlers_message)
    logger.info(f"Launching {VERSIONED_NAME}")

    controller = RelayController(args.device_ids, args.auto_discover, args.grab_devices)
    await controller.async_relay_devices()


async def async_list_devices():
    for dev in await async_list_input_devices():
        print(f"{dev.name}\t{dev.uniq if dev.uniq else dev.phys}\t{dev.path}")
    exit_safely()


def print_version():
    print(VERSIONED_NAME)
    exit_safely()


def exit_safely():
    """
    When the script is run with help or version flag, we need to unregister usb_hid.disable() from atexit
    because else an exception occurs if the script is already running, e.g. as service.
    """
    atexit.unregister(usb_hid.disable)
    sys.exit(0)


if __name__ == "__main__":
    """
    Entry point for the script.
    """
    try:
        asyncio.run(main())
    except Exception:
        logger.exception("Houston, we have an unhandled problem. Abort mission.")
