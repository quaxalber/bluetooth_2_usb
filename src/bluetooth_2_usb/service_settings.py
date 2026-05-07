from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .inputs.filter import parse_devices

DEFAULT_ENV_FILE = Path("/etc/default/bluetooth_2_usb")
BOOL_KEYS = {"B2U_AUTO", "B2U_GRAB_DEVICES", "B2U_DEBUG"}
RUNTIME_ENV_KEY_ORDER = ("B2U_AUTO", "B2U_DEVICES", "B2U_GRAB_DEVICES", "B2U_SHORTCUT", "B2U_DEBUG")
ALLOWED_KEYS = BOOL_KEYS | {"B2U_SHORTCUT", "B2U_DEVICES"}


class ServiceSettingsError(ValueError):
    pass


@dataclass(slots=True)
class ServiceSettings:
    auto: bool = True
    devices: list[str] = field(default_factory=list)
    grab: bool = True
    shortcut: str = "CTRL+SHIFT+F12"
    debug: bool = False

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


def _parse_devices(raw_value: str) -> list[str]:
    if not raw_value.strip():
        return []
    try:
        return parse_devices(raw_value)
    except ValueError as exc:
        raise ServiceSettingsError(f"Invalid device filter list: {raw_value!r}") from exc


def _canonical_bool(value: bool) -> str:
    return "true" if value else "false"


def _quote_if_needed(value: str) -> str:
    return shlex.join([value]) if value else ""


def _canonical_value_for_key(key: str, settings: ServiceSettings) -> str:
    if key == "B2U_AUTO":
        return _canonical_bool(settings.auto)
    if key == "B2U_DEVICES":
        return _quote_if_needed(", ".join(settings.devices))
    if key == "B2U_GRAB_DEVICES":
        return _canonical_bool(settings.grab)
    if key == "B2U_SHORTCUT":
        return _quote_if_needed(settings.shortcut)
    if key == "B2U_DEBUG":
        return _canonical_bool(settings.debug)
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
        if key == "B2U_AUTO":
            settings.auto = _parse_bool(value, key)
        elif key == "B2U_GRAB_DEVICES":
            settings.grab = _parse_bool(value, key)
        elif key == "B2U_SHORTCUT":
            settings.shortcut = value
        elif key == "B2U_DEBUG":
            settings.debug = _parse_bool(value, key)
        elif key == "B2U_DEVICES":
            settings.devices = _parse_devices(value)

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


def normalize_service_settings_file(env_file: Path = DEFAULT_ENV_FILE) -> bool:
    if not env_file.exists():
        return False

    original_text = env_file.read_text(encoding="utf-8")
    original_lines = original_text.splitlines()
    key_migrations = {
        "B2U_AUTO_DISCOVER": "B2U_AUTO",
        "B2U_DEVICE_IDS": "B2U_DEVICES",
        "B2U_INTERRUPT_SHORTCUT": "B2U_SHORTCUT",
    }
    removed_keys = {"B2U_LOG_PATH", "B2U_LOG_TO_FILE", "B2U_UDC_PATH", "B2U_USB_SERIAL", "B2U_USB_PRODUCT_SUFFIX"}
    target_keys = set(key_migrations.values())
    non_empty_targets = {
        key
        for key in target_keys
        if any(_line_key(line) == key and not _line_value_is_blank(line) for line in original_lines)
    }
    updated_lines: list[str] = []
    changed = False

    for line in original_lines:
        key = _line_key(line)
        if key in removed_keys:
            changed = True
            continue

        if key in target_keys:
            has_non_empty_legacy = any(
                current_target == key and _line_key(candidate) == legacy and not _line_value_is_blank(candidate)
                for legacy, current_target in key_migrations.items()
                for candidate in original_lines
            )
            if key not in non_empty_targets and has_non_empty_legacy:
                changed = True
                continue
            updated_lines.append(line)
            continue

        if key not in key_migrations:
            updated_lines.append(line)
            continue

        changed = True
        target_key = key_migrations[key]
        if target_key not in non_empty_targets:
            updated_lines.append(line.replace(key, target_key, 1))
            non_empty_targets.add(target_key)

    if not changed:
        return False

    updated_text = "\n".join(updated_lines)
    if original_text.endswith("\n"):
        updated_text += "\n"
    env_file.write_text(updated_text, encoding="utf-8")
    return True


def _line_key(raw_line: str) -> str | None:
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in raw_line:
        return None
    key, _raw_value = raw_line.split("=", 1)
    return key.strip()


def _line_value_is_blank(raw_line: str) -> bool:
    _key, raw_value = raw_line.split("=", 1)
    try:
        return _parse_value(raw_value) == ""
    except ServiceSettingsError:
        return False


def build_runtime_argv(settings: ServiceSettings, *, append_debug: bool = False) -> list[str]:
    argv: list[str] = []
    if settings.auto:
        argv.append("--auto")
    if settings.devices:
        argv.extend(["--devices", ",".join(settings.devices)])
    if settings.grab:
        argv.append("--grab")
    if settings.shortcut:
        argv.extend(["--shortcut", settings.shortcut])
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
        normalize_service_settings_file()
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
