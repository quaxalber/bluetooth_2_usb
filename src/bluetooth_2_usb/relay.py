import asyncio
from asyncio import CancelledError, Task, TaskGroup
from pathlib import Path
import re
from typing import Optional, Union, Any, Type

from adafruit_hid.consumer_control import ConsumerControl
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.mouse import Mouse
from evdev import InputDevice, InputEvent, KeyEvent, RelEvent, categorize, list_devices
import pyudev
import usb_hid
from usb_hid import Device

from .evdev import (
    evdev_to_usb_hid,
    get_mouse_movement,
    is_consumer_key,
    is_mouse_button,
)
from .logging import get_logger

_logger = get_logger()

PATH = "path"
MAC = "MAC"
NAME = "name"

PATH_REGEX = r"^/dev/input/event.*$"
MAC_REGEX = r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$"


class UsbHidManager:
    """
    Manages enabling, disabling, and providing references to USB HID devices.
    """

    def __init__(self) -> None:
        """
        The actual HID devices remain uninitialized until enable_devices() is called.
        """
        self._gadgets = {
            "keyboard": None,
            "mouse": None,
            "consumer": None,
        }
        self._enabled = False

    def enable_devices(self) -> None:
        """
        Disables and re-enables usb_hid devices to attach as mouse, keyboard, and consumer control.
        """
        try:
            usb_hid.disable()
        except Exception as ex:
            _logger.debug(f"usb_hid.disable() failed or was already disabled: {ex}")

        usb_hid.enable(
            [
                Device.BOOT_MOUSE,
                Device.KEYBOARD,
                Device.CONSUMER_CONTROL,
            ]  # type: ignore
        )
        enabled_devices = list(usb_hid.devices)  # type: ignore

        self._gadgets["keyboard"] = Keyboard(enabled_devices)
        self._gadgets["mouse"] = Mouse(enabled_devices)
        self._gadgets["consumer"] = ConsumerControl(enabled_devices)
        self._enabled = True

        _logger.debug(f"USB HID gadgets re-initialized: {enabled_devices}")

    def is_enabled(self) -> bool:
        """Return True if devices have been enabled."""
        return self._enabled

    def get_keyboard(self) -> Optional[Keyboard]:
        return self._gadgets["keyboard"]

    def get_mouse(self) -> Optional[Mouse]:
        return self._gadgets["mouse"]

    def get_consumer(self) -> Optional[ConsumerControl]:
        return self._gadgets["consumer"]


