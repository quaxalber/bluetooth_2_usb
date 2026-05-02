from __future__ import annotations

import re
from enum import StrEnum

from ..evdev.types import InputDevice


class DeviceIdentifierType(StrEnum):
    PATH = "path"
    MAC = "mac"
    NAME = "name"


class DeviceIdentifier:
    """
    Identifies an input device by path (/dev/input/eventX), MAC address,
    or a substring of the device name.
    """

    def __init__(self, device_identifier: str) -> None:
        """
        :param device_identifier: Path, MAC, or name fragment
        """
        self._value = device_identifier.strip()
        if not self._value:
            raise ValueError("device_identifier must not be blank")
        self._kind = self._determine_identifier_kind()
        self._normalized_value = self._normalize_identifier()

    def __str__(self) -> str:
        return f'{self.type.value} "{self._value}"'

    @property
    def type(self) -> DeviceIdentifierType:
        return self._kind

    def _determine_identifier_kind(self) -> DeviceIdentifierType:
        if re.match(r"^/dev/input/event\d+$", self._value):
            return DeviceIdentifierType.PATH
        if re.match(r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$", self._value):
            return DeviceIdentifierType.MAC
        return DeviceIdentifierType.NAME

    def _normalize_identifier(self) -> str:
        if self.type is DeviceIdentifierType.PATH:
            return self._value
        if self.type is DeviceIdentifierType.MAC:
            return self._value.lower().replace("-", ":")
        return self._value.lower()

    def matches(self, device: InputDevice) -> bool:
        """
        Check whether this identifier matches the given evdev InputDevice.

        :param device: An evdev InputDevice to compare
        :return: True if matched, False otherwise
        :rtype: bool
        """
        if self.type is DeviceIdentifierType.PATH:
            return self._value == device.path
        if self.type is DeviceIdentifierType.MAC:
            device_uniq = (device.uniq or "").lower().replace("-", ":")
            return self._normalized_value == device_uniq
        return self._normalized_value in (device.name or "").lower()
