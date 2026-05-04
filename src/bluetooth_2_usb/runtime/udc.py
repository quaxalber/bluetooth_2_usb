from __future__ import annotations

from pathlib import Path

from .events import UdcState


def read_udc_state(udc_path: Path | None) -> UdcState:
    """
    Read and normalize a USB device controller state file.

    Missing or unreadable state is treated as not attached so callers can keep
    cable-state handling conservative.
    """
    if udc_path is None:
        return UdcState.NOT_ATTACHED

    try:
        with open(udc_path, encoding="utf-8") as handle:
            return UdcState.from_raw(handle.read())
    except OSError:
        return UdcState.NOT_ATTACHED
