from __future__ import annotations

import os
import sys

from .cli import EXIT_USAGE, run
from .service_settings import ServiceSettingsError, build_runtime_argv, load_service_settings


def main() -> int:
    try:
        settings = load_service_settings()
    except ServiceSettingsError as exc:
        print(f"Invalid bluetooth_2_usb service settings: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if settings.udc_path:
        os.environ["BLUETOOTH_2_USB_UDC_PATH"] = settings.udc_path
    else:
        os.environ.pop("BLUETOOTH_2_USB_UDC_PATH", None)

    return run(build_runtime_argv(settings))


if __name__ == "__main__":
    raise SystemExit(main())
