from __future__ import annotations

import os
import sys

from .cli import EXIT_USAGE, run
from .service_config import ServiceConfigError, build_cli_argv, load_service_config


def main() -> int:
    try:
        config = load_service_config()
    except ServiceConfigError as exc:
        print(f"Invalid bluetooth_2_usb service config: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if config.udc_path:
        os.environ["BLUETOOTH_2_USB_UDC_PATH"] = config.udc_path

    return run(build_cli_argv(config))


if __name__ == "__main__":
    raise SystemExit(main())
