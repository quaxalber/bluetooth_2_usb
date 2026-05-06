from __future__ import annotations

import sys

from .cli import EXIT_USAGE, run
from .service_settings import (
    ServiceSettingsError,
    build_runtime_argv,
    load_service_settings,
    normalize_service_settings_file,
)


def main() -> int:
    try:
        normalize_service_settings_file()
        settings = load_service_settings()
    except ServiceSettingsError as exc:
        print(f"Invalid bluetooth_2_usb service settings: {exc}", file=sys.stderr)
        return EXIT_USAGE

    return run(build_runtime_argv(settings))


if __name__ == "__main__":
    raise SystemExit(main())
