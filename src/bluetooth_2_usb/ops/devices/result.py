from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def normalize(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return normalize(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex(" ")
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [normalize(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted((normalize(item) for item in value), key=repr)
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def json_line(record: dict[str, object]) -> str:
    return json.dumps(normalize(record), sort_keys=True, separators=(",", ":")) + "\n"
