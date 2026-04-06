import asyncio
import signal
from dataclasses import dataclass
from logging import DEBUG
from pathlib import Path

from .args import Arguments, parse_args
from .logging import add_file_handler, get_logger
from .version import get_versioned_name

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ENVIRONMENT = 3
EXIT_RUNTIME = 4

logger = get_logger()


@dataclass(slots=True)
class EnvironmentStatus:
    configfs: bool
    udc_present: bool
    udc_path: Path | None

    @property
    def ok(self) -> bool:
        return self.configfs and self.udc_present


def get_udc_path() -> Path | None:
    udc_root = Path("/sys/class/udc")
    if not udc_root.is_dir():
        return None

    controllers = [entry for entry in udc_root.iterdir() if entry.is_dir()]
    if not controllers:
        return None

    def state_path(controller: Path) -> Path:
        return controller / "state"

    otg_candidates = [
        controller
        for controller in controllers
        if any(token in controller.name.lower() for token in ("otg", "gadget", "dwc2"))
        and state_path(controller).is_file()
    ]
    if otg_candidates:
        return state_path(otg_candidates[0])

    valid_controllers = [
        controller for controller in controllers if state_path(controller).is_file()
    ]
    if valid_controllers:
        return state_path(valid_controllers[0])

    return None


def validate_environment() -> EnvironmentStatus:
    configfs_path = Path("/sys/kernel/config/usb_gadget")
    udc_path = get_udc_path()
    return EnvironmentStatus(
        configfs=configfs_path.is_dir(),
        udc_present=udc_path is not None,
        udc_path=udc_path,
    )


def print_environment_status(status: EnvironmentStatus) -> None:
    lines = [
        f"configfs: {'ok' if status.configfs else 'missing'}",
        f"udc: {'ok' if status.udc_present else 'missing'}",
        f"udc_path: {status.udc_path if status.udc_path else 'n/a'}",
    ]
    for line in lines:
        print(line)


def print_version() -> int:
    print(get_versioned_name())
    return EXIT_OK


def validate_shortcut(shortcut: list[str]) -> set[str]:
    alias_map = {
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
        key_upper = alias_map.get(key_upper, key_upper)
        key_name = key_upper if key_upper.startswith("KEY_") else f"KEY_{key_upper}"
        valid_keys.add(key_name)

    return valid_keys


async def async_list_devices() -> int:
    from .relay import async_list_input_devices

    for dev in await async_list_input_devices():
        print(f"{dev.name}\t{dev.uniq if dev.uniq else dev.phys}\t{dev.path}")
    return EXIT_OK


async def async_run_diagnostics(
    env_status: EnvironmentStatus,
    *,
    list_devices: bool = True,
) -> int:
    print_environment_status(env_status)
    if list_devices and env_status.ok:
        from .relay import async_list_input_devices

        devices = await async_list_input_devices()
        logger.info(f"Detected {len(devices)} input device(s).")
    elif list_devices:
        logger.info(
            "Skipping input device enumeration because gadget prerequisites are missing."
        )
    return EXIT_OK if env_status.ok else EXIT_ENVIRONMENT


def configure_logging(args: Arguments) -> None:
    if args.debug:
        logger.setLevel(DEBUG)

    if args.log_to_file:
        add_file_handler(args.log_path)

    logger.debug(f"CLI args: {args}")


async def async_run(args: Arguments) -> int:
    configure_logging(args)

    if args.version:
        return print_version()

    if args.list_devices:
        return await async_list_devices()

    env_status = validate_environment()

    if args.validate_env:
        print_environment_status(env_status)
        return EXIT_OK if env_status.ok else EXIT_ENVIRONMENT

    logger.info(f"Launching {get_versioned_name()}")
    logger.info(f"HID profile: {args.hid_profile}")

    if args.dry_run or args.no_bind:
        return await async_run_diagnostics(env_status)

    if not env_status.ok:
        if not env_status.configfs:
            logger.error(
                "configfs gadget path is missing: /sys/kernel/config/usb_gadget"
            )
        if not env_status.udc_present:
            logger.error("No UDC detected! USB gadget mode may not be enabled.")
        return EXIT_ENVIRONMENT

    relaying_active = asyncio.Event()
    relaying_active.clear()

    from .relay import (
        GadgetManager,
        RelayController,
        ShortcutToggler,
        UdcStateMonitor,
        UdevEventMonitor,
    )

    gadget_manager = GadgetManager(hid_profile=args.hid_profile)
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

    logger.debug(f"Detected UDC state file: {env_status.udc_path}")
    shutdown_event = asyncio.Event()
    previous_handlers = {}

    def _signal_handler(sig: int, frame) -> None:
        del frame
        sig_name = signal.Signals(sig).name
        logger.debug(f"Received signal: {sig_name}. Requesting graceful shutdown.")
        shutdown_event.set()

    for handled_signal in (
        signal.SIGINT,
        signal.SIGTERM,
        signal.SIGHUP,
        signal.SIGQUIT,
    ):
        previous_handlers[handled_signal] = signal.getsignal(handled_signal)
        signal.signal(handled_signal, _signal_handler)

    try:
        async with (
            UdevEventMonitor(relay_controller),
            UdcStateMonitor(
                relaying_active=relaying_active, udc_path=env_status.udc_path
            ),
        ):
            relay_task = asyncio.create_task(relay_controller.async_relay_devices())
            shutdown_task = asyncio.create_task(shutdown_event.wait())
            done, _ = await asyncio.wait(
                {relay_task, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if relay_task in done:
                if relay_task.cancelled():
                    logger.error(
                        "Relay task was cancelled before shutdown was requested."
                    )
                else:
                    relay_exc = relay_task.exception()
                    if relay_exc is None:
                        logger.error(
                            "Relay task exited unexpectedly before shutdown was requested."
                        )
                    else:
                        logger.error(
                            "Relay task exited unexpectedly before shutdown was requested: %s",
                            relay_exc,
                        )
                if not shutdown_task.done():
                    shutdown_task.cancel()
                await asyncio.gather(relay_task, shutdown_task, return_exceptions=True)
                return EXIT_RUNTIME

            logger.debug("Shutdown event triggered. Cancelling relay task...")
            relay_task.cancel()
            shutdown_task.cancel()
            await asyncio.gather(relay_task, shutdown_task, return_exceptions=True)
    finally:
        for handled_signal, previous_handler in previous_handlers.items():
            signal.signal(handled_signal, previous_handler)

    return EXIT_OK


def run(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else EXIT_OK

    try:
        return asyncio.run(async_run(args))
    except OSError as exc:
        logger.error(f"Runtime environment error: {exc}")
        return EXIT_ENVIRONMENT
    except Exception:
        logger.exception("Unhandled exception encountered. Aborting mission.")
        return EXIT_RUNTIME
