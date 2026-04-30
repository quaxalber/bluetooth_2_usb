from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_ENV_FILE = Path("/etc/default/bluetooth_2_usb")
DEFAULT_LOG_PATH = "/var/log/bluetooth_2_usb/bluetooth_2_usb.log"
BOOL_KEYS = {"B2U_AUTO_DISCOVER", "B2U_GRAB_DEVICES", "B2U_LOG_TO_FILE", "B2U_DEBUG"}
RUNTIME_ENV_KEY_ORDER = (
    "B2U_AUTO_DISCOVER",
    "B2U_DEVICE_IDS",
    "B2U_GRAB_DEVICES",
    "B2U_INTERRUPT_SHORTCUT",
    "B2U_LOG_TO_FILE",
    "B2U_LOG_PATH",
    "B2U_DEBUG",
    "B2U_UDC_PATH",
)
ALLOWED_KEYS = BOOL_KEYS | {"B2U_INTERRUPT_SHORTCUT", "B2U_LOG_PATH", "B2U_DEVICE_IDS", "B2U_UDC_PATH"}


class ServiceSettingsError(ValueError):
    pass


@dataclass(slots=True)
class ServiceSettings:
    auto_discover: bool = True
    device_ids: list[str] = field(default_factory=list)
    grab_devices: bool = True
    interrupt_shortcut: str = "CTRL+SHIFT+F12"
    log_to_file: bool = False
    log_path: str = DEFAULT_LOG_PATH
    debug: bool = False
    udc_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_bool(raw_value: str, key: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ServiceSettingsError(f"Invalid boolean value for {key}: {raw_value!r}")


def _parse_value(raw_value: str) -> str:
    raw_value = raw_value.strip()
    if raw_value == "":
        return ""

    try:
        parts = shlex.split(raw_value, posix=True)
    except ValueError as exc:
        raise ServiceSettingsError(f"Invalid settings value: {raw_value!r}") from exc

    if len(parts) != 1:
        raise ServiceSettingsError(f"Expected a single settings value, got: {raw_value!r}")
    return parts[0]


def _parse_device_ids(raw_value: str) -> list[str]:
    return [device_id.strip() for device_id in raw_value.split(",") if device_id.strip()]


def _canonical_bool(value: bool) -> str:
    return "true" if value else "false"


def _quote_if_needed(value: str) -> str:
    return shlex.join([value]) if value else ""


def _canonical_value_for_key(key: str, settings: ServiceSettings) -> str:
    if key == "B2U_AUTO_DISCOVER":
        return _canonical_bool(settings.auto_discover)
    if key == "B2U_DEVICE_IDS":
        return _quote_if_needed(", ".join(settings.device_ids))
    if key == "B2U_GRAB_DEVICES":
        return _canonical_bool(settings.grab_devices)
    if key == "B2U_INTERRUPT_SHORTCUT":
        return settings.interrupt_shortcut
    if key == "B2U_LOG_TO_FILE":
        return _canonical_bool(settings.log_to_file)
    if key == "B2U_LOG_PATH":
        return _quote_if_needed(settings.log_path)
    if key == "B2U_DEBUG":
        return _canonical_bool(settings.debug)
    if key == "B2U_UDC_PATH":
        return _quote_if_needed(settings.udc_path)
    raise ServiceSettingsError(f"Unexpected runtime settings key: {key!r}")


def load_service_settings(env_file: Path = DEFAULT_ENV_FILE) -> ServiceSettings:
    settings = ServiceSettings()
    if not env_file.exists():
        return settings

    for line_number, raw_line in enumerate(env_file.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in raw_line:
            raise ServiceSettingsError(f"{env_file}:{line_number}: expected KEY=value, got {raw_line!r}")

        key, raw_value = raw_line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_KEYS:
            raise ServiceSettingsError(f"{env_file}:{line_number}: unexpected key {key!r} in runtime settings")

        value = _parse_value(raw_value)
        if key == "B2U_AUTO_DISCOVER":
            settings.auto_discover = _parse_bool(value, key)
        elif key == "B2U_GRAB_DEVICES":
            settings.grab_devices = _parse_bool(value, key)
        elif key == "B2U_INTERRUPT_SHORTCUT":
            settings.interrupt_shortcut = value
        elif key == "B2U_LOG_TO_FILE":
            settings.log_to_file = _parse_bool(value, key)
        elif key == "B2U_LOG_PATH":
            settings.log_path = value
        elif key == "B2U_DEBUG":
            settings.debug = _parse_bool(value, key)
        elif key == "B2U_DEVICE_IDS":
            settings.device_ids = _parse_device_ids(value)
        elif key == "B2U_UDC_PATH":
            settings.udc_path = value

    return settings


def canonicalize_service_settings_bools(env_file: Path = DEFAULT_ENV_FILE) -> bool:
    if not env_file.exists():
        return False

    original_text = env_file.read_text(encoding="utf-8")
    settings = load_service_settings(env_file)
    leading_lines: list[str] = []
    trailing_lines: list[str] = []
    seen_key = False

    for line_number, raw_line in enumerate(original_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            if not seen_key:
                leading_lines.append(raw_line)
            continue

        if line.startswith("#"):
            if seen_key:
                trailing_lines.append(raw_line)
            else:
                leading_lines.append(raw_line)
            continue

        if "=" not in raw_line:
            raise ServiceSettingsError(f"{env_file}:{line_number}: expected KEY=value, got {raw_line!r}")

        key, raw_value = raw_line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_KEYS:
            raise ServiceSettingsError(f"{env_file}:{line_number}: unexpected key {key!r} in runtime settings")
        seen_key = True

    updated_lines = [
        *leading_lines,
        *[f"{key}={_canonical_value_for_key(key, settings)}" for key in RUNTIME_ENV_KEY_ORDER],
        *trailing_lines,
    ]
    updated_text = "\n".join(updated_lines)
    if original_text.endswith("\n"):
        updated_text += "\n"

    if updated_text == original_text:
        return False

    env_file.write_text(updated_text, encoding="utf-8")
    return True


def build_runtime_argv(settings: ServiceSettings, *, append_debug: bool = False) -> list[str]:
    argv: list[str] = []
    if settings.auto_discover:
        argv.append("--auto_discover")
    if settings.device_ids:
        argv.extend(["--device_ids", ",".join(settings.device_ids)])
    if settings.grab_devices:
        argv.append("--grab_devices")
    if settings.interrupt_shortcut:
        argv.extend(["--interrupt_shortcut", settings.interrupt_shortcut])
    if settings.log_to_file:
        argv.append("--log_to_file")
    if settings.log_path:
        argv.extend(["--log_path", settings.log_path])
    if settings.udc_path:
        argv.extend(["--udc_path", settings.udc_path])
    if settings.debug or append_debug:
        argv.append("--debug")
    return argv


def build_runtime_shell_command(
    executable: str,
    *,
    settings: ServiceSettings | None = None,
    env_file: Path = DEFAULT_ENV_FILE,
    append_debug: bool = False,
) -> str:
    resolved_settings = load_service_settings(env_file) if settings is None else settings
    command = shlex.split(executable) + build_runtime_argv(resolved_settings, append_debug=append_debug)
    return shlex.join(command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect bluetooth_2_usb service settings.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Validate the settings file.")
    group.add_argument(
        "--print-shell-command", action="store_true", help="Print a shell-quoted command for the configured runtime."
    )
    group.add_argument("--print-summary-json", action="store_true", help="Print the parsed settings as JSON.")
    group.add_argument(
        "--canonicalize-bools",
        action="store_true",
        help="Rewrite boolean values in place using canonical true/false values.",
    )
    parser.add_argument(
        "--executable",
        default=f"{sys.executable} -m bluetooth_2_usb",
        help="Executable command to use with --print-shell-command.",
    )
    parser.add_argument("--append-debug", action="store_true", help="Append --debug to the generated runtime command.")
    args = parser.parse_args(argv)

    try:
        settings = load_service_settings()
    except ServiceSettingsError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.check:
        return 0
    if args.print_shell_command:
        print(
            build_runtime_shell_command(
                args.executable, settings=settings, append_debug=args.append_debug, env_file=DEFAULT_ENV_FILE
            )
        )
        return 0
    if args.print_summary_json:
        print(json.dumps(settings.to_dict(), sort_keys=True))
        return 0
    if args.canonicalize_bools:
        canonicalize_service_settings_bools()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
