#!/usr/bin/python3
"""
Tray indicator for the bluetooth_2_usb service, for the Pi's own desktop.

Shows whether the mouse jiggler is on and where keyboard/mouse input currently
goes, read from the status file the service publishes. Display only.

Runs with the system Python (needs python3-gi and gir1.2-ayatanaappindicator3-0.1),
not the service venv, and as the desktop user, not root.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

STATUS_PATH = Path(os.environ.get("B2U_STATUS_FILE", "/run/bluetooth_2_usb/status.json"))
POLL_INTERVAL_MS = 1000
ICON_RESCAN_GRACE_SEC = 6
APP_ID = "bluetooth_2_usb-tray"

GREEN = "#2e9d4b"
RED = "#d64541"
GREY = "#8a8a8a"
BLUE = "#3584e4"
ORANGE = "#e5a50a"


@dataclass(frozen=True, slots=True)
class TrayState:
    online: bool
    jiggler: str = "unavailable"  # "on" | "off" | "unavailable"
    relay: str = "no_host"  # "host" | "paused" | "no_host"

    @property
    def icon_name(self) -> str:
        if not self.online:
            return "b2u-offline"
        return f"b2u-jiggler-{self.jiggler}-relay-{self.relay}"


def read_state(path: Path = STATUS_PATH) -> TrayState:
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        pid = int(status["pid"])
        relay = status["relay"]
        jiggler = status["jiggler"]
    except (OSError, ValueError, KeyError, TypeError):
        return TrayState(online=False)
    # Guards against a stale file left behind by a hard kill.
    if not Path(f"/proc/{pid}").exists():
        return TrayState(online=False)

    if not jiggler.get("available"):
        jiggler_state = "unavailable"
    else:
        jiggler_state = "on" if jiggler.get("enabled") else "off"

    if relay.get("active"):
        relay_state = "host"
    elif relay.get("host_configured") and not relay.get("user_enabled"):
        relay_state = "paused"
    else:
        relay_state = "no_host"
    return TrayState(online=True, jiggler=jiggler_state, relay=relay_state)


def describe(state: TrayState) -> tuple[str, str]:
    if not state.online:
        return "Jiggler: unknown", "bluetooth_2_usb is not running"
    jiggler_text = {"on": "Jiggler: ON", "off": "Jiggler: OFF", "unavailable": "Jiggler: not configured"}[state.jiggler]
    relay_text = {
        "host": "Input: forwarded to USB host",
        "paused": "Input: stays on this Pi (relay paused)",
        "no_host": "Input: USB host not available",
    }[state.relay]
    return jiggler_text, relay_text


def render_icon(state: TrayState) -> str:
    """SVG icon: a mouse colored by jiggler state, with a badge for the relay state."""
    if not state.online:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">'
            f'<rect x="6" y="2" width="12" height="19" rx="6" fill="none" stroke="{GREY}" '
            'stroke-width="2" stroke-dasharray="3 2"/>'
            "</svg>"
        )

    body = {"on": GREEN, "off": RED, "unavailable": GREY}[state.jiggler]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">',
        f'<rect x="4" y="1" width="12" height="19" rx="6" fill="{body}"/>',
        '<line x1="10" y1="4" x2="10" y2="8" stroke="#ffffff" stroke-width="2" stroke-linecap="round"/>',
    ]
    if state.jiggler == "off":
        # Not just color: the slash keeps "off" readable for color-blind users.
        parts.append('<line x1="3" y1="19" x2="17" y2="2" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round"/>')

    if state.relay == "host":
        parts += [
            f'<circle cx="18" cy="18" r="5.5" fill="{BLUE}" stroke="#ffffff" stroke-width="1"/>',
            '<path d="M15 18h5.5M18 15.5l2.5 2.5-2.5 2.5" fill="none" stroke="#ffffff" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
        ]
    elif state.relay == "paused":
        parts += [
            f'<circle cx="18" cy="18" r="5.5" fill="{ORANGE}" stroke="#ffffff" stroke-width="1"/>',
            '<path d="M16.5 15.5v5M19.5 15.5v5" stroke="#ffffff" stroke-width="1.8" stroke-linecap="round"/>',
        ]
    else:
        parts.append(f'<circle cx="18" cy="18" r="4.5" fill="#ffffff" stroke="{GREY}" stroke-width="2"/>')
    parts.append("</svg>")
    return "".join(parts)


def all_states() -> list[TrayState]:
    states = [TrayState(online=False)]
    for jiggler in ("on", "off", "unavailable"):
        for relay in ("host", "paused", "no_host"):
            states.append(TrayState(online=True, jiggler=jiggler, relay=relay))
    return states


def install_icons() -> bool:
    """
    Write every icon variant into the user's hicolor theme.

    wf-panel-pi resolves tray icons by theme name only and ignores the
    item's IconThemePath, so a private icon directory is not enough.

    :return: True if any icon was (re)written
    """
    icons_root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "icons"
    icon_dir = icons_root / "hicolor/scalable/apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    changed = False
    for state in all_states():
        icon_path = icon_dir / f"{state.icon_name}.svg"
        svg = render_icon(state)
        if not icon_path.exists() or icon_path.read_text(encoding="utf-8") != svg:
            icon_path.write_text(svg, encoding="utf-8")
            changed = True
    if changed:
        # GTK 3 only notices new icons when the icon root's mtime changes,
        # not the subdirectory's, so the panel would otherwise keep a stale view.
        os.utime(icons_root)
    return changed


class Tray:
    def __init__(self) -> None:
        self._state: TrayState | None = None
        self._jiggler_item = Gtk.MenuItem(label="")
        self._relay_item = Gtk.MenuItem(label="")
        self._jiggler_item.set_sensitive(False)
        self._relay_item.set_sensitive(False)
        quit_item = Gtk.MenuItem(label="Quit indicator")
        quit_item.connect("activate", lambda *_: Gtk.main_quit())

        menu = Gtk.Menu()
        for item in (self._jiggler_item, self._relay_item, Gtk.SeparatorMenuItem(), quit_item):
            menu.append(item)
        menu.show_all()

        self._indicator = AppIndicator.Indicator.new(
            APP_ID, TrayState(online=False).icon_name, AppIndicator.IndicatorCategory.HARDWARE
        )
        self._indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self._indicator.set_menu(menu)

        self._refresh()
        GLib.timeout_add(POLL_INTERVAL_MS, self._refresh)

    def _refresh(self) -> bool:
        state = read_state()
        if state != self._state:
            self._state = state
            jiggler_text, relay_text = describe(state)
            self._indicator.set_icon_full(state.icon_name, f"{jiggler_text}, {relay_text}")
            self._indicator.set_title(f"bluetooth_2_usb: {jiggler_text}, {relay_text}")
            self._jiggler_item.set_label(jiggler_text)
            self._relay_item.set_label(relay_text)
        return GLib.SOURCE_CONTINUE


def main() -> int:
    if install_icons():
        # GTK rescans icon themes at most every 5 s; give the panel time to see
        # fresh icons before the first lookup so the item doesn't start blank.
        time.sleep(ICON_RESCAN_GRACE_SEC)
    Tray()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
