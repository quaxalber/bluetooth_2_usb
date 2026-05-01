from __future__ import annotations

import errno

from .evdev_types import InputDevice, KeyEvent, RelEvent, categorize
from .hid_dispatch import HidDispatcher
from .hid_gadgets import HidGadgets
from .logging import get_logger
from .relay_gate import RelayGate
from .shortcut_toggler import ShortcutToggler

logger = get_logger(__name__)


class InputRelay:
    """
    Relay a single InputDevice's events to USB HID gadgets.

    - Optionally grabs the device exclusively.
    - Delegates HID translation and writes to HidDispatcher.
    """

    def __init__(
        self,
        input_device: InputDevice,
        hid_gadgets: HidGadgets,
        relay_gate: RelayGate,
        grab_device: bool = False,
        shortcut_toggler: ShortcutToggler | None = None,
    ) -> None:
        """
        :param input_device: The evdev input device
        :param hid_gadgets: Provides references to Keyboard, Mouse, ConsumerControl
        :param grab_device: Whether to grab the device for exclusive access
        :param relay_gate: RelayGate that indicates whether relaying is active
        :param shortcut_toggler: Optional handler for toggling relay via a shortcut
        """
        self._input_device = input_device
        self._dispatcher = HidDispatcher(hid_gadgets, relay_gate)
        self._grab_device = grab_device
        self._relay_gate = relay_gate
        self._shortcut_toggler = shortcut_toggler

        self._currently_grabbed = False

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

    async def __aenter__(self) -> InputRelay:
        """
        Async context manager entry. Grabs the device if requested.

        :return: self
        """
        self._relay_gate.add_listener(self._handle_gate_change)
        self._handle_gate_change(self._relay_gate.active)
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
                    logger.warning("Unable to ungrab %s: %s", self._input_device.path, ex)
        self._relay_gate.remove_listener(self._handle_gate_change)
        return False

    def _should_ignore_ungrab_error(self, ex: Exception) -> bool:
        return isinstance(ex, OSError) and ex.errno in (errno.ENODEV, errno.EBADF)

    def _handle_gate_change(self, active: bool) -> None:
        self._update_grab_state(active)
        if not active:
            self._dispatcher.discard_pending()

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
        input_disappeared = False
        try:
            async for input_event in self._input_device.async_read_loop():
                event = categorize(input_event)

                if any(isinstance(event, ev_type) for ev_type in [KeyEvent, RelEvent]):
                    logger.debug(
                        "Received %s from %s (%s)",
                        event,
                        self._input_device.name,
                        self._input_device.path,
                    )

                if self._shortcut_toggler and isinstance(event, KeyEvent):
                    if self._shortcut_toggler.handle_key_event(event):
                        continue

                if not self._relay_gate.active:
                    self._dispatcher.discard_pending()
                    continue

                await self._dispatcher.dispatch(event, input_event)
        except OSError as ex:
            if ex.errno != errno.ENODEV:
                raise
            input_disappeared = True
            logger.debug(
                "Stopping relay loop for %s because the input device disappeared.",
                self._input_device.path,
            )
            self._dispatcher.discard_pending()
        try:
            await self._dispatcher.flush()
        except OSError as ex:
            if not input_disappeared or ex.errno != errno.ENODEV:
                raise
            logger.debug(
                "Ignoring pending mouse flush failure for %s after input device disappeared: %s",
                self._input_device.path,
                ex,
            )
        logger.debug(
            "Relay stats for %s: hid_write_retries=%s hid_write_failures=%s",
            self._input_device.path,
            self._dispatcher.stats.write_retries,
            self._dispatcher.stats.write_failures,
        )