class RelayController:
    """
    Manages the TaskGroup of all active DeviceRelay tasks and handles
    add/remove events from UdevEventMonitor.

    If auto_discover is True, it will attempt to relay all valid input devices
    except those specifically skipped.
    """

    def __init__(
        self,
        usb_manager: UsbHidManager,
        device_identifiers: Optional[list[str]] = None,
        auto_discover: bool = False,
        skip_name_prefixes: Optional[list[str]] = None,
        grab_devices: bool = False,
        max_blockingio_retries: int = 2,
        blockingio_retry_delay: float = 0.01,
    ) -> None:
        """
        Args:
            usb_manager:
                A UsbHidManager instance that should already be enabled, or the caller
                can call usb_manager.enable_devices() as needed.
            device_identifiers:
                A list of path, MAC, or name fragments to identify devices to relay.
            auto_discover:
                If True, automatically relay any device that doesn't match skip_name_prefixes.
            skip_name_prefixes:
                A list of device.name prefixes to skip if auto_discover is True.
            grab_devices:
                If True, tries to grab exclusive access to each device.
            max_blockingio_retries, blockingio_retry_delay:
                Control how many times we retry a blocking HID write and the delay between retries.
        """
        self._usb_manager = usb_manager
        self._device_ids = [DeviceIdentifier(id) for id in (device_identifiers or [])]
        self._auto_discover = auto_discover
        self._skip_name_prefixes = skip_name_prefixes or ["vc4-hdmi"]
        self._grab_devices = grab_devices

        self._max_blockingio_retries = max_blockingio_retries
        self._blockingio_retry_delay = blockingio_retry_delay

        self._active_tasks: dict[str, Task] = {}
        self._task_group: Optional[TaskGroup] = None
        self._cancelled = False

    async def async_relay_devices(self) -> None:
        """
        Main method that opens a TaskGroup and relays events indefinitely,
        while device add/remove is handled dynamically.

        This function ends only if canceled or an unhandled exception occurs.
        """
        try:
            async with TaskGroup() as task_group:
                self._task_group = task_group
                _logger.debug("RelayController: TaskGroup started.")

                for device in await async_list_input_devices():
                    if self._should_relay(device):
                        self.add_device(device.path)

                while not self._cancelled:
                    await asyncio.sleep(0.1)
        except* Exception as exc_grp:
            _logger.exception(
                "RelayController: Exception in TaskGroup", exc_info=exc_grp
            )
        finally:
            self._task_group = None
            _logger.debug("RelayController: TaskGroup exited.")

    def add_device(self, device_path: str) -> None:
        """
        Called when a new device is detected. Schedules a new relay task if
        the device passes the _should_relay() check and isn't already tracked.
        """
        if not Path(device_path).exists():
            _logger.debug(f"{device_path} does not exist.")
            return

        try:
            device = InputDevice(device_path)
        except OSError:
            _logger.debug(f"{device_path} vanished before we could open it.")
            return

        if self._task_group is None:
            _logger.critical(f"No TaskGroup available; ignoring {device}.")
            return

        if device.path in self._active_tasks:
            _logger.debug(f"Device {device} is already active.")
            return

        task = self._task_group.create_task(
            self._async_relay_events(device), name=device.path
        )
        self._active_tasks[device.path] = task
        _logger.debug(f"Created task for {device}.")

    def remove_device(self, device_path: str) -> None:
        """
        Called when a device is removed. Cancels the associated relay task if running.
        """
        task = self._active_tasks.pop(device_path, None)
        if task and not task.done():
            _logger.debug(f"Cancelling relay for {device_path}.")
            task.cancel()
        else:
            _logger.debug(f"No active task found for {device_path} to remove.")

    async def _async_relay_events(self, device: InputDevice) -> None:
        """
        Creates a DeviceRelay in a context manager, then loops forever reading events.
        """
        try:
            async with DeviceRelay(
                device,
                self._usb_manager,
                grab_device=self._grab_devices,
                max_blockingio_retries=self._max_blockingio_retries,
                blockingio_retry_delay=self._blockingio_retry_delay,
            ) as relay:
                _logger.info(f"Activated {relay}")
                await relay.async_relay_events_loop()
        except CancelledError:
            _logger.debug(f"Relay cancelled for device {device}.")
            raise
        except (OSError, FileNotFoundError):
            _logger.info(f"Lost connection to {device}.")
        except Exception:
            _logger.exception(f"Unhandled exception in relay for {device}.")
        finally:
            self.remove_device(device.path)

    def _should_relay(self, device: InputDevice) -> bool:
        """
        Decide whether to relay this device.

        If auto_discover is True, the device is relayed if its name does not
        start with one of the 'skip_name_prefixes' and if it hasn't been matched
        by a skip. Otherwise, check if any configured DeviceIdentifier matches.
        """
        name_lower = device.name.lower()
        if self._auto_discover:
            for prefix in self._skip_name_prefixes:
                if name_lower.startswith(prefix.lower()):
                    return False
            return True

        return any(identifier.matches(device) for identifier in self._device_ids)


