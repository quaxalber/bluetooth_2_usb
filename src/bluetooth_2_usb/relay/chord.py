from __future__ import annotations

from collections.abc import Callable

from ..evdev import find_key_name
from ..evdev.types import KeyEvent


class ChordToggler:
    """
    Tracks a set of keys and detects a complete press-then-release cycle of
    all of them, invoking a callback exactly once per cycle.

    Only the key that completes the chord (the trigger key) is suppressed on
    its way up. The other chord keys were already forwarded to the host when
    pressed, so their releases are forwarded too, instead of being swallowed
    and leaving a stuck modifier on the host. The callback fires once every
    chord key has been released (not on the completing key-down), so a caller
    only sees one transition per full press+release cycle of every key.
    """

    def __init__(self, chord_keys: set[str], on_trigger: Callable[[], None]) -> None:
        """
        :param chord_keys: Set of evdev-style key names that make up the chord
        :param on_trigger: Called once every chord key has been released after
            the chord was completed
        """
        self._chord_keys = chord_keys
        self._on_trigger = on_trigger

        self._currently_pressed: set[str] = set()
        self._pending_release: set[str] = set()
        self._trigger_key: str | None = None
        self._armed = True

    def handle_key_event(self, event: KeyEvent) -> bool:
        """
        Process a key press or release to detect the chord.

        :param event: The incoming KeyEvent from evdev
        :return: True if the event was consumed and should not be forwarded
        """
        key_name = find_key_name(event)
        if key_name is None:
            return False

        if event.keystate == KeyEvent.key_down:
            self._currently_pressed.add(key_name)
            if self._armed and self._chord_keys and self._chord_keys.issubset(self._currently_pressed):
                self._armed = False
                self._trigger_key = key_name
                self._pending_release = set(self._chord_keys)
            return key_name == self._trigger_key

        if event.keystate == KeyEvent.key_up:
            self._currently_pressed.discard(key_name)
            is_trigger = key_name == self._trigger_key
            if key_name in self._pending_release:
                self._pending_release.discard(key_name)
                if not self._pending_release:
                    self._armed = True
                    self._trigger_key = None
                    self._on_trigger()
            return is_trigger

        return False
