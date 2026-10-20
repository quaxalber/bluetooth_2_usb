from __future__ import annotations

from ..evdev.types import KeyEvent
from ..logging import get_logger
from .chord import ChordToggler
from .gate import RelayGate

logger = get_logger(__name__)


class ShortcutToggler:
    """
    Tracks a user-defined shortcut and toggles relaying on/off when the shortcut is pressed.
    """

    def __init__(self, shortcut_keys: set[str], relay_gate: RelayGate) -> None:
        """
        :param shortcut_keys: A set of evdev-style key names to detect
        :param relay_gate: RelayGate controlling whether relaying is active
        """
        self._relay_gate = relay_gate
        self._chord = ChordToggler(shortcut_keys, on_trigger=self.toggle_relaying)

    def handle_key_event(self, event: KeyEvent) -> bool:
        """
        Process a key press or release to detect the toggle shortcut.

        Only the trigger key (the one whose key-down completes the shortcut)
        is suppressed. The other shortcut keys were already forwarded to the
        host when pressed, so their key-ups are forwarded too, instead of
        being swallowed and leaving a stuck modifier on the host. The toggle
        itself still waits until every shortcut key has been released (not
        the initial key-down), so the device grab state only changes once
        the local terminal has seen a complete press+release cycle for every
        modifier.

        :param event: The incoming KeyEvent from evdev
        :type event: KeyEvent
        """
        return self._chord.handle_key_event(event)

    def toggle_relaying(self) -> None:
        """
        Toggle the global relaying state: if it was on, turn it off, otherwise turn it on.
        """
        if self._relay_gate.toggle_user_enabled():
            logger.info("User pause is now disabled.")
        else:
            logger.info("User pause is now enabled.")
