#!/usr/bin/env python
"""
Reads incoming mouse and keyboard events (e.g., Bluetooth) and forwards them to USB
using Linux's gadget mode.
"""

import asyncio
from asyncio import TaskGroup, Task
from datetime import datetime
from logging import DEBUG
import signal
import sys
from typing import Collection, NoReturn

from adafruit_hid.consumer_control import ConsumerControl
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.mouse import Mouse
from evdev import (
    InputDevice,
    InputEvent,
    categorize,
    list_devices,
)
import usb_hid
from usb_hid import Device as GadgetDevice, unregister_disable

from lib.args import parse_args
from lib.device_link import DeviceLink
import lib.evdev_adapter as evdev_adapter
import lib.logger

_VERSION = "0.4.6"
_VERSIONED_NAME = f"Bluetooth 2 USB v{_VERSION}"

_logger = lib.logger.get_logger()


class ComboDeviceHidProxy:
    """
    This class serves as a HID proxy to handle both keyboard and mouse devices.
    """

    def __init__(
        self,
        keyboard_paths: list[str] = None,
        mouse_paths: list[str] = None,
        is_sandbox: bool = False,
    ) -> None:
        self._init_variables()
        self._init_devices(keyboard_paths, mouse_paths, is_sandbox)

    def _init_variables(self) -> None:
        # Device links, that have been registered to this instance, but not
        # necessarily connected. Only connected links are ready to be used.
        self._registered_links: list[DeviceLink] = []
        self._is_sandbox: bool = False
        self._gadgets_enabled: bool = False
        self._task_group: TaskGroup

    def _init_devices(
        self,
        keyboard_paths: list[str] = None,
        mouse_paths: list[str] = None,
        is_sandbox: bool = False,
    ) -> None:
        try:
            self.enable_usb_gadgets()
            self._create_and_register_links(keyboard_paths, mouse_paths)
            self.enable_sandbox(is_sandbox)
            self._log_registered_links()

        except Exception:
            _logger.exception(f"Failed to initialize devices.")
            raise

    def enable_usb_gadgets(self, gadgets_enabled: bool = True) -> None:
        try:
            self._check_enable_gadgets(gadgets_enabled)
            self._log_gadgets()

        except Exception:
            action = "enable" if gadgets_enabled else "disable"
            _logger.exception(f"Failed to {action} gadget devices.")
            raise

    def _check_enable_gadgets(self, gadgets_enabled: bool) -> None:
        # Nothing to do if the state didn't change
        if self._gadgets_enabled == gadgets_enabled:
            return
        self._gadgets_enabled = gadgets_enabled

        if gadgets_enabled:
            # We have to use BOOT_MOUSE since somehow MOUSE freezes on any input.
            # This should be fine though. Also it's important to enable mouse first.
            usb_hid.enable(
                [
                    GadgetDevice.BOOT_MOUSE,
                    GadgetDevice.KEYBOARD,
                    GadgetDevice.CONSUMER_CONTROL,
                ]
            )
        else:
            usb_hid.disable()

    def _log_gadgets(self) -> None:
        if self._gadgets_enabled:
            _logger.debug(f"Available output devices: {usb_hid.devices}")
        else:
            _logger.warning(f"All output devices disabled!")

    def _create_and_register_links(
        self,
        keyboard_paths: list[str] = None,
        mouse_paths: list[str] = None,
    ) -> None:
        if keyboard_paths is None:
            keyboard_paths = []
        if mouse_paths is None:
            mouse_paths = []

        keyboards = [self.create_keyboard_link(path) for path in keyboard_paths]
        mice = [self.create_mouse_link(path) for path in mouse_paths]

        # Use list unpacking to get a nice comma-separated sequence of all devices
        self.register_device_links(*keyboards, *mice)

    def register_device_links(self, *device_links: DeviceLink | None) -> None:
        for link in device_links:
            self._register_single_link(link)

    def _register_single_link(self, link: DeviceLink | None) -> None:
        if link and link not in self._registered_links:
            self._registered_links.append(link)

    def create_keyboard_link(self, keyboard_path: str) -> DeviceLink | None:
        return self._create_device_link(
            keyboard_path,
            keyboard_gadget=Keyboard(usb_hid.devices),
            consumer_control_gadget=ConsumerControl(usb_hid.devices),
        )

    def create_mouse_link(self, mouse_path: str) -> DeviceLink | None:
        return self._create_device_link(mouse_path, mouse_gadget=Mouse(usb_hid.devices))

    def _create_device_link(
        self,
        input_device_path: str,
        keyboard_gadget: Keyboard = None,
        mouse_gadget: Mouse = None,
        consumer_control_gadget: ConsumerControl = None,
    ) -> DeviceLink | None:
        if not input_device_path:
            return None

        device_link = DeviceLink(
            input_device_path, keyboard_gadget, mouse_gadget, consumer_control_gadget
        )

        return device_link

    def enable_sandbox(self, sandbox_enabled: bool = True) -> None:
        self._check_enable_sandbox(sandbox_enabled)
        self._log_sandbox_status()

    def _check_enable_sandbox(self, sandbox_enabled: bool) -> None:
        # Nothing to do if the state didn't change
        if self._is_sandbox == sandbox_enabled:
            return
        self._is_sandbox = sandbox_enabled

        gadgets_enabled = not sandbox_enabled
        self._enable_gadgets(gadgets_enabled)

    def _enable_gadgets(self, gadgets_enabled: bool) -> None:
        for link in self._registered_links:
            link.gadgets_enabled = gadgets_enabled

    def _log_sandbox_status(self) -> None:
        if self._is_sandbox:
            _logger.warning("Sandbox mode enabled! All output devices deactivated.")
        else:
            _logger.debug("Sandbox mode disabled. All output devices activated.")

    def _log_registered_links(self) -> None:
        for link in self._registered_links:
            _logger.debug(f"Registered device link: {link}")

    async def async_connect_registered_links(self) -> NoReturn:
        try:
            async with TaskGroup() as self._task_group:
                self._connect_device_links(self._registered_links)

            _logger.critical("Event loop closed.")

        except* Exception as ex:
            _logger.error(f"Error(s) in TaskGroup: [{ex.exceptions}]")

    def _connect_device_links(self, device_links: Collection[DeviceLink]) -> None:
        for link in device_links:
            self._connect_single_link(link)

        _logger.debug(f"Current tasks: {asyncio.all_tasks()}")

    def _connect_single_link(self, device_link: DeviceLink) -> None:
        self._task_group.create_task(
            self._async_relay_input_events(device_link), name=str(device_link)
        )

        _logger.debug(f"Connected device link: {device_link}")

    async def _async_relay_input_events(self, device_link: DeviceLink) -> None:
        _logger.info(f"Starting event loop for {repr(device_link)}")
        should_reconnect = True

        try:
            if (not device_link.input_device_connected):
                device_link.reset_input_device()
            await self._async_relay_input_events_loop(device_link)
        except OSError as ex:
            _logger.critical(
                f"{device_link.name} disconnected. Reconnecting... [{repr(ex)}]"
            )
            reconnected = await self._async_wait_for_device(device_link)
            self._log_reconnection_outcome(device_link, reconnected)

        except asyncio.exceptions.CancelledError:
            _logger.critical(f"{device_link.name} received a cancellation request.")
            should_reconnect = False

        except Exception:
            _logger.exception(f"{device_link.name} failed! Restarting task...")
            await asyncio.sleep(5)

        finally:
            await self._async_disconnect_device_link(device_link, should_reconnect)

    async def _async_relay_input_events_loop(self, device_link: DeviceLink):
        input_device = device_link.input_device

        async for event in input_device.async_read_loop():
            if not event:
                continue

            await self._async_relay_single_event(event, device_link)

    async def _async_relay_single_event(
        self, event: InputEvent, device_link: DeviceLink
    ) -> None:
        _logger.debug(f"Received event: [{categorize(event)}]")

        if evdev_adapter.is_key_event(event):
            await self._async_send_key(event, device_link)
        elif evdev_adapter.is_mouse_movement(event):
            await self._async_move_mouse(event, device_link.mouse_gadget)

    async def _async_send_key(self, event: InputEvent, device_link: DeviceLink) -> None:
        hid_key = evdev_adapter.to_hid_usage_id(event)
        device_out = evdev_adapter.get_output_device(event, device_link)

        if hid_key is None or device_out is None:
            return

        try:
            if evdev_adapter.is_key_up(event):
                device_out.release(hid_key)
            elif evdev_adapter.is_key_down(event):
                device_out.press(hid_key)

        except Exception:
            _logger.exception(f"Error sending [{categorize(event)}] to {device_out}")

    async def _async_move_mouse(self, event: InputEvent, mouse: Mouse) -> None:
        if mouse is None:
            return

        x, y, mwheel = evdev_adapter.get_mouse_movement(event)
        _logger.debug(f"Moving mouse {mouse}: (x, y, mwheel) = {(x, y, mwheel)}")

        try:
            mouse.move(x, y, mwheel)
        except Exception:
            _logger.exception(f"Error sending [{categorize(event)}] to {mouse}")

    async def _async_wait_for_device(
        self, device_link: DeviceLink, delay_seconds: float = 1
    ) -> bool:
        await asyncio.sleep(delay_seconds)
        last_log_time = datetime.now()

        while device_link.path not in list_devices():
            last_log_time = self._log_reconnection_attempt(device_link, last_log_time)
            await asyncio.sleep(delay_seconds)

        return True

    def _log_reconnection_attempt(
        self, device_link: DeviceLink, last_log_time: datetime
    ) -> datetime:
        if _elapsed_seconds_since(last_log_time) >= 60:
            _logger.debug(f"Still trying to reconnect to {device_link.name}...")
            last_log_time = datetime.now()

        return last_log_time

    def _log_reconnection_outcome(self, device_link: DeviceLink, reconnected: bool):
        if reconnected:
            _logger.info(f"Successfully reconnected to {device_link.name}.")
        else:
            _logger.critical(f"Reconnecting to {device_link.name} failed.")

    async def _async_disconnect_device_link(
        self, device_link: DeviceLink, reconnect: bool = False
    ) -> None:
        task = _get_task(str(device_link))
        if task:
            task.cancel()

        if reconnect:
            await device_link.async_reset_input_device()
            self._connect_single_link(device_link)


