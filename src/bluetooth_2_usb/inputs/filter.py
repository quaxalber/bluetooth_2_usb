from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from ..evdev.types import InputDevice


class DeviceFilterType(StrEnum):
    PATH = "path"
    MAC = "mac"
    TEXT = "text"


class DeviceFilter:
    """
    Matches an input device by path, uniq, phys, MAC address, or name fragment.
    """

    def __init__(self, device_filter: str) -> None:
        """
        :param device_filter: Path, uniq, phys, MAC, or name fragment
        """
        self._value = device_filter.strip()
        if not self._value:
            raise ValueError("device_filter must not be blank")
        self._kind = self._determine_filter_kind()
        self._normalized_value = self._normalize_filter()

    def __str__(self) -> str:
        return f'{self.type.value} "{self._value}"'

    @property
    def type(self) -> DeviceFilterType:
        return self._kind

    def _determine_filter_kind(self) -> DeviceFilterType:
        if self._value.startswith("/"):
            return DeviceFilterType.PATH
        if re.match(r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$", self._value):
            return DeviceFilterType.MAC
        return DeviceFilterType.TEXT

    def _normalize_filter(self) -> str:
        if self.type is DeviceFilterType.PATH:
            return self._value
        if self.type is DeviceFilterType.MAC:
            return self._value.lower().replace("-", ":")
        return self._value.lower()

    def matches(self, device: InputDevice | Any) -> bool:
        """
        Check whether this filter matches the given input-device-like object.

        :param device: An evdev InputDevice or compatible object to compare
        :return: True if matched, False otherwise
        :rtype: bool
        """
        path = getattr(device, "path", "")
        uniq = getattr(device, "uniq", "") or ""
        phys = getattr(device, "phys", "") or ""
        name = getattr(device, "name", "") or ""

        if self.type is DeviceFilterType.PATH:
            return self._value == path
        if self.type is DeviceFilterType.MAC:
            device_uniq = uniq.lower().replace("-", ":")
            device_phys = phys.lower().replace("-", ":")
            return self._normalized_value in {device_uniq, device_phys}
        return (
            self._value == path or self._value == uniq or self._value == phys or self._normalized_value in name.lower()
        )


def parse_devices(raw_value: str) -> list[str]:
    devices = [device.strip() for device in raw_value.split(",") if device.strip()]
    if not devices:
        raise ValueError("devices must not be empty")
    return devices
