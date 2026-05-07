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
        self._type = self._determine_filter_type()

    def __str__(self) -> str:
        return f'{self.type.value} "{self.value}"'

    @property
    def type(self) -> DeviceFilterType:
        return self._type

    @property
    def value(self) -> str:
        return self._value

    def _determine_filter_type(self) -> DeviceFilterType:
        if self.value.startswith("/"):
            return DeviceFilterType.PATH
        if re.match(r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$", self.value):
            return DeviceFilterType.MAC
        return DeviceFilterType.TEXT

    def _normalized_value(self) -> str:
        if self.type is DeviceFilterType.PATH:
            return self.value
        if self.type is DeviceFilterType.MAC:
            return _normalize_mac(self.value)
        return _normalize_text(self.value)

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
            return self.value == path
        if self.type is DeviceFilterType.MAC:
            device_uniq = _normalize_mac(uniq)
            device_phys = _normalize_mac(phys).split("/", 1)[0]
            return self._normalized_value() in {device_uniq, device_phys}
        return self.value in {path, uniq, phys} or self._normalized_value() in _normalize_text(name)


def _normalize_mac(value: str) -> str:
    return value.lower().replace("-", ":")


def _normalize_text(value: str) -> str:
    return value.lower()


def parse_devices(raw_value: str) -> list[str]:
    devices = [device.strip() for device in raw_value.split(",") if device.strip()]
    if not devices:
        raise ValueError("devices must not be empty")
    return devices
