import asyncio
import atexit
from logging import DEBUG
import signal
import sys

import usb_hid

from src.bluetooth_2_usb.args import parse_args
from src.bluetooth_2_usb.logging import add_file_handler, get_logger
from src.bluetooth_2_usb.relay import (
    RelayController,
    UdevEventMonitor,
    UsbHidManager,
    async_list_input_devices,
)

logger = get_logger()
VERSION = "0.8.3"
VERSIONED_NAME = f"Bluetooth 2 USB v{VERSION}"

shutdown_event = asyncio.Event()


def signal_handler(sig, frame):
    sig_name = signal.Signals(sig).name
    logger.debug(f"Received signal: {sig_name}. Requesting graceful shutdown.")
    shutdown_event.set()


for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
    signal.signal(sig, signal_handler)


async def main() -> None:
    """
    Parses command-line arguments, sets up logging, starts the event loop
    to forward input-device events to USB gadgets, and then waits for a shutdown signal.
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
        try:
            add_file_handler(args.log_path)
        except OSError as e:
            logger.error(f"Could not open log file '{args.log_path}' for writing: {e}")
            sys.exit(1)
        log_handlers_message += f" and to {args.log_path}"

    logger.debug(f"CLI args: {args}")
    logger.debug(log_handlers_message)
    logger.info(f"Launching {VERSIONED_NAME}")

    usb_manager = UsbHidManager()
    usb_manager.enable_devices()

    relay_controller = RelayController(
        usb_manager=usb_manager,
        device_identifiers=args.device_ids,
        auto_discover=args.auto_discover,
        grab_devices=args.grab_devices,
    )

    event_loop = asyncio.get_event_loop()

    with UdevEventMonitor(relay_controller, event_loop):
        relay_task = asyncio.create_task(relay_controller.async_relay_devices())

        await shutdown_event.wait()

        logger.debug("Shutdown event triggered. Cancelling relay task...")
        relay_task.cancel()

        await asyncio.gather(relay_task, return_exceptions=True)


async def async_list_devices():
    """
    Prints a list of available input devices. This is a helper function for
    the --list-devices CLI argument.
    """
    for dev in await async_list_input_devices():
        print(f"{dev.name}\t{dev.uniq if dev.uniq else dev.phys}\t{dev.path}")
    exit_safely()


def print_version():
    """
    Prints the version of Bluetooth 2 USB and exits.
    """
    print(VERSIONED_NAME)
    exit_safely()


def exit_safely():
    """
    When the script is run with help or version flag, we need to unregister usb_hid.disable()
    from atexit because else an exception occurs if the script is already running,
    e.g. as service.
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
        logger.exception("Unhandled exception encountered. Aborting mission.")
        sys.exit(1)
