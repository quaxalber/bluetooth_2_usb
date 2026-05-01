from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProbeStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: ProbeStatus
    message: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status.value,
            "message": self.message,
            "detail": self.detail,
        }
