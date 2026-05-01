from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..commands import fail
from ..paths import PATHS


@dataclass(slots=True)
class ReadonlyConfig:
    """Store persistent read-only mode configuration loaded from disk."""

    mode: str = "disabled"
    persist_mount: Path = PATHS.persist_mount
    persist_bluetooth_dir: Path = PATHS.persist_bluetooth_dir
    persist_spec: str = ""
    persist_device: str = ""


def load_readonly_config(path: Path = PATHS.readonly_env_file) -> ReadonlyConfig:
    """Load persistent read-only mode configuration from disk.

    :return: The requested value or status result.
    """
    config = ReadonlyConfig()
    if not path.is_file():
        return config

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
            fail(
                f"Refusing to load invalid read-only config line from {path}:{line_number}: {line}"
            )
        key, value = match.groups()
        if key not in allowed:
            fail(f"Refusing to load unexpected key from {path}: {key}")
        values[key] = value

    persist_mount = Path(values.get("B2U_PERSIST_MOUNT", str(PATHS.persist_mount)))
    persist_bluetooth_dir = Path(
        values.get("B2U_PERSIST_BLUETOOTH_DIR", str(PATHS.persist_bluetooth_dir))
    )

    return ReadonlyConfig(
        mode=values.get("B2U_READONLY_MODE", "disabled"),
        persist_mount=persist_mount,
        persist_bluetooth_dir=persist_bluetooth_dir,
        persist_spec=values.get("B2U_PERSIST_SPEC", ""),
        persist_device=values.get("B2U_PERSIST_DEVICE", ""),
    )


def write_readonly_config(config: ReadonlyConfig, path: Path = PATHS.readonly_env_file) -> None:
    """Write persistent read-only mode configuration to disk.

    :return: None.
    """
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
