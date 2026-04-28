from __future__ import annotations

import asyncio
import errno
from collections.abc import Callable
from typing import Any

from .evdev import ecodes, get_mouse_movement
from .evdev_compat import InputDevice, InputEvent, KeyEvent, RelEvent, categorize
from .gadget_manager import GadgetManager
from .hid_dispatch import dispatch_event_to_hid
from .logging import get_logger
from .mouse_delta import MouseDelta, MouseDeltaAccumulator, iter_mouse_delta_chunks
from .shortcut_toggler import ShortcutToggler

logger = get_logger(__name__)


class DeviceRelay:
    """
    Relay a single InputDevice's events to USB HID gadgets.

    - Optionally grabs the device exclusively.
    - Retries HID writes if they raise BlockingIOError.
    """

    HID_WRITE_MAX_TRIES = 20
    HID_WRITE_RETRY_DELAY_SEC = 0.01

    def __init__(
        self,
        input_device: InputDevice,
        gadget_manager: GadgetManager,
        relaying_active: asyncio.Event,
        grab_device: bool = False,
        shortcut_toggler: ShortcutToggler | None = None,
    ) -> None:
        """
        :param input_device: The evdev input device
        :param gadget_manager: Provides references to Keyboard, Mouse, ConsumerControl
        :param grab_device: Whether to grab the device for exclusive access
        :param relaying_active: asyncio.Event that indicates relaying is on/off
        :param shortcut_toggler: Optional handler for toggling relay via a shortcut
        """
        self._input_device = input_device
        self._gadget_manager = gadget_manager
        self._grab_device = grab_device
        self._relaying_active = relaying_active
        self._shortcut_toggler = shortcut_toggler

        self._currently_grabbed = False
        self._hid_write_retries = 0
        self._hid_write_failures = 0
        self._mouse_delta = MouseDeltaAccumulator()

    def __str__(self) -> str:
        return f"relay for {self._input_device}"

    @property
    def input_device(self) -> InputDevice:
        """
        The underlying evdev InputDevice being relayed.

        :return: The InputDevice
        :rtype: InputDevice
        """
        return self._input_device

    async def __aenter__(self) -> DeviceRelay:
        """
        Async context manager entry. Grabs the device if requested.

        :return: self
        """
        if self._grab_device and self._relaying_active.is_set():
            try:
                self._input_device.grab()
                self._currently_grabbed = True
            except Exception as ex:
                logger.warning("Could not grab %s: %s", self._input_device.path, ex)
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> bool:
        """
        Async context manager exit. Ungrabs the device if we grabbed it.

        :return: False to propagate exceptions
        """
        if self._currently_grabbed:
            try:
                self._input_device.ungrab()
                self._currently_grabbed = False
            except Exception as ex:
                self._currently_grabbed = False
                if self._should_ignore_ungrab_error(ex):
                    logger.debug(
                        "Skipping ungrab for %s because the device is no longer available.",
                        self._input_device.path,
                    )
                else:
                    logger.warning(
                        "Unable to ungrab %s: %s", self._input_device.path, ex
                    )
        try:
            self._input_device.close()
        except Exception:
            logger.debug("Ignoring close failure for %s", self._input_device.path)
        return False

    def _should_ignore_ungrab_error(self, ex: Exception) -> bool:
        return isinstance(ex, OSError) and ex.errno in (errno.ENODEV, errno.EBADF)

    def _update_grab_state(self, active: bool) -> None:
        if self._grab_device and active and not self._currently_grabbed:
            try:
                self._input_device.grab()
                self._currently_grabbed = True
                logger.debug("Grabbed %s", self._input_device)
            except Exception as ex:
                logger.warning("Could not grab %s: %s", self._input_device, ex)
        elif self._grab_device and not active and self._currently_grabbed:
            try:
                self._input_device.ungrab()
                self._currently_grabbed = False
                logger.debug("Ungrabbed %s", self._input_device)
            except Exception as ex:
                self._currently_grabbed = False
                if self._should_ignore_ungrab_error(ex):
                    logger.debug(
                        "Skipping ungrab for %s because the device is no longer available.",
                        self._input_device.path,
                    )
                else:
                    logger.warning("Could not ungrab %s: %s", self._input_device, ex)

    async def async_relay_events_loop(self) -> None:
        """
        Continuously read events from the device and relay them
        to the USB HID gadgets. Stops when canceled or on error.

        :return: None
        """
        try:
            async for input_event in self._input_device.async_read_loop():
                event = categorize(input_event)
                is_syn_report = (
                    getattr(input_event, "type", None) == ecodes.EV_SYN
                    and getattr(input_event, "code", None) == ecodes.SYN_REPORT
                )

                if any(isinstance(event, ev_type) for ev_type in [KeyEvent, RelEvent]):
                    logger.debug(
                        "Received %s from %s (%s)",
                        event,
                        self._input_device.name,
                        self._input_device.path,
                    )

                if self._shortcut_toggler and isinstance(event, KeyEvent):
                    if self._shortcut_toggler.handle_key_event(event):
                        active = self._relaying_active.is_set()
                        self._update_grab_state(active)
                        if not active:
                            self._discard_pending_mouse_state()
                        continue

                active = self._relaying_active.is_set()
                self._update_grab_state(active)

                if not active:
                    self._discard_pending_mouse_state()
                    continue

                if isinstance(event, RelEvent):
                    self._accumulate_mouse_movement(event)
                    continue

                if is_syn_report:
                    await self._flush_pending_mouse_movement()
                    continue

                # Preserve cross-gadget event order if another event arrives before SYN_REPORT.
                await self._flush_pending_mouse_movement()
                await self._process_event_with_retry(event)
        except OSError as ex:
            if ex.errno != errno.ENODEV:
                raise
            logger.debug(
                "Stopping relay loop for %s because the input device disappeared.",
                self._input_device.path,
            )
            self._discard_pending_mouse_state()
        await self._flush_pending_mouse_movement()
        logger.debug(
            "Relay stats for %s: hid_write_retries=%s hid_write_failures=%s",
            self._input_device.path,
            self._hid_write_retries,
            self._hid_write_failures,
        )

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

    def _discard_pending_mouse_state(self) -> None:
        self._mouse_delta.discard()

    async def _flush_pending_mouse_movement(self) -> None:
        delta = self._mouse_delta.flush()
        if delta is None:
            return
        await self._process_mouse_delta_with_retry(delta)

    async def _process_mouse_delta_with_retry(self, delta: MouseDelta) -> None:
        for partial in iter_mouse_delta_chunks(delta):

            def move_mouse(partial=partial) -> None:
                mouse = self._gadget_manager.mouse
                if mouse is None:
                    raise RuntimeError(
                        "Mouse gadget not initialized or manager not enabled."
                    )
                mouse.move(*partial)

            if not await self._process_hid_action_with_retry(
                move_mouse, "mouse movement"
            ):
                return

    async def _process_event_with_retry(self, event: InputEvent) -> None:
        """
        Attempt to relay the given event to the appropriate HID gadget.
        Retry on BlockingIOError within the bounded HID write budget.

        :param event: The InputEvent to process
        """
        await self._process_hid_action_with_retry(
            lambda: dispatch_event_to_hid(event, self._gadget_manager),
            f"{event}",
        )

    async def _process_hid_action_with_retry(
        self,
        action: Callable[[], Any],
        action_name: str,
    ) -> bool:
        """
        Attempt to relay one HID action and retry transient write blocking.

        :param action: Callable that performs one HID write operation
        :param action_name: Human-readable action for error logging
        """
        max_tries = self.HID_WRITE_MAX_TRIES
        retry_delay = self.HID_WRITE_RETRY_DELAY_SEC
        for attempt in range(1, max_tries + 1):
            try:
                action()
                return True
            except BlockingIOError:
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
                    "Pausing relay.\nSee: "
                    "https://github.com/quaxalber/bluetooth_2_usb/blob/main/TROUBLESHOOTING.md"
                )
                self._relaying_active.clear()
                return False
            except Exception:
                self._hid_write_failures += 1
                logger.exception("Error processing %s", action_name)
                return False
        return False
