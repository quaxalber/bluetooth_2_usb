from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_ENV_FILE = Path("/etc/default/bluetooth_2_usb")
DEFAULT_LOG_PATH = "/var/log/bluetooth_2_usb/bluetooth_2_usb.log"


class ServiceConfigError(ValueError):
    pass


@dataclass(slots=True)
class ServiceConfig:
    auto_discover: bool = True
    grab_devices: bool = True
    interrupt_shortcut: str = "CTRL+SHIFT+F12"
    log_to_file: bool = False
    log_path: str = DEFAULT_LOG_PATH
    debug: bool = False
    device_ids: list[str] = field(default_factory=list)
    udc_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_bool(raw_value: str, key: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ServiceConfigError(f"Invalid boolean value for {key}: {raw_value!r}")


def _parse_value(raw_value: str) -> str:
    raw_value = raw_value.strip()
    if raw_value == "":
        return ""

    try:
        parts = shlex.split(raw_value, posix=True)
    except ValueError as exc:
        raise ServiceConfigError(f"Invalid config value: {raw_value!r}") from exc

    if len(parts) != 1:
        raise ServiceConfigError(f"Expected a single config value, got: {raw_value!r}")
    return parts[0]


def _parse_device_ids(raw_value: str) -> list[str]:
    return [
        device_id.strip() for device_id in raw_value.split(",") if device_id.strip()
    ]


def load_service_config(env_file: Path = DEFAULT_ENV_FILE) -> ServiceConfig:
    config = ServiceConfig()
    if not env_file.exists():
        return config

    allowed_keys = {
        "B2U_AUTO_DISCOVER",
        "B2U_GRAB_DEVICES",
        "B2U_INTERRUPT_SHORTCUT",
        "B2U_LOG_TO_FILE",
        "B2U_LOG_PATH",
        "B2U_DEBUG",
        "B2U_DEVICE_IDS",
        "B2U_UDC_PATH",
    }

    for line_number, raw_line in enumerate(
        env_file.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in raw_line:
            raise ServiceConfigError(
                f"{env_file}:{line_number}: expected KEY=value, got {raw_line!r}"
            )

        key, raw_value = raw_line.split("=", 1)
        key = key.strip()
        if key not in allowed_keys:
            raise ServiceConfigError(
                f"{env_file}:{line_number}: unexpected key {key!r} in runtime config"
            )

        value = _parse_value(raw_value)
        if key == "B2U_AUTO_DISCOVER":
            config.auto_discover = _parse_bool(value, key)
        elif key == "B2U_GRAB_DEVICES":
            config.grab_devices = _parse_bool(value, key)
        elif key == "B2U_INTERRUPT_SHORTCUT":
            config.interrupt_shortcut = value
        elif key == "B2U_LOG_TO_FILE":
            config.log_to_file = _parse_bool(value, key)
        elif key == "B2U_LOG_PATH":
            config.log_path = value
        elif key == "B2U_DEBUG":
            config.debug = _parse_bool(value, key)
        elif key == "B2U_DEVICE_IDS":
            config.device_ids = _parse_device_ids(value)
        elif key == "B2U_UDC_PATH":
            config.udc_path = value

    return config


def build_cli_argv(config: ServiceConfig, *, append_debug: bool = False) -> list[str]:
    argv: list[str] = []
    if config.auto_discover:
        argv.append("--auto_discover")
    if config.device_ids:
        argv.extend(["--device_ids", ",".join(config.device_ids)])
    if config.grab_devices:
        argv.append("--grab_devices")
    if config.interrupt_shortcut:
        argv.extend(["--interrupt_shortcut", config.interrupt_shortcut])
    if config.log_to_file:
        argv.append("--log_to_file")
    if config.log_path:
        argv.extend(["--log_path", config.log_path])
    if config.debug or append_debug:
        argv.append("--debug")
    return argv


def build_shell_command(
    executable: str,
    *,
    config: ServiceConfig | None = None,
    env_file: Path = DEFAULT_ENV_FILE,
    append_debug: bool = False,
) -> str:
    resolved_config = load_service_config(env_file) if config is None else config
    command = shlex.split(executable) + build_cli_argv(
        resolved_config, append_debug=append_debug
    )
    return shlex.join(command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect bluetooth_2_usb service config."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Validate the config file.")
    group.add_argument(
        "--print-shell-command",
        action="store_true",
        help="Print a shell-quoted command for the configured runtime.",
    )
    group.add_argument(
        "--print-summary-json",
        action="store_true",
        help="Print the parsed config as JSON.",
    )
    parser.add_argument(
        "--executable",
        default=f"{sys.executable} -m bluetooth_2_usb",
        help="Executable command to use with --print-shell-command.",
    )
    parser.add_argument(
        "--append-debug",
        action="store_true",
        help="Append --debug to the generated runtime command.",
    )
    args = parser.parse_args(argv)

    try:
        config = load_service_config()
    except ServiceConfigError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.check:
        return 0
    if args.print_shell_command:
        print(
            build_shell_command(
                args.executable,
                config=config,
                append_debug=args.append_debug,
                env_file=DEFAULT_ENV_FILE,
            )
        )
        return 0
    if args.print_summary_json:
        print(json.dumps(config.to_dict(), sort_keys=True))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
