from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .evdev import ecodes, evdev_to_usb_hid, get_mouse_movement, is_consumer_key, is_mouse_button
from .evdev_types import InputEvent, KeyEvent, RelEvent, categorize
from .extended_mouse import ExtendedMouse
from .hid_gadgets import HidGadgets
from .logging import get_logger
from .mouse_delta import MouseDelta, MouseDeltaAccumulator, iter_mouse_delta_chunks
from .relay_gate import RelayGate
from .shortcut_toggler import ShortcutToggler

if TYPE_CHECKING:
    from adafruit_hid.consumer_control import ConsumerControl
    from adafruit_hid.keyboard import Keyboard

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class HidDispatchStats:
    write_retries: int
    write_failures: int


class HidDispatcher:
    """
    Converts raw evdev events into HID gadget writes.

    This owns HID-domain details: event categorization, shortcut suppression,
    key routing, mouse frame coalescing, large mouse delta chunking, transient
    key write retry, and write-failure suspension.
    """

    HID_WRITE_MAX_TRIES = 20
    HID_WRITE_RETRY_DELAY_SEC = 0.01

    def __init__(
        self,
        hid_gadgets: HidGadgets,
        relay_gate: RelayGate,
        shortcut_toggler: ShortcutToggler | None = None,
    ) -> None:
        self._hid_gadgets = hid_gadgets
        self._relay_gate = relay_gate
        self._shortcut_toggler = shortcut_toggler
        self._mouse_delta = MouseDeltaAccumulator()
        self._hid_write_retries = 0
        self._hid_write_failures = 0

    @property
    def stats(self) -> HidDispatchStats:
        return HidDispatchStats(
            write_retries=self._hid_write_retries,
            write_failures=self._hid_write_failures,
        )

    async def dispatch(self, raw_event: InputEvent) -> None:
        event = categorize(raw_event)

        if self._shortcut_toggler and isinstance(event, KeyEvent):
            if self._shortcut_toggler.handle_key_event(event):
                return

        if not self._relay_gate.active:
            self.discard_pending()
            return

        if isinstance(event, RelEvent):
            self._accumulate_mouse_movement(event)
            return

        if self._is_syn_report(event):
            self.flush()
            return

        # Preserve cross-gadget event order if another event arrives before SYN_REPORT.
        self.flush()
        if isinstance(event, KeyEvent):
            await self._process_key_event_with_retry(event)

    @staticmethod
    def _is_syn_report(event: InputEvent) -> bool:
        return (
            getattr(event, "type", None) == ecodes.EV_SYN
            and getattr(event, "code", None) == ecodes.SYN_REPORT
        )

    def discard_pending(self) -> None:
        self._mouse_delta.discard()

    def flush(self) -> None:
        if not self._relay_gate.active:
            self.discard_pending()
            return
        delta = self._mouse_delta.flush()
        if delta is None:
            return
        self._process_mouse_delta(delta)

    def _accumulate_mouse_movement(self, event: RelEvent) -> None:
        x, y, wheel, pan = get_mouse_movement(event)
        logger.debug(
            "Mouse REL input: code=%s value=%s -> x=%s y=%s wheel=%s pan=%s",
            event.event.code,
            event.event.value,
            x,
            y,
            wheel,
            pan,
        )
        self._mouse_delta.add_event(event)

    def _process_mouse_delta(self, delta: MouseDelta) -> None:
        mouse = self._hid_gadgets.mouse
        if mouse is None:
            raise RuntimeError("Mouse gadget is not available; HID gadgets are not enabled.")
        for partial in iter_mouse_delta_chunks(delta):
            if not self._relay_gate.active:
                return
            try:
                mouse.move(*partial)
            except BlockingIOError:
                self._hid_write_failures += 1
                logger.debug("Mouse movement HID write blocked; dropping chunk %s", partial)
                continue
            except BrokenPipeError:
                self._handle_broken_pipe()
                return
            except Exception:
                self._hid_write_failures += 1
                logger.exception("Unexpected error processing mouse movement")
                raise

    async def _process_key_event_with_retry(self, event: KeyEvent) -> None:
        max_tries = self.HID_WRITE_MAX_TRIES
        retry_delay = self.HID_WRITE_RETRY_DELAY_SEC
        for attempt in range(1, max_tries + 1):
            if not self._relay_gate.active:
                return
            try:
                self._dispatch_key_event(event)
                return
            except BlockingIOError:
                if not self._relay_gate.active:
                    return
                if attempt < max_tries:
                    self._hid_write_retries += 1
                    logger.debug("HID write blocked (%s/%s)", attempt, max_tries)
                    await asyncio.sleep(retry_delay)
                else:
                    self._hid_write_failures += 1
                    logger.warning("HID write blocked (%s/%s)", attempt, max_tries)
                    return
            except BrokenPipeError:
                self._handle_broken_pipe()
                return
            except Exception:
                self._hid_write_failures += 1
                logger.exception("Unexpected error processing %s", event)
                raise

    def _dispatch_key_event(self, event: KeyEvent) -> None:
        key_id, key_name = evdev_to_usb_hid(event)
        if key_id is None or key_name is None:
            return

        output_gadget = self._select_gadget(event)
        if output_gadget is None:
            raise RuntimeError("No appropriate USB HID gadget is available.")

        if event.keystate == KeyEvent.key_down:
            logger.debug("Pressing %s (0x%02X) via %s", key_name, key_id, output_gadget)
            output_gadget.press(key_id)
        elif event.keystate == KeyEvent.key_up:
            logger.debug("Releasing %s (0x%02X) via %s", key_name, key_id, output_gadget)
            if is_consumer_key(event):
                output_gadget.release()
            else:
                output_gadget.release(key_id)

    def _select_gadget(self, event: KeyEvent) -> ConsumerControl | Keyboard | ExtendedMouse | None:
        if is_consumer_key(event):
            return self._hid_gadgets.consumer
        if is_mouse_button(event):
            return self._hid_gadgets.mouse
        return self._hid_gadgets.keyboard

    def _handle_broken_pipe(self) -> None:
        self._hid_write_failures += 1
        logger.warning(
            "BrokenPipeError: USB cable likely disconnected or power-only. "
            + "Pausing relay.\nSee: "
            + "https://github.com/quaxalber/bluetooth_2_usb/blob/main/TROUBLESHOOTING.md"
        )
        self._relay_gate.suspend_writes()
