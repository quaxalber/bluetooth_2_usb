import asyncio
import atexit
from logging import DEBUG
import signal
import sys

import usb_hid

from src.bluetooth_2_usb.args import parse_args
from src.bluetooth_2_usb.logging import add_file_handler, get_logger
from src.bluetooth_2_usb.relay import (
    GadgetManager,
    RelayController,
    ShortcutToggler,
    UdevEventMonitor,
    async_list_input_devices,
)

logger = get_logger()
VERSION = "0.9.0"
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

    relay_active_event = asyncio.Event()
    relay_active_event.set()

    shortcut_toggler = None
    if args.interrupt_shortcut:
        shortcut_keys = validate_shortcut(args.interrupt_shortcut)
        if shortcut_keys:
            logger.debug(f"Configuring global interrupt shortcut: {shortcut_keys}")

            shortcut_toggler = ShortcutToggler(shortcut_keys, relay_active_event)

    gadget_manager = GadgetManager()
    gadget_manager.enable_gadgets()

    relay_controller = RelayController(
        gadget_manager=gadget_manager,
        device_identifiers=args.device_ids,
        auto_discover=args.auto_discover,
        grab_devices=args.grab_devices,
        relay_active_event=relay_active_event,
        shortcut_toggler=shortcut_toggler,
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


def validate_shortcut(shortcut: list[str]) -> set[str]:
    """
    Converts a list of raw key strings (e.g. ["SHIFT", "CTRL", "Q"]) into a set of
    valid evdev-style names (e.g. {"KEY_LEFTSHIFT", "KEY_LEFTCTRL", "KEY_Q"}).

    This function:
      - Uppercases each entry,
      - Maps certain aliases (LSHIFT -> LEFTSHIFT, SHIFT -> LEFTSHIFT, etc.),
      - Prefixes with "KEY_" if missing,
      - Checks membership in ECodes.__members__.

    Raises ValueError if you want to enforce membership in your ECodes, but here it's commented out.
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

        # if key_name not in ECodes.__members__:
        #     raise ValueError(f"Invalid key '{raw_key}' -> '{key_name}' is not a recognized ECode")

        valid_keys.add(key_name)

    return valid_keys


if __name__ == "__main__":
    """
    Entry point for the script.
    """
    try:
        asyncio.run(main())
    except Exception:
        logger.exception("Unhandled exception encountered. Aborting mission.")
        sys.exit(1)
