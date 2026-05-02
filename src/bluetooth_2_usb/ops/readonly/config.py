from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..commands import fail
from ..paths import PATHS


@dataclass(slots=True)
class ReadonlyConfig:
    mode: str = "disabled"
    persist_mount: Path = PATHS.persist_mount
    persist_bluetooth_dir: Path = PATHS.default_persist_bluetooth_dir
    persist_spec: str = ""
    persist_device: str = ""


def load_readonly_config(path: Path = PATHS.readonly_env_file) -> ReadonlyConfig:
    if not path.is_file():
        return ReadonlyConfig(
            persist_mount=PATHS.persist_mount, persist_bluetooth_dir=PATHS.default_persist_bluetooth_dir
        )

    allowed = {
        "B2U_READONLY_MODE",
        "B2U_PERSIST_MOUNT",
        "B2U_PERSIST_BLUETOOTH_DIR",
        "B2U_PERSIST_SPEC",
        "B2U_PERSIST_DEVICE",
    }
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"', line)
        if match is None:
            fail(f"Refusing to load invalid read-only config line from {path}:{line_number}: {line}")
        key, value = match.groups()
        if key not in allowed:
            fail(f"Refusing to load unexpected key from {path}: {key}")
        values[key] = value

    persist_mount = _required_absolute_path(
        values.get("B2U_PERSIST_MOUNT", str(PATHS.persist_mount)), "B2U_PERSIST_MOUNT", path
    )
    persist_bluetooth_dir = _required_absolute_path(
        values.get("B2U_PERSIST_BLUETOOTH_DIR", str(PATHS.default_persist_bluetooth_dir)),
        "B2U_PERSIST_BLUETOOTH_DIR",
        path,
    )

    return ReadonlyConfig(
        mode=values.get("B2U_READONLY_MODE", "disabled"),
        persist_mount=persist_mount,
        persist_bluetooth_dir=persist_bluetooth_dir,
        persist_spec=values.get("B2U_PERSIST_SPEC", ""),
        persist_device=values.get("B2U_PERSIST_DEVICE", ""),
    )


def _required_absolute_path(raw_value: str, key: str, config_path: Path) -> Path:
    if not raw_value:
        fail(f"Refusing to load empty {key} from {config_path}")
    value = Path(raw_value)
    if not value.is_absolute():
        fail(f"Refusing to load relative {key} from {config_path}: {raw_value}")
    return value


def write_readonly_config(config: ReadonlyConfig, path: Path = PATHS.readonly_env_file) -> None:
    path.write_text(
        "\n".join(
            [
                f'B2U_READONLY_MODE="{config.mode}"',
                f'B2U_PERSIST_MOUNT="{config.persist_mount}"',
                f'B2U_PERSIST_BLUETOOTH_DIR="{config.persist_bluetooth_dir}"',
                f'B2U_PERSIST_SPEC="{config.persist_spec}"',
                f'B2U_PERSIST_DEVICE="{config.persist_device}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o644)
