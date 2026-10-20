from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from ..evdev import ecodes, evdev_to_usb_hid, is_consumer_key, is_mouse_button
from ..evdev.types import InputEvent, KeyEvent, RelEvent, categorize
from ..logging import get_logger
from ..relay.gate import RelayGate
from ..relay.jiggler import JigglerToggler, MouseJiggler
from ..relay.shortcut import ShortcutToggler
from .mouse_delta import MouseDelta, MouseDeltaAccumulator

logger = get_logger(__name__)

if TYPE_CHECKING:
    from ..gadgets.manager import HidGadgets


class HidDispatcher:
    """
    Converts raw evdev events into HID gadget writes.

    This owns HID-domain details: event categorization, shortcut suppression,
    key routing, mouse frame coalescing, and write-failure suspension.
    """

    def __init__(
        self,
        hid_gadgets: HidGadgets,
        relay_gate: RelayGate,
        shortcut_toggler: ShortcutToggler | None = None,
        jiggler_toggler: JigglerToggler | None = None,
        mouse_jiggler: MouseJiggler | None = None,
    ) -> None:
        self._hid_gadgets = hid_gadgets
        self._relay_gate = relay_gate
        self._shortcut_toggler = shortcut_toggler
        self._jiggler_toggler = jiggler_toggler
        self._mouse_jiggler = mouse_jiggler
        self._mouse_delta = MouseDeltaAccumulator()
        self._hid_write_failures = 0

    @property
    def write_failures(self) -> int:
        return self._hid_write_failures

    async def dispatch(self, raw_event: InputEvent) -> None:
        event = categorize(raw_event)

        # A shortcut key event can itself flip relay_gate (pause/resume) as a
        # side effect of handle_key_event(). Snapshot the state from before
        # that flip: a non-suppressed modifier release that completes the
        # shortcut happened while the old state was still in effect, and must
        # be forwarded (or dropped) accordingly, not based on the state it
        # just caused.
        relay_was_active = self._relay_gate.active

        if self._shortcut_toggler and isinstance(event, KeyEvent):
            if self._shortcut_toggler.handle_key_event(event):
                return

        if self._jiggler_toggler and isinstance(event, KeyEvent):
            if self._jiggler_toggler.handle_key_event(event):
                return

        if not relay_was_active:
            self.discard_pending()
            return

        if isinstance(event, RelEvent):
            self._mouse_delta.add_event(event)
            return

        if getattr(event, "type", None) == ecodes.EV_SYN and getattr(event, "code", None) == ecodes.SYN_REPORT:
            await self.flush()
            return

        # Preserve cross-gadget event order if another event arrives before SYN_REPORT.
        await self.flush()
        if isinstance(event, KeyEvent):
            await self._process_key_event(event)

    def discard_pending(self) -> None:
        self._mouse_delta.discard()

    async def flush(self) -> None:
        if not self._relay_gate.active:
            self.discard_pending()
            return
        coalesced_events = self._mouse_delta.pending_event_count
        delta = self._mouse_delta.flush()
        if coalesced_events:
            logger.debug(
                "Flushing mouse delta: coalesced_events=%s x=%s y=%s wheel=%s pan=%s emitted=%s",
                coalesced_events,
                delta.x if delta is not None else 0,
                delta.y if delta is not None else 0,
                delta.wheel if delta is not None else 0,
                delta.pan if delta is not None else 0,
                delta is not None,
            )
        if delta is None:
            return
        await self._process_mouse_delta(delta)

    async def _process_mouse_delta(self, delta: MouseDelta) -> None:
        mouse = self._hid_gadgets.mouse
        if mouse is None:
            raise RuntimeError("Mouse gadget is not available; HID gadgets are not enabled.")
        if not self._relay_gate.active:
            return
        await self._write_hid_report(mouse.move, "Mouse movement", delta, *delta)

    async def _process_key_event(self, event: KeyEvent) -> None:
        # Callers already gate on the relay-active snapshot taken before this
        # event ran through the togglers; re-checking the (possibly now
        # stale) live gate state here would drop the very key-up that a
        # shortcut's own completion is supposed to still forward.
        await self._write_hid_report(self._dispatch_key_event, "Key event", event, event)

    async def _write_hid_report(
        self, operation: Callable[..., Awaitable[None]], description: str, context: object, *args: object
    ) -> None:
        try:
            await operation(*args)
            if self._mouse_jiggler:
                self._mouse_jiggler.reset_timer()
        except BlockingIOError:
            self._hid_write_failures += 1
            logger.debug("%s HID write blocked; dropping %s", description, context)
        except BrokenPipeError:
            self._handle_broken_pipe()
        except Exception:
            self._hid_write_failures += 1
            logger.exception("Unexpected error processing %s", context)
            raise

    async def _dispatch_key_event(self, event: KeyEvent) -> None:
        key_id, key_name = evdev_to_usb_hid(event)
        if key_id is None or key_name is None:
            return

        if is_consumer_key(event):
            output_gadget = self._hid_gadgets.consumer
        elif is_mouse_button(event):
            output_gadget = self._hid_gadgets.mouse
        else:
            output_gadget = self._hid_gadgets.keyboard
        if output_gadget is None:
            raise RuntimeError("No appropriate USB HID gadget is available.")

        if event.keystate == KeyEvent.key_down:
            logger.debug("Pressing %s (0x%02X) via %s", key_name, key_id, output_gadget)
            await output_gadget.press(key_id)
        elif event.keystate == KeyEvent.key_up:
            logger.debug("Releasing %s (0x%02X) via %s", key_name, key_id, output_gadget)
            if is_consumer_key(event):
                await output_gadget.release()
            else:
                await output_gadget.release(key_id)

    def _handle_broken_pipe(self) -> None:
        self._hid_write_failures += 1
        logger.warning(
            "BrokenPipeError: USB cable likely disconnected or power-only. "
            + "Pausing relay until the host reports a fresh configured USB state.\nSee: "
            + "https://github.com/quaxalber/bluetooth_2_usb/blob/main/TROUBLESHOOTING.md"
        )
        self._relay_gate.suspend_writes()
