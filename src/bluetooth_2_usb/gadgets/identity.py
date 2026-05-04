"""Stable host-visible USB identity for the managed Bluetooth-2-USB gadget."""

USB_GADGET_VID_LINUX = 0x1D6B
"""USB device descriptor idVendor: Linux Foundation VID used by gadget examples."""

USB_GADGET_PID_COMBO = 0x0104
"""USB device descriptor idProduct for this multifunction composite gadget."""

USB_MANUFACTURER = "quaxalber"
"""Manufacturer string descriptor exposed to the host."""

USB_PRODUCT_NAME = "USB Combo Device"
"""Product string descriptor exposed to the host and used by loopback discovery."""

USB_SERIAL_NUMBER = "213374badcafe"
"""Stable host-visible serial string used for host-side device identity."""


def usb_configfs_hex_u16(value: int) -> str:
    """Format a 16-bit USB descriptor value for configfs descriptor attributes."""
    return f"0x{value:04x}"


def usb_udev_hex_u16(value: int) -> str:
    """Format a 16-bit USB descriptor value for udev attribute matching."""
    return f"{value:04x}"
