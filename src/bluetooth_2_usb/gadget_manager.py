from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .extended_mouse import ExtendedMouse
from .gadget_config import rebuild_gadget
from .hid_layout import build_default_layout
from .logging import get_logger

if TYPE_CHECKING:
    from adafruit_hid.consumer_control import ConsumerControl
    from adafruit_hid.keyboard import Keyboard

logger = get_logger(__name__)


class GadgetManager:
    """
    Manages enabling, disabling, and references to USB HID gadget devices.

    :ivar _gadgets: Internal dictionary mapping device types to HID device objects
    :ivar _enabled: Indicates whether the gadgets have been enabled
    """

    HIDG_NODE_READY_TIMEOUT_SEC = 2.0
    HIDG_NODE_POLL_INTERVAL_SEC = 0.05

    def __init__(self) -> None:
        """
        Initialize without enabling devices. Call enable_gadgets() to enable them.
        """
        self._gadgets = {
            "keyboard": None,
            "mouse": None,
            "consumer": None,
        }
        self._enabled = False

    def _requested_devices(self):
        return list(build_default_layout().devices)

    def _expected_hidg_paths(self) -> tuple[Path, ...]:
        return tuple(
            Path(f"/dev/hidg{device.function_index}")
            for device in self._requested_devices()
        )

    def _prune_stale_hidg_nodes(
        self, *, remove_character_devices: bool = False
    ) -> None:
        for path in self._expected_hidg_paths():
            try:
                mode = path.stat().st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISCHR(mode) and not remove_character_devices:
                continue
            logger.warning("Removing stale HID gadget path %s", path)
            path.unlink()

    def _collect_invalid_hidg_nodes(self) -> list[str]:
        invalid_paths: list[str] = []
        for device, path in zip(
            self._requested_devices(), self._expected_hidg_paths(), strict=False
        ):
            try:
                stats = path.stat()
            except FileNotFoundError:
                invalid_paths.append(f"{path} (missing)")
                continue
            mode = stats.st_mode
            if not stat.S_ISCHR(mode):
                invalid_paths.append(f"{path} (mode=0o{mode:o})")
                continue
            expected_minor = device.function_index
            if os.minor(stats.st_rdev) != expected_minor:
                invalid_paths.append(
                    f"{path} (minor={os.minor(stats.st_rdev)}, expected={expected_minor})"
                )
                continue
            try:
                fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                message = exc.strerror or exc.__class__.__name__
                invalid_paths.append(f"{path} ({message})")
                continue
            os.close(fd)
        return invalid_paths

    def _validate_hidg_nodes(
        self,
        timeout_sec: float | None = None,
        poll_interval_sec: float | None = None,
    ) -> None:
        timeout_sec = (
            self.HIDG_NODE_READY_TIMEOUT_SEC if timeout_sec is None else timeout_sec
        )
        poll_interval_sec = (
            self.HIDG_NODE_POLL_INTERVAL_SEC
            if poll_interval_sec is None
            else poll_interval_sec
        )
        deadline = time.monotonic() + max(timeout_sec, 0.0)

        while True:
            invalid_paths = self._collect_invalid_hidg_nodes()
            if not invalid_paths:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "USB HID gadget nodes are not healthy: " + ", ".join(invalid_paths)
                )
            time.sleep(poll_interval_sec)

    def enable_gadgets(self) -> None:
        """
        Disable and re-enable usb_hid devices, then store references
        to the new Keyboard, Mouse, and ConsumerControl gadgets.
        """
        self._prune_stale_hidg_nodes(remove_character_devices=True)
        enabled_devices = list(rebuild_gadget(build_default_layout()))
        try:
            self._validate_hidg_nodes()
        except RuntimeError:
            logger.warning(
                "Retrying HID gadget initialization after stale node validation failure"
            )
            self._prune_stale_hidg_nodes(remove_character_devices=True)
            enabled_devices = list(rebuild_gadget(build_default_layout()))
            self._validate_hidg_nodes()

        from adafruit_hid.consumer_control import ConsumerControl
        from adafruit_hid.keyboard import Keyboard

        self._gadgets["keyboard"] = Keyboard(enabled_devices)
        self._gadgets["mouse"] = ExtendedMouse(enabled_devices)
        self._gadgets["consumer"] = ConsumerControl(enabled_devices)
        self._enabled = True

        logger.debug("USB HID gadgets initialized: %s", enabled_devices)

    def get_keyboard(self) -> Keyboard | None:
        """
        Get the Keyboard gadget.

        :return: A Keyboard object, or None if not initialized
        :rtype: Keyboard | None
        """
        return self._gadgets["keyboard"]

    def get_mouse(self) -> ExtendedMouse | None:
        """
        Get the Mouse gadget.

        :return: An ExtendedMouse object, or None if not initialized
        :rtype: ExtendedMouse | None
        """
        return self._gadgets["mouse"]

    def get_consumer(self) -> ConsumerControl | None:
        """
        Get the ConsumerControl gadget.

        :return: A ConsumerControl object, or None if not initialized
        :rtype: ConsumerControl | None
        """
        return self._gadgets["consumer"]

    def release_all_gadgets(self) -> None:
        """
        Best-effort release of any pressed/active state on all HID gadgets.

        Shared gadget state is owned by the manager rather than individual
        device relays, so global shutdown can clear host-visible state once.
        """
        seen: set[int] = set()
        for name, gadget in self._gadgets.items():
            if gadget is None or id(gadget) in seen:
                continue
            seen.add(id(gadget))
            try:
                if hasattr(gadget, "release_all"):
                    gadget.release_all()
                elif hasattr(gadget, "release"):
                    gadget.release()
            except Exception:
                logger.debug("Ignoring %s gadget release failure", name)
