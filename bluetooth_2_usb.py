import asyncio
import atexit
from logging import DEBUG
from pathlib import Path
import signal
import sys

import usb_hid

from src.bluetooth_2_usb.args import parse_args
from src.bluetooth_2_usb.logging import add_file_handler, get_logger
from src.bluetooth_2_usb.relay import (
    GadgetManager,
    RelayController,
    ShortcutToggler,
    UdcStateMonitor,
    UdevEventMonitor,
    async_list_input_devices,
)

logger = get_logger()
VERSION = "0.9.0"
VERSIONED_NAME = f"Bluetooth 2 USB v{VERSION}"

shutdown_event = asyncio.Event()


def signal_handler(sig, frame):
    """
    Signal handler that sets the global shutdown_event.

    :param sig: Integer signal number
    :param frame: Unused stack frame object
    """
    sig_name = signal.Signals(sig).name
    logger.debug(f"Received signal: {sig_name}. Requesting graceful shutdown.")
    shutdown_event.set()


for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
    signal.signal(sig, signal_handler)


async def main() -> None:
    """
    Main entry point for Bluetooth 2 USB.

    1. Parses command-line arguments.
    2. Sets up logging according to the supplied flags.
    3. Optionally lists devices or prints version before exiting.
    4. Creates and enables the USB HID gadget.
    5. Creates a RelayController to forward input events to the gadget.
    6. Monitors for UDC state changes and new/removed /dev/input devices.
    7. Waits for a shutdown signal to cancel tasks.
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

    relaying_active = asyncio.Event()
    relaying_active.clear()

    gadget_manager = GadgetManager()
    gadget_manager.enable_gadgets()

    shortcut_toggler = None
    if args.interrupt_shortcut:
        shortcut_keys = validate_shortcut(args.interrupt_shortcut)
        if shortcut_keys:
            logger.debug(f"Configuring global interrupt shortcut: {shortcut_keys}")
            shortcut_toggler = ShortcutToggler(
                shortcut_keys=shortcut_keys,
                relaying_active=relaying_active,
                gadget_manager=gadget_manager,
            )

    relay_controller = RelayController(
        gadget_manager=gadget_manager,
        device_identifiers=args.device_ids,
        auto_discover=args.auto_discover,
        grab_devices=args.grab_devices,
        relaying_active=relaying_active,
        shortcut_toggler=shortcut_toggler,
    )

    udc_path = get_udc_path()
    if udc_path is None:
        logger.error("No UDC detected! USB Gadget mode may not be enabled.")
        return
    logger.debug(f"Detected UDC state file: {udc_path}")

    async with (
        UdevEventMonitor(relay_controller),
        UdcStateMonitor(
            relaying_active=relaying_active,
            udc_path=udc_path,
        ),
    ):
        relay_task = asyncio.create_task(relay_controller.async_relay_devices())
        await shutdown_event.wait()

        logger.debug("Shutdown event triggered. Cancelling relay task...")
        relay_task.cancel()
        await asyncio.gather(relay_task, return_exceptions=True)


async def async_list_devices():
    """
    Prints a list of available input devices and exits.

    :return: None
    :raises SystemExit: Always exits after listing devices
    """
    for dev in await async_list_input_devices():
        print(f"{dev.name}\t{dev.uniq if dev.uniq else dev.phys}\t{dev.path}")
    exit_safely()


def print_version():
    """
    Prints the version of Bluetooth 2 USB and exits.

    :return: None
    :raises SystemExit: Always exits after printing version
    """
    print(VERSIONED_NAME)
    exit_safely()


def exit_safely():
    """
    Safely exits the script. Unregisters usb_hid.disable()
    from atexit handlers to avoid potential exceptions.

    :return: None
    :raises SystemExit: Always exits
    """
    atexit.unregister(usb_hid.disable)
    sys.exit(0)


def validate_shortcut(shortcut: list[str]) -> set[str]:
    """
    Convert a list of raw key strings (e.g. ["SHIFT", "CTRL", "Q"])
    into a set of valid evdev-style names (e.g. {"KEY_LEFTSHIFT", "KEY_LEFTCTRL", "KEY_Q"}).

    :param shortcut: List of key strings to convert
    :type shortcut: list[str]
    :return: A set of normalized key names
    :rtype: set[str]
    """
    ALIAS_MAP = {
        "SHIFT": "LEFTSHIFT",
        "LSHIFT": "LEFTSHIFT",
        "RSHIFT": "RIGHTSHIFT",
        "CTRL": "LEFTCTRL",
        "LCTRL": "LEFTCTRL",
        "RCTRL": "RIGHTCTRL",
        "ALT": "LEFTALT",
        "LALT": "LEFTALT",
        "RALT": "RIGHTALT",
        "GUI": "LEFTMETA",
        "LMETA": "LEFTMETA",
        "RMETA": "RIGHTMETA",
    }

    valid_keys = set()
    for raw_key in shortcut:
        key_upper = raw_key.strip().upper()
        if key_upper in ALIAS_MAP:
            key_upper = ALIAS_MAP[key_upper]
        key_name = key_upper if key_upper.startswith("KEY_") else f"KEY_{key_upper}"
        valid_keys.add(key_name)

    return valid_keys


def get_udc_path() -> Path | None:
    """
    Dynamically find the UDC state file for the USB Device Controller.

    :return: The path to the "state" file for the first UDC or None if not found
    :rtype: Path | None
    """
    udc_root = Path("/sys/class/udc")

    if not udc_root.exists() or not udc_root.is_dir():
        return None

    controllers = [entry for entry in udc_root.iterdir() if entry.is_dir()]
    if not controllers:
        return None

    return controllers[0] / "state"


if __name__ == "__main__":
    """
    Entry point for the script.
    """
    try:
        asyncio.run(main())
    except Exception:
        logger.exception("Unhandled exception encountered. Aborting mission.")
        sys.exit(1)
