from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class GadgetNodes:
    """Host-side HID gadget node paths selected for loopback capture.

    :param keyboard_node: HID path selected for keyboard capture, if any.
    :param mouse_node: HID path selected for mouse capture, if any.
    :param consumer_node: HID path selected for consumer-control capture, if any.
    """

    keyboard_node: str | None
    mouse_node: str | None
    consumer_node: str | None

    def to_dict(self) -> dict[str, str | None]:
        """Serialize selected gadget node paths.

        :return: Dictionary with ``keyboard_node``, ``mouse_node``, and ``consumer_node`` values.
        """
        return {
            "keyboard_node": self.keyboard_node,
            "mouse_node": self.mouse_node,
            "consumer_node": self.consumer_node,
        }


@dataclass(slots=True)
class LoopbackResult:
    """Result of a loopback inject or capture command.

    :param command: Loopback subcommand that produced the result.
    :param scenario: Scenario name used by the command.
    :param success: Whether the command completed successfully.
    :param exit_code: Process-style exit code.
    :param message: Human-readable result summary.
    :param details: Structured command-specific details for JSON output.
    """

    command: str
    scenario: str
    success: bool
    exit_code: int
    message: str
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        """Serialize the loopback result for JSON output.

        :return: JSON-ready dictionary containing command, scenario, status, message, and details.
        """
        return asdict(self)

    def to_text(self) -> str:
        """Render the loopback result for human-readable terminal output.

        :return: Stable multi-line text representation.
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
