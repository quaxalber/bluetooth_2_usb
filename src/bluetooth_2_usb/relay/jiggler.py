from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..evdev.types import KeyEvent
from ..logging import get_logger
from .chord import ChordToggler
from .gate import RelayGate

if TYPE_CHECKING:
    from ..gadgets.manager import HidGadgets

logger = get_logger(__name__)


class MouseJiggler:
    """
    Periodically moves the mouse by a small amount to prevent screen timeout.

    Fires when the USB host is configured and writes are not suspended,
    regardless of the user pause state. Reset whenever any input event is
    successfully relayed to USB.

    Each jiggle moves 2 pixels in one of 8 directions (cardinal or diagonal),
    always ensuring at least one axis moves. The cursor performs a random walk
    over time, but the random distribution keeps it statistically near the
    starting position.
    """

    _HOST_CHECK_INTERVAL = 5.0

    def __init__(
        self,
        hid_gadgets: HidGadgets,
        relay_gate: RelayGate,
        base_interval: float = 120.0,
        jitter: float = 15.0,
    ) -> None:
        """
        :param hid_gadgets: Provides access to the mouse gadget
        :param relay_gate: Provides host connection and write-suspension state
        :param base_interval: Base seconds between jiggles (default: 120)
        :param jitter: Random ± seconds added to base_interval (default: 15)
        """
        self._hid_gadgets = hid_gadgets
        self._relay_gate = relay_gate
        self._base_interval = base_interval
        self._jitter = jitter

        self._enabled = True
        self._next_jiggle_time = time.monotonic() + self._sample_interval()
        self._listeners: list[Callable[[bool], None]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def add_listener(self, listener: Callable[[bool], None]) -> None:
        """Register a callback invoked with the new enabled state whenever toggle() runs."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[bool], None]) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def toggle(self) -> bool:
        """Toggle enabled state. Returns the new enabled state."""
        self._enabled = not self._enabled
        if self._enabled:
            # Ensure re-enable doesn't fire immediately if the timer already expired
            self.reset_timer()
        for listener in list(self._listeners):
            listener(self._enabled)
        return self._enabled

    def reset_timer(self) -> None:
        """
        Push the next jiggle forward on user activity. Only extends the timer,
        never shortens it.
        """
        earliest_next = time.monotonic() + self._base_interval
        if self._next_jiggle_time < earliest_next:
            self._next_jiggle_time = earliest_next

    def _sample_interval(self) -> float:
        return self._base_interval + random.uniform(-self._jitter, self._jitter)

    async def run(self) -> None:
        """
        Background coroutine: polls every second and jiggles the mouse when due.
        Designed to run as an asyncio Task; exits cleanly on CancelledError.
        """
        logger.debug(
            "MouseJiggler: Started (base_interval=%.0fs, jitter=±%.0fs)",
            self._base_interval,
            self._jitter,
        )
        while True:
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                logger.debug("MouseJiggler: Stopped.")
                break

            now = time.monotonic()
            if now < self._next_jiggle_time:
                continue

            state = self._relay_gate.state
            if self._enabled and state.host_configured and not state.write_suspended:
                await self._perform_jiggle()
                interval = self._sample_interval()
                self._next_jiggle_time = now + interval
                logger.debug("MouseJiggler: Next jiggle in %.1fs", interval)
            elif not self._enabled:
                logger.debug("MouseJiggler: Skipping jiggle (disabled by user)")
                interval = self._sample_interval()
                self._next_jiggle_time = now + interval
            else:
                # Host disconnected or writes suspended; check again soon so the
                # first jiggle after reconnect isn't delayed by a full interval.
                logger.debug("MouseJiggler: Skipping jiggle (host not ready)")
                self._next_jiggle_time = now + self._HOST_CHECK_INTERVAL

    async def _perform_jiggle(self) -> None:
        """
        Move the cursor 2 pixels in a random direction (one of 8 cardinal or diagonal
        directions), always ensuring at least one axis moves.
        """
        mouse = self._hid_gadgets.mouse
        if mouse is None:
            logger.warning("MouseJiggler: Mouse gadget not available; skipping jiggle")
            return
        try:
            x = random.choice([-2, 0, 2])
            y = random.choice([-2, 0, 2])
            if x == 0 and y == 0:
                x = random.choice([-2, 2])
            await mouse.move(x=x, y=y)
            logger.debug("MouseJiggler: Jiggled mouse (x=%+d, y=%+d)", x, y)
        except BlockingIOError as exc:
            # Transient (e.g. gadget report queue momentarily full); already retried
            # internally by the gadget write path. Drop this jiggle, don't suspend.
            logger.debug("MouseJiggler: Write blocked; dropping this jiggle (%s)", exc)
        except BrokenPipeError as exc:
            # Suspend writes so the relay gate gates all HID output until reconnect.
            logger.warning("MouseJiggler: Write error (%s); suspending writes", exc)
            self._relay_gate.suspend_writes()
        except Exception as exc:
            logger.warning("MouseJiggler: Failed to jiggle mouse: %s", exc)


class JigglerToggler:
    """
    Tracks a user-defined shortcut and toggles the mouse jiggler on/off.

    Only the key that completes the shortcut (the trigger key) is suppressed on
    its way up. All other shortcut keys that were pressed first are forwarded
    normally, so the USB host never sees a stuck modifier.
    """

    def __init__(self, shortcut_keys: set[str], mouse_jiggler: MouseJiggler) -> None:
        """
        :param shortcut_keys: Set of evdev-style key names (e.g. {"KEY_LEFTCTRL", "KEY_F11"})
        :param mouse_jiggler: The MouseJiggler instance to toggle
        """
        self._mouse_jiggler = mouse_jiggler
        self._chord = ChordToggler(shortcut_keys, on_trigger=self._toggle_jiggler)

    def handle_key_event(self, event: KeyEvent) -> bool:
        """
        Process a key event to detect the jiggler toggle shortcut.

        :return: True if the event was consumed and should not be forwarded
        """
        return self._chord.handle_key_event(event)

    def _toggle_jiggler(self) -> None:
        enabled = self._mouse_jiggler.toggle()
        logger.info("JigglerToggler: Mouse jiggler is now %s.", "ON" if enabled else "OFF")
