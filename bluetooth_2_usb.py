import asyncio
import atexit
from logging import DEBUG
import signal
import sys
from typing import NoReturn

from usb_hid import disable

from src.bluetooth_2_usb.args import parse_args
from src.bluetooth_2_usb.logging import add_file_handler, get_logger
from src.bluetooth_2_usb.relay import RelayController, list_input_devices


_logger = get_logger()
_VERSION = "0.7.0"
_VERSIONED_NAME = f"Bluetooth 2 USB v{_VERSION}"


def _signal_handler(sig, frame) -> NoReturn:
    _logger.info(f"Exiting gracefully. Received signal: {sig}, frame: {frame}")
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


async def _main() -> NoReturn:
    """
    Parses command-line arguments, sets up logging and starts the event loop which
    reads events from the input devices and forwards them to the corresponding USB
    gadget device.
    """
    args = parse_args()
    if args.debug:
        _logger.setLevel(DEBUG)
    if args.version:
        _print_version()
    if args.list_devices:
        _list_devices()

    log_handlers_message = "Logging to stdout"
    if args.log_to_file:
        add_file_handler(args.log_path)
        log_handlers_message += f" and to {args.log_path}"
    _logger.debug(f"CLI args: {args}")
    _logger.debug(log_handlers_message)
    _logger.info(f"Launching {_VERSIONED_NAME}")

    controller = RelayController(args.device_ids, args.auto_discover, args.grab_devices)
    await controller.async_relay_devices()


def _list_devices():
    for dev in list_input_devices():
        print(f"{dev.name}\t{dev.uniq if dev.uniq else dev.phys}\t{dev.path}")
    _exit_safely()


def _print_version():
    print(_VERSIONED_NAME)
    _exit_safely()


def _exit_safely():
    """
    When the script is run with help or version flag, we need to unregister usb_hid.disable() from atexit
    because else an exception occurs if the script is already running, e.g. as service.
    """
    atexit.unregister(disable)
    sys.exit(0)


if __name__ == "__main__":
    """
    Entry point for the script.
    """
    try:
        asyncio.run(_main())
    except Exception:
        _logger.exception("Houston, we have an unhandled problem. Abort mission.")
