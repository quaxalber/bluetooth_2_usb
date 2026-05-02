from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

from ..hid.consumer import ExtendedConsumerControl
from ..hid.keyboard import ExtendedKeyboard
from ..hid.mouse import ExtendedMouse
from ..logging import get_logger
from .config import rebuild_gadget
from .layout import build_default_layout

logger = get_logger(__name__)


class HidGadgets:
    """
    Manages enabling, disabling, and references to USB HID gadget devices.

    :ivar _gadgets: Internal dictionary mapping device types to HID device objects
    :ivar _enabled: Indicates whether the gadgets have been enabled
    """

    HIDG_NODE_READY_TIMEOUT_SEC = 2.0
    HIDG_NODE_POLL_INTERVAL_SEC = 0.05

    def __init__(self) -> None:
        """
        Initialize without enabling devices. Call enable() to enable them.
        """
        self._clear_gadget_state()

    def _clear_gadget_state(self) -> None:
        self._gadgets = {"keyboard": None, "mouse": None, "consumer": None}
        self._enabled = False

    def requested_devices(self):
        """
        Return the HID devices declared by the default gadget layout.

        :return: A list of configured HID layout device declarations.
        """
        return list(build_default_layout().devices)

    def declared_hidg_paths(self) -> tuple[Path, ...]:
        """
        Return the /dev/hidg paths expected from the default gadget layout.

        :return: Paths derived from the declared HID function indexes.
        """
        return tuple(Path(f"/dev/hidg{device.function_index}") for device in self.requested_devices())

    def _hidg_path(self, device) -> Path | None:
        if getattr(device, "path", None):
            return Path(device.path)
        try:
            return Path(device.get_device_path())
        except FileNotFoundError:
            return None

    def _hidg_paths(self, devices) -> tuple[Path, ...]:
        return tuple(path for device in devices if (path := self._hidg_path(device)) is not None)

    def prune_stale_hidg_nodes(
        self, paths: tuple[Path, ...] | None = None, *, remove_character_devices: bool = False
    ) -> None:
        """
        Remove stale HID gadget device nodes before rebuilding the gadget.

        :param paths: Optional paths to prune. Defaults to the layout-declared /dev/hidg paths.
        :param remove_character_devices: Whether character device nodes should also be removed.
        :return: None.
        """
        for path in self.declared_hidg_paths() if paths is None else paths:
            try:
                mode = path.stat().st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISCHR(mode) and not remove_character_devices:
                continue
            logger.warning("Removing stale HID gadget path %s", path)
            try:
                path.unlink()
            except FileNotFoundError:
                continue

    def collect_invalid_hidg_nodes(self, devices) -> list[str]:
        """
        Inspect enabled HID device nodes and describe nodes that are not writable character devices.

        :param devices: Enabled usb_hid devices returned by gadget rebuild.
        :return: Human-readable descriptions of unhealthy device nodes.
        """
        invalid_paths: list[str] = []
        for device in devices:
            path = self._hidg_path(device)
            if path is None:
                invalid_paths.append(f"{device.name} (missing device path)")
                continue
            try:
                stats = path.stat()
            except FileNotFoundError:
                invalid_paths.append(f"{path} (missing)")
                continue
            mode = stats.st_mode
            if not stat.S_ISCHR(mode):
                invalid_paths.append(f"{path} (mode=0o{mode:o})")
                continue
            try:
                fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                message = exc.strerror or exc.__class__.__name__
                invalid_paths.append(f"{path} ({message})")
                continue
            os.close(fd)
        return invalid_paths

    async def validate_hidg_nodes(
        self, devices, timeout_sec: float | None = None, poll_interval_sec: float | None = None
    ) -> None:
        """
        Wait until all enabled HID device nodes are present and writable.

        :param devices: Enabled usb_hid devices returned by gadget rebuild.
        :param timeout_sec: Maximum time to wait, or None for the default timeout.
        :param poll_interval_sec: Delay between health checks, or None for the default interval.
        :return: None.
        :raises RuntimeError: If any HID device node remains unhealthy when the timeout expires.
        """
        timeout_sec = self.HIDG_NODE_READY_TIMEOUT_SEC if timeout_sec is None else timeout_sec
        poll_interval_sec = self.HIDG_NODE_POLL_INTERVAL_SEC if poll_interval_sec is None else poll_interval_sec
        deadline = asyncio.get_running_loop().time() + max(timeout_sec, 0.0)

        while True:
            invalid_paths = self.collect_invalid_hidg_nodes(devices)
            if not invalid_paths:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("USB HID gadget nodes are not healthy: " + ", ".join(invalid_paths))
            await asyncio.sleep(poll_interval_sec)

    async def enable(self) -> None:
        """
        Disable and re-enable usb_hid devices, then store references
        to the new Keyboard, Mouse, and ConsumerControl gadgets.
        """
        self._clear_gadget_state()
        self.prune_stale_hidg_nodes()
        enabled_devices = list(rebuild_gadget(build_default_layout()))
        try:
            await self.validate_hidg_nodes(enabled_devices)
        except RuntimeError:
            logger.warning("Retrying HID gadget initialization after stale node validation failure")
            self.prune_stale_hidg_nodes(self._hidg_paths(enabled_devices), remove_character_devices=True)
            enabled_devices = list(rebuild_gadget(build_default_layout()))
            await self.validate_hidg_nodes(enabled_devices)

        self._gadgets["keyboard"] = ExtendedKeyboard(enabled_devices)
        self._gadgets["mouse"] = ExtendedMouse(enabled_devices)
        self._gadgets["consumer"] = ExtendedConsumerControl(enabled_devices)
        self._enabled = True

        logger.debug("USB HID gadgets initialized: %s", enabled_devices)

    @property
    def keyboard(self) -> ExtendedKeyboard | None:
        """
        Get the Keyboard gadget.

        :return: An ExtendedKeyboard object, or None if not initialized
        :rtype: ExtendedKeyboard | None
        """
        return self._gadgets["keyboard"]

    @property
    def mouse(self) -> ExtendedMouse | None:
        """
        Get the Mouse gadget.

        :return: An ExtendedMouse object, or None if not initialized
        :rtype: ExtendedMouse | None
        """
        return self._gadgets["mouse"]

    @property
    def consumer(self) -> ExtendedConsumerControl | None:
        """
        Get the ConsumerControl gadget.

        :return: An ExtendedConsumerControl object, or None if not initialized
        :rtype: ExtendedConsumerControl | None
        """
        return self._gadgets["consumer"]

    async def release_all(self) -> None:
        """
        Best-effort release of any pressed/active state on all HID gadgets.

        Shared gadget state is owned by HidGadgets rather than individual
        device relays, so host disconnect and shutdown can clear host-visible
        state explicitly.
        """
        seen: set[int] = set()
        for name, gadget in self._gadgets.items():
            if gadget is None or id(gadget) in seen:
                continue
            seen.add(id(gadget))
            try:
                if hasattr(gadget, "release_all"):
                    await gadget.release_all()
                elif hasattr(gadget, "release"):
                    await gadget.release()
            except Exception:
                logger.debug("Ignoring %s gadget release failure", name)
