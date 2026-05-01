from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .evdev import ecodes, evdev_to_usb_hid, get_mouse_movement, is_consumer_key, is_mouse_button
from .evdev_types import InputEvent, KeyEvent, RelEvent
from .extended_mouse import ExtendedMouse
from .hid_gadgets import HidGadgets
from .logging import get_logger
from .mouse_delta import MouseDelta, MouseDeltaAccumulator, iter_mouse_delta_chunks
from .relay_gate import RelayGate

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
    Converts categorized evdev events into HID gadget writes.

    This owns HID-domain details: key routing, mouse frame coalescing, large
    mouse delta chunking, transient write retry, and write-failure suspension.
    """

    HID_WRITE_MAX_TRIES = 20
    HID_WRITE_RETRY_DELAY_SEC = 0.01

    def __init__(self, hid_gadgets: HidGadgets, relay_gate: RelayGate) -> None:
        self._hid_gadgets = hid_gadgets
        self._relay_gate = relay_gate
        self._mouse_delta = MouseDeltaAccumulator()
        self._hid_write_retries = 0
        self._hid_write_failures = 0

    @property
    def stats(self) -> HidDispatchStats:
        return HidDispatchStats(
            write_retries=self._hid_write_retries,
            write_failures=self._hid_write_failures,
        )

    async def dispatch(self, event: InputEvent, raw_event: InputEvent) -> None:
        if not self._relay_gate.active:
            self.discard_pending()
            return

        is_syn_report = (
            getattr(raw_event, "type", None) == ecodes.EV_SYN
            and getattr(raw_event, "code", None) == ecodes.SYN_REPORT
        )

        if isinstance(event, RelEvent):
            self._accumulate_mouse_movement(event)
            return

        if is_syn_report:
            await self.flush()
            return

        # Preserve cross-gadget event order if another event arrives before SYN_REPORT.
        await self.flush()
        await self._process_event_with_retry(event)

    def discard_pending(self) -> None:
        self._mouse_delta.discard()

    async def flush(self) -> None:
        if not self._relay_gate.active:
            self.discard_pending()
            return
        delta = self._mouse_delta.flush()
        if delta is None:
            return
        await self._process_mouse_delta_with_retry(delta)

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

    async def _process_mouse_delta_with_retry(self, delta: MouseDelta) -> None:
        for partial in iter_mouse_delta_chunks(delta):

            def move_mouse(partial=partial) -> None:
                mouse = self._hid_gadgets.mouse
                if mouse is None:
                    raise RuntimeError(
                        "Mouse gadget is not available; HID gadgets are not enabled."
                    )
                mouse.move(*partial)

            if not await self._process_hid_action_with_retry(move_mouse, "mouse movement"):
                return

    async def _process_event_with_retry(self, event: InputEvent) -> None:
        await self._process_hid_action_with_retry(
            lambda: dispatch_event_to_hid(event, self._hid_gadgets), f"{event}"
        )

    async def _process_hid_action_with_retry(
        self, action: Callable[[], object], action_name: str
    ) -> bool:
        max_tries = self.HID_WRITE_MAX_TRIES
        retry_delay = self.HID_WRITE_RETRY_DELAY_SEC
        for attempt in range(1, max_tries + 1):
            if not self._relay_gate.active:
                return False
            try:
                action()
                return True
            except BlockingIOError:
                if not self._relay_gate.active:
                    return False
                if attempt < max_tries:
                    self._hid_write_retries += 1
                    logger.debug("HID write blocked (%s/%s)", attempt, max_tries)
                    await asyncio.sleep(retry_delay)
                else:
                    self._hid_write_failures += 1
                    logger.warning("HID write blocked (%s/%s)", attempt, max_tries)
                    return False
            except BrokenPipeError:
                self._hid_write_failures += 1
                logger.warning(
                    "BrokenPipeError: USB cable likely disconnected or power-only. "
                    + "Pausing relay.\nSee: "
                    + "https://github.com/quaxalber/bluetooth_2_usb/blob/main/TROUBLESHOOTING.md"
                )
                self._relay_gate.suspend_writes()
                return False
            except Exception:
                self._hid_write_failures += 1
                logger.exception("Unexpected error processing %s", action_name)
                raise
        return False


def dispatch_event_to_hid(event: InputEvent, hid_gadgets: HidGadgets) -> None:
    """
    Relay the given event to the appropriate USB HID device.

    :param event: The evdev InputEvent
    :param hid_gadgets: HidGadgets with references to HID devices
    :raises BlockingIOError: If HID device write is blocked
    """
    if isinstance(event, RelEvent):
        mouse = hid_gadgets.mouse
        if mouse is None:
            raise RuntimeError("Mouse gadget is not available; HID gadgets are not enabled.")
        mouse.move(*get_mouse_movement(event))
    elif isinstance(event, KeyEvent):
        dispatch_key_event_to_hid(event, hid_gadgets)


def dispatch_key_event_to_hid(event: KeyEvent, hid_gadgets: HidGadgets) -> None:
    """
    Relay a key event (press/release) to the appropriate HID gadget.

    :param event: The KeyEvent to process
    :param hid_gadgets: HidGadgets with references to the HID devices
    :raises RuntimeError: If no appropriate HID gadget is available
    """
    key_id, key_name = evdev_to_usb_hid(event)
    if key_id is None or key_name is None:
        return

    output_gadget = select_hid_gadget(event, hid_gadgets)
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


def select_hid_gadget(
    event: KeyEvent, hid_gadgets: HidGadgets
) -> ConsumerControl | Keyboard | ExtendedMouse | None:
    """
    Determine which HID gadget to target for the given key event.

    :param event: The KeyEvent to process
    :param hid_gadgets: HidGadgets for HID references
    :return: A ConsumerControl, Mouse, or Keyboard object, or None if not found
    """
    if is_consumer_key(event):
        return hid_gadgets.consumer
    if is_mouse_button(event):
        return hid_gadgets.mouse
    return hid_gadgets.keyboard
