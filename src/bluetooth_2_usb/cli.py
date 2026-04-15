from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass
from logging import DEBUG
from pathlib import Path
from typing import TYPE_CHECKING

from .logging import add_file_handler, get_logger
from .version import get_versioned_name

if TYPE_CHECKING:
    from .args import Arguments

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ENVIRONMENT = 3
EXIT_RUNTIME = 4
GRACEFUL_SHUTDOWN_TIMEOUT_SEC = 10.0

logger = get_logger()


@dataclass(slots=True)
class EnvironmentStatus:
    configfs: bool
    udc_present: bool
    udc_path: Path | None

    @property
    def ok(self) -> bool:
        return self.configfs and self.udc_present

    def to_dict(self) -> dict[str, object]:
        return {
            "configfs": self.configfs,
            "udc_present": self.udc_present,
            "udc_path": str(self.udc_path) if self.udc_path else None,
            "ok": self.ok,
        }


def get_udc_path() -> Path | None:
    override_path = os.environ.get("BLUETOOTH_2_USB_UDC_PATH")
    if override_path:
        candidate = Path(override_path)
        return candidate if candidate.is_file() else None

    udc_root = Path("/sys/class/udc")
    if not udc_root.is_dir():
        return None

    controllers = sorted(entry for entry in udc_root.iterdir() if entry.is_dir())
    if not controllers:
        return None

    def state_path(controller: Path) -> Path:
        return controller / "state"

    scored_controllers: list[tuple[int, str, Path]] = []
    for controller in controllers:
        candidate = state_path(controller)
        if not candidate.is_file():
            continue

        name = controller.name.lower()
        score = 0
        if any(token in name for token in ("otg", "gadget", "dwc2")):
            score += 100
        if name.startswith("2098") or name.startswith("fe98"):
            score += 25
        scored_controllers.append((score, controller.name, candidate))

    if scored_controllers:
        scored_controllers.sort(key=lambda item: (-item[0], item[1]))
        return scored_controllers[0][2]

    return None


def validate_environment() -> EnvironmentStatus:
    configfs_path = Path("/sys/kernel/config/usb_gadget")
    udc_path = get_udc_path()
    return EnvironmentStatus(
        configfs=configfs_path.is_dir(),
        udc_present=udc_path is not None,
        udc_path=udc_path,
    )


def print_environment_status(status: EnvironmentStatus, output: str) -> None:
    if output == "json":
        print(json.dumps(status.to_dict(), sort_keys=True))
        return

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


def configure_logging(args: Arguments) -> None:
    if args.debug:
        logger.setLevel(DEBUG)

    if args.log_to_file:
        add_file_handler(args.log_path)

    logger.debug(f"CLI args: {args}")


def _handled_shutdown_signals() -> tuple[signal.Signals, ...]:
    signals = [signal.SIGINT, signal.SIGTERM]
    for optional_name in ("SIGHUP", "SIGQUIT"):
        optional_signal = getattr(signal, optional_name, None)
        if optional_signal is not None:
            signals.append(optional_signal)
    return tuple(signals)