class DeviceRelay:
    """
    A relay for a single InputDevice, forwarding events to the USB HID gadgets.

    - Grabs/ungrabs the device if grab_device=True (in a context manager).
    - Retries HID writes if they raise BlockingIOError.
    """

    def __init__(
        self,
        input_device: InputDevice,
        usb_manager: UsbHidManager,
        grab_device: bool = False,
        max_blockingio_retries: int = 2,
        blockingio_retry_delay: float = 0.01,
    ) -> None:
        """
        Args:
            input_device: The evdev input device to be relayed.
            usb_manager: Provides access to keyboard/mouse/consumer HID gadgets.
            grab_device: If True, grabs exclusive access to input_device.
            max_blockingio_retries: How many times to retry a blocked HID write.
            blockingio_retry_delay: Delay between retries in seconds.
        """
        self._input_device = input_device
        self._usb_manager = usb_manager
        self._grab_device = grab_device
        self._max_blockingio_retries = max_blockingio_retries
        self._blockingio_retry_delay = blockingio_retry_delay

    async def __aenter__(self) -> "DeviceRelay":
        if self._grab_device:
            try:
                self._input_device.grab()
            except OSError as ex:
                _logger.debug(f"Could not grab {self._input_device.path}: {ex}")
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        if self._grab_device:
            try:
                self._input_device.ungrab()
            except Exception as ex:
                _logger.debug(f"Unable to ungrab {self._input_device.path}: {ex}")

        # Returning False means any exceptions are not suppressed.
        return False

    @property
    def input_device(self) -> InputDevice:
        """The underlying evdev input device."""
        return self._input_device

    def __str__(self) -> str:
        return f"relay for {self.input_device}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._input_device!r}, {self._grab_device})"

    async def async_relay_events_loop(self) -> None:
        """
        Continuously read events from the device (async evdev loop) and relay them
        to the USB HID gadgets. This method ends only if an error or cancellation occurs.
        """
        async for input_event in self._input_device.async_read_loop():
            event = categorize(input_event)
            _logger.debug(f"Received {event} from {self._input_device.name}")
            await self._process_event_with_retry(event)

    async def _process_event_with_retry(self, event: InputEvent) -> None:
        """
        Attempt to relay the given event. If a BlockingIOError occurs, retry
        up to self._max_blockingio_retries times. If still blocked, discard the event.
        """
        for attempt in range(self._max_blockingio_retries):
            try:
                relay_event(event, self._usb_manager)
                return
            except BlockingIOError:
                if attempt < self._max_blockingio_retries - 1:
                    _logger.debug(
                        f"HID write blocked (attempt {attempt+1}); retrying after "
                        f"{self._blockingio_retry_delay}s..."
                    )
                    await asyncio.sleep(self._blockingio_retry_delay)
                else:
                    _logger.debug(
                        f"HID write blocked again on final retry—skipping {event}."
                    )
                    return


class DeviceIdentifier:
    """
    Identifies an input device by either:
    - Path (/dev/input/eventX)
    - MAC address (XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX)
    - Name substring
    """

    def __init__(self, device_identifier: str) -> None:
        self._value = device_identifier
        self._type = self._determine_identifier_type()
        self._normalized_value = self._normalize_identifier()

    @property
    def value(self) -> str:
        return self._value

    @property
    def normalized_value(self) -> str:
        return self._normalized_value

    @property
    def type(self) -> str:
        return self._type

    def __str__(self) -> str:
        return f'{self.type} "{self.value}"'

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.value})"

    def _determine_identifier_type(self) -> str:
        if re.match(PATH_REGEX, self.value):
            return PATH
        if re.match(MAC_REGEX, self.value):
            return MAC
        return NAME

    def _normalize_identifier(self) -> str:
        if self.type == PATH:
            return self.value
        if self.type == MAC:
            return self.value.lower().replace("-", ":")
        return self.value.lower()

    def matches(self, device: InputDevice) -> bool:
        """
        Return True if this DeviceIdentifier matches the given evdev InputDevice.
        - If path-based, exact match to device.path.
        - If MAC-based, compare normalized MAC to device.uniq.
        - If name-based, check if normalized_value is a substring of the device name.
        """
        if self.type == PATH:
            return self.value == device.path
        if self.type == MAC:
            return self.normalized_value == (device.uniq or "").lower()
        return self.normalized_value in device.name.lower()


async def async_list_input_devices() -> list[InputDevice]:
    """
    Return a list of available /dev/input/event* devices.
    """
    try:
        return [InputDevice(path) for path in list_devices()]
    except (OSError, FileNotFoundError) as ex:
        _logger.critical(f"Failed listing devices: {ex}")
        return []
    except Exception:
        _logger.exception(f"Unexpected error listing devices")
        return []


