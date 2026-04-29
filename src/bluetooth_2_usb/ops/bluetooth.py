from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .commands import info, ok, output, run, warn


def bluetoothctl_show() -> str:
    return output(["bluetoothctl", "show"])


def bluetoothctl_paired_devices() -> str:
    return output(["bluetoothctl", "devices", "Paired"])


def btmgmt_info() -> str:
    return output(["btmgmt", "info"])


def bluetooth_controller_powered_from_text(text: str) -> bool:
    return any(line.strip() == "Powered: yes" for line in text.splitlines())


def bluetooth_controller_powered() -> bool:
    try:
        return bluetooth_controller_powered_from_text(bluetoothctl_show())
    except Exception:
        return False


def bluetooth_paired_count() -> int:
    return sum(
        1 for line in bluetoothctl_paired_devices().splitlines() if line.startswith("Device ")
    )


def rfkill_root() -> Path:
    return Path(os.environ.get("B2U_RFKILL_ROOT", "/sys/class/rfkill"))


@dataclass(frozen=True, slots=True)
class RfkillEntry:
    name: str
    soft: str
    hard: str
    state: str

    def line(self) -> str:
        return (
            f"{self.name} type=bluetooth soft={self.soft} " f"hard={self.hard} state={self.state}"
        )


def bluetooth_rfkill_entries(root: Path | None = None) -> list[RfkillEntry]:
    base = rfkill_root() if root is None else root
    entries: list[RfkillEntry] = []
    for type_file in sorted(base.glob("rfkill*/type")):
        if not type_file.is_file():
            continue
        if type_file.read_text(encoding="utf-8", errors="replace").strip() != "bluetooth":
            continue
        rfkill_dir = type_file.parent
        entries.append(
            RfkillEntry(
                name=rfkill_dir.name,
                soft=_read_optional(rfkill_dir / "soft"),
                hard=_read_optional(rfkill_dir / "hard"),
                state=_read_optional(rfkill_dir / "state"),
            )
        )
    return entries


def _read_optional(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "?"


def bluetooth_rfkill_blocked(root: Path | None = None) -> bool:
    return any(
        entry.soft == "1" or entry.hard == "1" or entry.state == "0"
        for entry in bluetooth_rfkill_entries(root)
    )


def clear_bluetooth_rfkill_soft_blocks(root: Path | None = None) -> None:
    base = rfkill_root() if root is None else root
    entries = bluetooth_rfkill_entries(base)
    if not entries:
        info("No bluetooth rfkill entries found; skipping soft-block cleanup.")
        return

    for entry in entries:
        if entry.hard == "1":
            warn(f"Bluetooth rfkill {entry.name} is hard-blocked; leaving it unchanged.")
            continue
        if entry.soft != "1":
            info(
                f"Bluetooth rfkill {entry.name} is already unblocked "
                f"(soft={entry.soft} state={entry.state})."
            )
            continue

        soft_file = base / entry.name / "soft"
        try:
            soft_file.write_text("0\n", encoding="utf-8")
        except OSError:
            warn(f"Failed to clear Bluetooth rfkill soft block for {entry.name}.")
            continue

        soft = _read_optional(soft_file)
        state = _read_optional(base / entry.name / "state")
        if soft == "0":
            ok(f"Cleared Bluetooth rfkill soft block for {entry.name} (state={state}).")
        else:
            warn(f"Attempted to clear Bluetooth rfkill {entry.name}, but soft={soft} afterwards.")


def rfkill_list_bluetooth() -> str:
    completed = run(["rfkill", "list", "bluetooth"], check=False, capture=True)
    lines = [completed.stdout.rstrip()]
    lines.extend(entry.line() for entry in bluetooth_rfkill_entries())
    return "\n".join(line for line in lines if line)