def _elapsed_seconds_since(reference_time: datetime) -> float:
    current_time = datetime.now()
    return (current_time - reference_time).total_seconds()


def _get_task(task_name: str) -> Task | None:
    for task in asyncio.all_tasks():
        if task.get_name() == task_name:
            return task

    return None


def _signal_handler(sig, frame) -> NoReturn:
    _logger.info(f"Exiting gracefully. Received signal: {sig}, frame: {frame}")
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


async def _main() -> NoReturn:
    """
    Parses command-line arguments, sets up logging and starts the event loop which
    reads events from the input devices and forwards them to the corresponding USB
    gadget device.
    """
    args = parse_args()

    if args.version:
        _print_version()

    if args.list_devices:
        _list_devices()

    if args.debug:
        _logger.setLevel(DEBUG)

    log_handlers_message = "Logging to stdout"

    if args.log_to_file:
        lib.logger.add_file_handler(args.log_path)
        log_handlers_message += f" and to {args.log_path}"

    _logger.debug(f"CLI args: {args}")
    _logger.debug(log_handlers_message)
    _logger.info(f"Launching {_VERSIONED_NAME}")

    proxy = ComboDeviceHidProxy(args.keyboards, args.mice, args.sandbox)
    await proxy.async_connect_registered_links()


def _list_devices():
    devices = [InputDevice(path) for path in list_devices()]
    for device in devices:
        print(f"{device.name}\t{device.phys}\t{device.path}")

    _exit_safely()


def _print_version():
    print(_VERSIONED_NAME)
    _exit_safely()


def _exit_safely():
    unregister_disable()
    sys.exit(0)


if __name__ == "__main__":
    """
    Entry point for the script.
    """
    try:
        asyncio.run(_main())

    except Exception:
        _logger.exception("Houston, we have an unhandled problem. Abort mission.")
