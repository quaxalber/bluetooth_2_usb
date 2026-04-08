from evdev import InputDevice, list_devices

from .logging import get_logger

_logger = get_logger()


async def async_list_input_devices() -> list[InputDevice]:
    """
    Return a list of available /dev/input/event* devices.

    :return: List of InputDevice objects
    :rtype: list[InputDevice]
    """
    try:
        return [InputDevice(path) for path in list_devices()]
    except (OSError, FileNotFoundError) as ex:
        _logger.critical(f"Failed listing devices: {ex}")
        return []
    except Exception:
        _logger.exception("Unexpected error listing devices")
        return []
