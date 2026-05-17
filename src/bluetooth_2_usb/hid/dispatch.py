from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from ..evdev import (
    InputEvent,
    KeyEvent,
    RelEvent,
    categorize,
    ecodes,
    evdev_to_usb_hid,
    event_code,
    event_scancode,
    event_type,
    is_consumer_key,
    is_mouse_button,
)
from ..inputs.profile import DEFAULT_PROFILE, InputDeviceKind, InputDeviceProfile
from ..logging import get_logger
from ..relay.gate import RelayGate
from ..relay.shortcut import ShortcutToggler
from .absolute import TABLET_PAD_BUTTONS, PadAccumulator, PenAccumulator, TouchAccumulator
from .mouse_delta import MouseAccumulator, MouseDelta

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
        source_profile: InputDeviceProfile = DEFAULT_PROFILE,
    ) -> None:
        self._hid_gadgets = hid_gadgets
        self._relay_gate = relay_gate
        self._shortcut_toggler = shortcut_toggler
        self._source_profile = source_profile
        self._mouse = MouseAccumulator()
        self._touch = (
            TouchAccumulator(source_profile)
            if source_profile.kind in (InputDeviceKind.TOUCHPAD, InputDeviceKind.TABLET_TOUCH)
            else None
        )
        self._pen = PenAccumulator(source_profile) if source_profile.kind is InputDeviceKind.TABLET_PEN else None
        self._pad = PadAccumulator() if source_profile.kind is InputDeviceKind.TABLET_PAD else None
        self._hid_write_failures = 0

    @property
    def write_failures(self) -> int:
        return self._hid_write_failures

    async def dispatch(self, raw_event: InputEvent) -> None:
        event = categorize(raw_event)

        if self._shortcut_toggler and isinstance(event, KeyEvent):
            if self._shortcut_toggler.handle_key_event(event):
                return

        if not self._relay_gate.active:
            self.discard_pending()
            return

        if isinstance(event, RelEvent):
            self._mouse.add_event(event)
            return

        if event_type(event) == ecodes.EV_SYN and event_code(event) == ecodes.SYN_REPORT:
            await self.flush()
            return

        if self._process_absolute_event(event):
            return

        if isinstance(event, KeyEvent) and self._process_digitizer_key_event(event):
            return

        # Preserve cross-gadget event order if another event arrives before SYN_REPORT.
        await self.flush()
        if isinstance(event, KeyEvent):
            await self._process_key_event(event)

    def discard_pending(self) -> None:
        for accumulator in (self._mouse, self._touch, self._pen, self._pad):
            if accumulator is not None:
                accumulator.discard()

    async def flush(self) -> None:
        if not self._relay_gate.active:
            self.discard_pending()
            return
        coalesced_events = self._mouse.pending_event_count
        delta = self._mouse.flush()
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
            await self._flush_digitizers()
            return
        await self._process_mouse(delta)
        await self._flush_digitizers()

    def _process_absolute_event(self, event: object) -> bool:
        resolved_event_type = event_type(event)
        resolved_event_code = event_code(event)
        if resolved_event_type == ecodes.EV_ABS:
            if self._touch is not None:
                self._touch.add_event(event)
                return True
            if self._pen is not None:
                self._pen.add_event(event)
                return True
            if self._pad is not None:
                self._pad.add_event(event)
                return True
        if resolved_event_type == ecodes.EV_MSC and resolved_event_code == ecodes.MSC_SERIAL and self._pen is not None:
            self._pen.add_misc(event)
            return True
        return False

    def _process_digitizer_key_event(self, event: KeyEvent) -> bool:
        if self._touch is not None:
            self._touch.add_key(event)
            return event_scancode(event) in {
                ecodes.BTN_LEFT,
                ecodes.BTN_TOUCH,
                ecodes.BTN_TOOL_FINGER,
                ecodes.BTN_TOOL_DOUBLETAP,
                ecodes.BTN_TOOL_TRIPLETAP,
                ecodes.BTN_TOOL_QUADTAP,
                ecodes.BTN_TOOL_QUINTTAP,
            }
        if self._pen is not None:
            self._pen.add_key(event)
            return event_scancode(event) in {
                ecodes.BTN_DIGI,
                ecodes.BTN_TOOL_PEN,
                ecodes.BTN_TOOL_RUBBER,
                ecodes.BTN_TOUCH,
                ecodes.BTN_STYLUS,
                ecodes.BTN_STYLUS2,
            }
        if self._pad is not None:
            self._pad.add_key(event)
            return event_scancode(event) in TABLET_PAD_BUTTONS
        return False

    async def release_active_digitizers(self) -> None:
        if self._touch is not None and (touch_report := self._touch.release_all()) is not None:
            touch = self._hid_gadgets.touch
            if touch is None:
                raise RuntimeError("Touch digitizer gadget is not available; HID gadgets are not enabled.")
            await self._write_hid_report(touch.send, "Touch digitizer release", touch_report, touch_report)
        if self._pen is not None and (pen_report := self._pen.release_all()) is not None:
            tablet = self._hid_gadgets.tablet
            if tablet is None:
                raise RuntimeError("Tablet digitizer gadget is not available; HID gadgets are not enabled.")
            await self._write_hid_report(tablet.send_pen, "Tablet pen release", pen_report, pen_report)
        if self._pad is not None and (pad_report := self._pad.release_all()) is not None:
            tablet = self._hid_gadgets.tablet
            if tablet is None:
                raise RuntimeError("Tablet digitizer gadget is not available; HID gadgets are not enabled.")
            await self._write_hid_report(tablet.send_pad, "Tablet pad release", pad_report, pad_report)

    async def _flush_digitizers(self) -> None:
        if self._touch is not None and (touch_report := self._touch.flush()) is not None:
            touch = self._hid_gadgets.touch
            if touch is None:
                raise RuntimeError("Touch digitizer gadget is not available; HID gadgets are not enabled.")
            await self._write_hid_report(touch.send, "Touch digitizer", touch_report, touch_report)
        if self._pen is not None and (pen_report := self._pen.flush()) is not None:
            tablet = self._hid_gadgets.tablet
            if tablet is None:
                raise RuntimeError("Tablet digitizer gadget is not available; HID gadgets are not enabled.")
            await self._write_hid_report(tablet.send_pen, "Tablet pen", pen_report, pen_report)
        if self._pad is not None and (pad_report := self._pad.flush()) is not None:
            tablet = self._hid_gadgets.tablet
            if tablet is None:
                raise RuntimeError("Tablet digitizer gadget is not available; HID gadgets are not enabled.")
            await self._write_hid_report(tablet.send_pad, "Tablet pad", pad_report, pad_report)

    async def _process_mouse(self, delta: MouseDelta) -> None:
        mouse = self._hid_gadgets.mouse
        if mouse is None:
            raise RuntimeError("Mouse gadget is not available; HID gadgets are not enabled.")
        if not self._relay_gate.active:
            return
        await self._write_hid_report(mouse.move, "Mouse movement", delta, *delta)

    async def _process_key_event(self, event: KeyEvent) -> None:
        if not self._relay_gate.active:
            return
        await self._write_hid_report(self._dispatch_key_event, "Key event", event, event)

    async def _write_hid_report(
        self, operation: Callable[..., Awaitable[None]], description: str, context: object, *args: object
    ) -> None:
        try:
            await operation(*args)
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