def _install_shutdown_signal_handlers(
    shutdown_event: asyncio.Event,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> tuple[dict[int, signal.Handlers], tuple[int, ...]]:
    active_loop = asyncio.get_running_loop() if loop is None else loop
    previous_handlers: dict[int, signal.Handlers] = {}
    loop_handled_signals: list[int] = []

    def _request_shutdown(sig_name: str) -> None:
        logger.debug(f"Received signal: {sig_name}. Requesting graceful shutdown.")
        shutdown_event.set()

    def _signal_handler(sig: int, frame) -> None:
        del frame
        sig_name = signal.Signals(sig).name
        _request_shutdown(sig_name)
        try:
            active_loop.call_soon_threadsafe(shutdown_event.set)
        except RuntimeError:
            shutdown_event.set()

    for handled_signal in _handled_shutdown_signals():
        sig_name = signal.Signals(handled_signal).name
        add_signal_handler = getattr(active_loop, "add_signal_handler", None)
        if add_signal_handler is not None:
            try:
                active_loop.add_signal_handler(
                    handled_signal,
                    _request_shutdown,
                    sig_name,
                )
                loop_handled_signals.append(handled_signal)
                continue
            except (NotImplementedError, RuntimeError, ValueError):
                pass
        previous_handlers[handled_signal] = signal.getsignal(handled_signal)
        signal.signal(handled_signal, _signal_handler)

    return previous_handlers, tuple(loop_handled_signals)


def _restore_signal_handlers(
    previous_handlers: dict[int, signal.Handlers],
    loop_handled_signals: tuple[int, ...],
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    active_loop = asyncio.get_running_loop() if loop is None else loop
    for handled_signal in loop_handled_signals:
        remove_signal_handler = getattr(active_loop, "remove_signal_handler", None)
        if remove_signal_handler is not None:
            remove_signal_handler(handled_signal)
    for handled_signal, previous_handler in previous_handlers.items():
        signal.signal(handled_signal, previous_handler)


async def async_run(args: Arguments) -> int:
    if args.version:
        return print_version()

    if args.list_devices:
        from .inventory import (
            DeviceEnumerationError,
            describe_input_devices,
            inventory_to_text,
        )

        try:
            devices = describe_input_devices()
        except DeviceEnumerationError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_ENVIRONMENT

        if args.output == "json":
            print(json.dumps([device.to_dict() for device in devices], sort_keys=True))
        else:
            print(inventory_to_text(devices))
        return EXIT_OK

    env_status = validate_environment()

    if args.validate_env:
        print_environment_status(env_status, args.output)
        return EXIT_OK if env_status.ok else EXIT_ENVIRONMENT

    configure_logging(args)

    logger.info(f"Launching {get_versioned_name()}")

    if not env_status.ok:
        if not env_status.configfs:
            logger.error(
                "configfs gadget path is missing: /sys/kernel/config/usb_gadget"
            )
        if not env_status.udc_present:
            logger.error("No UDC detected! USB gadget mode may not be enabled.")
        return EXIT_ENVIRONMENT

    relaying_active = asyncio.Event()

    from .relay import (
        GadgetManager,
        RelayController,
        RuntimeMonitor,
        ShortcutToggler,
    )

    gadget_manager = GadgetManager()
    gadget_manager.enable_gadgets()

    shortcut_toggler = None
    if args.interrupt_shortcut:
        shortcut_keys = set(args.interrupt_shortcut)
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
    previous_handlers, loop_handled_signals = _install_shutdown_signal_handlers(
        shutdown_event
    )

    try:
        async with RuntimeMonitor(
            relay_controller=relay_controller,
            relaying_active=relaying_active,
            udc_path=env_status.udc_path,
        ):
            relay_task = asyncio.create_task(relay_controller.async_relay_devices())
            shutdown_task = asyncio.create_task(shutdown_event.wait())
            done, _ = await asyncio.wait(
                {relay_task, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if relay_task in done:
                relay_controller.request_shutdown()
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
            relay_controller.request_shutdown()
            shutdown_task.cancel()
            try:
                await asyncio.wait_for(
                    relay_task,
                    timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SEC,
                )
            except TimeoutError:
                logger.warning(
                    "Relay shutdown exceeded %.1fs; cancelling remaining tasks.",
                    GRACEFUL_SHUTDOWN_TIMEOUT_SEC,
                )
                relay_task.cancel()
                await asyncio.gather(relay_task, return_exceptions=True)
            await asyncio.gather(shutdown_task, return_exceptions=True)
    finally:
        _restore_signal_handlers(
            previous_handlers,
            loop_handled_signals,
        )

    return EXIT_OK


def run(argv: list[str] | None = None) -> int:
    from .args import parse_args

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
