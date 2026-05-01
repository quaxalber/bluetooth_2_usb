from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProbeStatus(StrEnum):
    """Enumerate smoke-test probe severities."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Store one smoke-test probe outcome for text or JSON reporting."""

    status: ProbeStatus
    message: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable dictionary representation.

        :return: The requested value or status result.
        """
        return {
            "status": self.status.value,
            "message": self.message,
            "detail": self.detail,
        }
