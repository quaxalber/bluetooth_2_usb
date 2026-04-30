from __future__ import annotations

import asyncio

from .evdev import find_key_name
from .evdev_types import KeyEvent
from .hid_gadgets import HidGadgets
from .logging import get_logger

logger = get_logger(__name__)


class ShortcutToggler:
    """
    Tracks a user-defined shortcut and toggles relaying on/off when the shortcut is pressed.
    """

    def __init__(self, shortcut_keys: set[str], relaying_active: asyncio.Event, hid_gadgets: HidGadgets) -> None:
        """
        :param shortcut_keys: A set of evdev-style key names to detect
        :param relaying_active: An asyncio.Event controlling whether relaying is active
        :param hid_gadgets: HidGadgets to release keyboard/mouse states on toggle
        """
        self._shortcut_keys = shortcut_keys
        self._relaying_active = relaying_active
        self._hid_gadgets = hid_gadgets

        self._currently_pressed: set[str] = set()
        self._suppressed_keys: set[str] = set()
        self._shortcut_armed = True

    def handle_key_event(self, event: KeyEvent) -> bool:
        """
        Process a key press or release to detect the toggle shortcut.

        :param event: The incoming KeyEvent from evdev
        :type event: KeyEvent
        """
        key_name = find_key_name(event)
        if key_name is None:
            return False

        if event.keystate == KeyEvent.key_down:
            self._currently_pressed.add(key_name)
        elif event.keystate == KeyEvent.key_up:
            self._currently_pressed.discard(key_name)
            if key_name in self._suppressed_keys:
                self._suppressed_keys.discard(key_name)
                if not self._suppressed_keys:
                    self._shortcut_armed = True
                return True
            if self._shortcut_keys and key_name in self._shortcut_keys:
                self._shortcut_armed = True

        if self._shortcut_armed and self._shortcut_keys and self._shortcut_keys.issubset(self._currently_pressed):
            self._shortcut_armed = False
            self._suppressed_keys.update(self._shortcut_keys)
            self.toggle_relaying()
            return True

        return key_name in self._suppressed_keys

    def toggle_relaying(self) -> None:
        """
        Toggle the global relaying state: if it was on, turn it off, otherwise turn it on.
        """
        if self._relaying_active.is_set():
            self._hid_gadgets.release_all()
            self._relaying_active.clear()
            logger.info("ShortcutToggler: Relaying is now OFF.")
        else:
            self._relaying_active.set()
            logger.info("ShortcutToggler: Relaying is now ON.")
