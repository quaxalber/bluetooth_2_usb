from __future__ import annotations

from typing import TYPE_CHECKING

from .evdev import (
    evdev_to_usb_hid,
    get_mouse_movement,
    is_consumer_key,
    is_mouse_button,
)
from .evdev_compat import InputEvent, KeyEvent, RelEvent
from .extended_mouse import ExtendedMouse
from .gadget_manager import GadgetManager
from .logging import get_logger

if TYPE_CHECKING:
    from adafruit_hid.consumer_control import ConsumerControl
    from adafruit_hid.keyboard import Keyboard

logger = get_logger(__name__)


def dispatch_event_to_hid(event: InputEvent, gadget_manager: GadgetManager) -> None:
    """
    Relay the given event to the appropriate USB HID device.

    :param event: The evdev InputEvent
    :param gadget_manager: GadgetManager with references to HID devices
    :raises BlockingIOError: If HID device write is blocked
    """
    if isinstance(event, RelEvent):
        mouse = gadget_manager.mouse
        if mouse is None:
            raise RuntimeError("Mouse gadget not initialized or manager not enabled.")
        mouse.move(*get_mouse_movement(event))
    elif isinstance(event, KeyEvent):
        dispatch_key_event_to_hid(event, gadget_manager)


def dispatch_key_event_to_hid(event: KeyEvent, gadget_manager: GadgetManager) -> None:
    """
    Relay a key event (press/release) to the appropriate HID gadget.

    :param event: The KeyEvent to process
    :param gadget_manager: GadgetManager with references to the HID devices
    :raises RuntimeError: If no appropriate HID gadget is available
    """
    key_id, key_name = evdev_to_usb_hid(event)
    if key_id is None or key_name is None:
        return

    output_gadget = select_hid_gadget(event, gadget_manager)
    if output_gadget is None:
        raise RuntimeError("No appropriate USB gadget found (manager not enabled?).")

    if event.keystate == KeyEvent.key_down:
        logger.debug(f"Pressing {key_name} (0x{key_id:02X}) via {output_gadget}")
        output_gadget.press(key_id)
    elif event.keystate == KeyEvent.key_up:
        logger.debug(f"Releasing {key_name} (0x{key_id:02X}) via {output_gadget}")
        if is_consumer_key(event):
            output_gadget.release()
        else:
            output_gadget.release(key_id)


def select_hid_gadget(
    event: KeyEvent, gadget_manager: GadgetManager
) -> ConsumerControl | Keyboard | ExtendedMouse | None:
    """
    Determine which HID gadget to target for the given key event.

    :param event: The KeyEvent to process
    :param gadget_manager: GadgetManager for HID references
    :return: A ConsumerControl, Mouse, or Keyboard object, or None if not found
    """
    if is_consumer_key(event):
        return gadget_manager.consumer
    if is_mouse_button(event):
        return gadget_manager.mouse
    return gadget_manager.keyboard
