from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class GadgetNodes:
    keyboard_node: str | None
    mouse_node: str | None
    consumer_node: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {"keyboard_node": self.keyboard_node, "mouse_node": self.mouse_node, "consumer_node": self.consumer_node}


@dataclass(slots=True)
class LoopbackResult:
    command: str
    scenario: str
    success: bool
    exit_code: int
    message: str
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "scenario": self.scenario,
            "success": self.success,
            "exit_code": self.exit_code,
            "message": self.message,
            "details": _normalize_detail(self.details),
        }

    def to_text(self) -> str:
        lines = [
            f"command: {self.command}",
            f"scenario: {self.scenario}",
            f"result: {'ok' if self.success else 'error'}",
            f"exit_code: {self.exit_code}",
            f"message: {self.message}",
        ]
        for key, value in sorted(self.details.items()):
            rendered = _render_detail(value)
            lines.append(f"{key}: {rendered}")
        return "\n".join(lines)


def _render_detail(value: object) -> str:
    normalized = _normalize_detail(value)
    if isinstance(normalized, (dict, list)):
        return json.dumps(normalized, sort_keys=True)
    return str(normalized)


def _normalize_detail(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize_detail(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _normalize_detail(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_detail(item) for item in value]
    if isinstance(value, set):
        return sorted((_normalize_detail(item) for item in value), key=repr)
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value
