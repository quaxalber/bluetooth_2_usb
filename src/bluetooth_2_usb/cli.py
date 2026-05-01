from __future__ import annotations

import asyncio
import json
import os
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

logger = get_logger(__name__)


@dataclass(slots=True)
class EnvironmentStatus:
    """Describe whether local USB gadget runtime prerequisites are present."""

    configfs: bool
    udc_present: bool
    udc_path: Path | None

    @property
    def ok(self) -> bool:
        """Return whether all required environment checks passed.

        :return: The current value exposed by this property.
        """
        return self.configfs and self.udc_present

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dictionary representation.

        :return: The requested value or status result.
        """
        return {
            "configfs": self.configfs,
            "udc_present": self.udc_present,
            "udc_path": str(self.udc_path) if self.udc_path else None,
            "ok": self.ok,
        }


def get_udc_path() -> Path | None:
    """Find the USB device controller state file used for gadget monitoring.

    :return: The requested value or status result.
    """
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
        """Return the UDC state-file path below a controller directory.

        :return: The requested value or status result.
        """
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
    """Check whether the local system exposes the required USB gadget runtime paths.

    :return: The requested value or status result.
    """
    configfs_path = Path("/sys/kernel/config/usb_gadget")
    udc_path = get_udc_path()
    return EnvironmentStatus(
        configfs=configfs_path.is_dir(), udc_present=udc_path is not None, udc_path=udc_path
    )


def print_environment_status(status: EnvironmentStatus, output: str) -> None:
    """Print runtime environment status in the requested output format.

    :return: None.
    """
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
    """Print the package version banner.

    :return: The requested value or status result.
    """
    print(get_versioned_name())
    return EXIT_OK


def configure_logging(args: Arguments) -> None:
    """Configure package logging from parsed command-line arguments.

    :return: None.
    """
    if args.debug:
        get_logger().setLevel(DEBUG)

    if args.log_to_file:
        add_file_handler(args.log_path)

    logger.debug("CLI args: %s", args)


async def async_run(args: Arguments) -> int:
    """Run the asynchronous relay command flow for parsed arguments.

    :return: The requested value or status result.
    """
    if args.version:
        return print_version()

    if args.list_devices:
        from .inventory import DeviceEnumerationError, describe_input_devices, inventory_to_text

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

    logger.info("Launching %s", get_versioned_name())

    if not env_status.ok:
        if not env_status.configfs:
            logger.error("configfs gadget path is missing: /sys/kernel/config/usb_gadget")
        if not env_status.udc_present:
            logger.error("No UDC detected! USB gadget mode may not be enabled.")
        return EXIT_ENVIRONMENT

    logger.debug("Detected UDC state file: %s", env_status.udc_path)

    from .runtime import Runtime
    from .runtime_config import runtime_config_from_args

    runtime = Runtime(runtime_config_from_args(args, udc_path=env_status.udc_path))
    await runtime.run()

    return EXIT_OK


def run(argv: list[str] | None = None) -> int:
    """Run the command entrypoint and return a process-style exit code.

    :return: The requested value or status result.
    """
    raw_args = list(sys.argv[1:] if argv is None else argv)
    from .ops.cli import OPERATIONAL_COMMANDS
    from .ops.cli import main as operational_main

    if raw_args[:1] and raw_args[0] in OPERATIONAL_COMMANDS:
        return operational_main(raw_args, prog="bluetooth_2_usb")
    if raw_args[:1] == ["loopback"]:
        from .loopback import run as loopback_run

        return loopback_run(raw_args[1:])
    if raw_args[:1] and not raw_args[0].startswith("-"):
        print(
            f"Unknown command: {raw_args[0]}. "
            + "Use bluetooth_2_usb loopback inject/capture for loopback validation.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    from .args import parse_args

    try:
        args = parse_args(raw_args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else EXIT_OK

    try:
        return asyncio.run(async_run(args))
    except OSError as exc:
        logger.error("Runtime environment error: %s", exc)
        return EXIT_ENVIRONMENT
    except Exception:
        logger.exception("Unhandled exception encountered. Aborting mission.")
        return EXIT_RUNTIME
