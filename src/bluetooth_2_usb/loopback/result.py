from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class GadgetNodes:
    """Store selected host-side HID gadget node paths for loopback capture."""

    keyboard_node: str | None
    mouse_node: str | None
    consumer_node: str | None

    def to_dict(self) -> dict[str, str | None]:
        """Return a JSON-serializable dictionary representation.

        :return: The requested value or status result.
        """
        return {
            "keyboard_node": self.keyboard_node,
            "mouse_node": self.mouse_node,
            "consumer_node": self.consumer_node,
        }


@dataclass(slots=True)
class LoopbackResult:
    """Store a loopback command result for text or JSON rendering."""

    command: str
    scenario: str
    success: bool
    exit_code: int
    message: str
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dictionary representation.

        :return: The requested value or status result.
        """
        return asdict(self)

    def to_text(self) -> str:
        """Render the loopback result as stable human-readable text.

        :return: The requested value or status result.
        """
        lines = [
            f"command: {self.command}",
            f"scenario: {self.scenario}",
            f"result: {'ok' if self.success else 'error'}",
            f"exit_code: {self.exit_code}",
            f"message: {self.message}",
        ]
        for key, value in sorted(self.details.items()):
            rendered = (
                json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
            )
            lines.append(f"{key}: {rendered}")
        return "\n".join(lines)
