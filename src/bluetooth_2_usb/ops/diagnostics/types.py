from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProbeStatus(StrEnum):
    """Severity of one diagnostics or smoke-test probe result."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One diagnostics probe result shown in text and JSON smoke-test output.

    :param status: Probe severity.
    :param message: Human-readable probe summary.
    :param detail: Optional detail text shown after the summary.
    """

    status: ProbeStatus
    message: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serialize this probe result for JSON output.

        :return: Dictionary containing ``status``, ``message``, and ``detail`` strings.
        """
        return {
            "status": self.status.value,
            "message": self.message,
            "detail": self.detail,
        }