def relay_event(event: InputEvent, usb_manager: UsbHidManager) -> None:
    """
    Relay an event to the correct USB HID function.
    May raise BlockingIOError if the HID device is busy.
    """
    if isinstance(event, RelEvent):
        move_mouse(event, usb_manager)
    elif isinstance(event, KeyEvent):
        send_key_event(event, usb_manager)


def move_mouse(event: RelEvent, usb_manager: UsbHidManager) -> None:
    """
    Relay relative movement events to the USB HID Mouse gadget.
    Raises BlockingIOError if the HID write cannot be completed.
    """
    mouse = usb_manager.get_mouse()
    if mouse is None:
        raise RuntimeError("Mouse gadget not initialized or manager not enabled.")

    x, y, mwheel = get_mouse_movement(event)
    coords = f"(x={x}, y={y}, mwheel={mwheel})"

    try:
        _logger.debug(f"Moving mouse {coords}")
        mouse.move(x, y, mwheel)
    except BlockingIOError:
        raise
    except Exception:
        _logger.exception(f"Failed moving mouse {coords}")


def send_key_event(event: KeyEvent, usb_manager: UsbHidManager) -> None:
    """
    Relay key press/release events to the appropriate USB HID gadget
    (keyboard, mouse-button, or consumer control).
    Raises BlockingIOError if the HID write cannot be completed.
    """
    key_id, key_name = evdev_to_usb_hid(event)
    if key_id is None or key_name is None:
        return

    output_gadget = get_output_device(event, usb_manager)
    if output_gadget is None:
        raise RuntimeError("No appropriate USB gadget found (manager not enabled?).")

    try:
        if event.keystate == KeyEvent.key_down:
            _logger.debug(f"Pressing {key_name} (0x{key_id:02X})")
            output_gadget.press(key_id)
        elif event.keystate == KeyEvent.key_up:
            _logger.debug(f"Releasing {key_name} (0x{key_id:02X})")
            output_gadget.release(key_id)
    except BlockingIOError:
        raise
    except Exception:
        _logger.exception(f"Failed sending 0x{key_id:02X} to {output_gadget}")


def get_output_device(
    event: KeyEvent, usb_manager: UsbHidManager
) -> Union[ConsumerControl, Keyboard, Mouse, None]:
    """
    Decide which HID gadget to use based on the event type:
      - Consumer keys: ConsumerControl
      - Mouse buttons: Mouse
      - Otherwise: Keyboard
    """
    if is_consumer_key(event):
        return usb_manager.get_consumer()
    elif is_mouse_button(event):
        return usb_manager.get_mouse()
    return usb_manager.get_keyboard()


class UdevEventMonitor:
    """
    Watches for new/removed /dev/input/event* devices and notifies RelayController.
    Provides a context manager interface to ensure graceful startup and shutdown.
    """

    def __init__(
        self,
        relay_controller: "RelayController",
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.relay_controller = relay_controller
        self.loop = loop
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem="input")

        self.observer = pyudev.MonitorObserver(self.monitor, self._udev_event_callback)
        _logger.debug("UdevEventMonitor initialized (observer not started yet).")

    def __enter__(self) -> "UdevEventMonitor":
        """
        Starts the observer on entering the context.
        """
        self.observer.start()
        _logger.debug("UdevEventMonitor started observer.")
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """
        Stops the observer on exiting the context.
        Returning False means we don't suppress any exceptions.
        """
        self.observer.stop()
        _logger.debug("UdevEventMonitor stopped observer.")
        return False

    def _udev_event_callback(self, action: str, device: pyudev.Device) -> None:
        """
        pyudev callback for device add/remove events.
        """
        device_node = device.device_node
        if not device_node or not device_node.startswith("/dev/input/event"):
            return

        if action == "add":
            _logger.debug(f"UdevEventMonitor: Added => {device_node}")
            self.relay_controller.add_device(device_node)
        elif action == "remove":
            _logger.debug(f"UdevEventMonitor: Removed => {device_node}")
            self.relay_controller.remove_device(device_node)
