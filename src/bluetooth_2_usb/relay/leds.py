"""Mirror host keyboard LED state (Num/Caps/Scroll Lock) to relayed keyboards.

The USB host sends the boot-keyboard LED output report to the keyboard gadget.
The Linux HID gadget exposes those host-to-device reports as readable data on
the keyboard ``/dev/hidgN`` node. This module reads them and forwards the LED
bits to every relayed input device that advertises ``EV_LED`` support.
"""

from __future__ import annotations

import asyncio
import errno
import os
from pathlib import Path

from ..evdev.ecodes import ecodes
from ..evdev.types import InputDevice
from ..logging import get_logger

logger = get_logger(__name__)

HID_LED_BITS: tuple[tuple[int, int], ...] = (
    (0x01, ecodes.LED_NUML),
    (0x02, ecodes.LED_CAPSL),
    (0x04, ecodes.LED_SCROLLL),
    (0x08, ecodes.LED_COMPOSE),
    (0x10, ecodes.LED_KANA),
)
"""HID LED usage bit -> evdev LED code, in boot-keyboard output report order."""

LED_REPORT_READ_SIZE = 64


def _supports_leds(device: InputDevice) -> tuple[int, ...]:
    try:
        capabilities = device.capabilities()
    except Exception:
        return ()
    return tuple(capabilities.get(ecodes.EV_LED, ()) or ())


class KeyboardLedMirror:
    """Read host LED output reports and apply them to relayed keyboards."""

    def __init__(self, hidg_path: Path | str | None) -> None:
        self._hidg_path = Path(hidg_path) if hidg_path else None
        self._led_state: int | None = None
        self._devices: dict[str, tuple[InputDevice, tuple[int, ...]]] = {}

    @property
    def led_state(self) -> int | None:
        return self._led_state

    def register(self, device: InputDevice) -> None:
        """Track a relayed device and apply the current host LED state to it."""
        supported = _supports_leds(device)
        if not supported:
            return
        self._devices[device.path] = (device, supported)
        if self._led_state is not None:
            self._apply_to(device, supported, self._led_state)

    def unregister(self, device_path: str) -> None:
        self._devices.pop(device_path, None)

    def handle_report(self, report: bytes) -> None:
        """Apply one LED output report received from the host."""
        if not report:
            return
        state = report[-1]
        if state == self._led_state:
            return
        self._led_state = state
        logger.debug("Host keyboard LED state changed: 0x%02x", state)
        for device, supported in list(self._devices.values()):
            self._apply_to(device, supported, state)

    def _apply_to(self, device: InputDevice, supported: tuple[int, ...], state: int) -> None:
        for bit, led_code in HID_LED_BITS:
            if led_code not in supported:
                continue
            try:
                device.set_led(led_code, 1 if state & bit else 0)
            except OSError as exc:
                logger.debug("Could not set LED %s on %s: %s", led_code, device.path, exc)
                return
            except Exception:
                logger.debug("Could not set LED %s on %s", led_code, device.path, exc_info=True)
                return

    async def run(self) -> None:
        """Read LED output reports from the keyboard gadget node until cancelled."""
        if self._hidg_path is None:
            logger.debug("No keyboard gadget path available; LED mirroring disabled.")
            return
        try:
            fd = os.open(self._hidg_path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            logger.warning("Keyboard LED mirroring unavailable (%s): %s", self._hidg_path, exc)
            return

        loop = asyncio.get_running_loop()
        stopped: asyncio.Future[None] = loop.create_future()

        def _on_readable() -> None:
            try:
                data = os.read(fd, LED_REPORT_READ_SIZE)
            except BlockingIOError:
                return
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EINTR):
                    return
                logger.debug("Stopping keyboard LED mirroring: %s", exc)
                if not stopped.done():
                    stopped.set_result(None)
                return
            self.handle_report(data)

        loop.add_reader(fd, _on_readable)
        logger.debug("Mirroring host keyboard LEDs from %s", self._hidg_path)
        try:
            await stopped
        finally:
            loop.remove_reader(fd)
            os.close(fd)
