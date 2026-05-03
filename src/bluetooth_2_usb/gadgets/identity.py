"""Host-visible USB identity for the managed Bluetooth-2-USB gadget."""

USB_GADGET_VENDOR_ID_LINUX_FOUNDATION = 0x1D6B
"""USB device descriptor idVendor: Linux Foundation VID used by gadget examples."""

USB_GADGET_PRODUCT_ID_MULTIFUNCTION_COMPOSITE = 0x0104
"""USB device descriptor idProduct for this multifunction composite gadget."""


def usb_configfs_hex_u16(value: int) -> str:
    """Format a 16-bit USB descriptor value for configfs descriptor attributes."""
    return f"0x{value:04x}"


def usb_udev_hex_u16(value: int) -> str:
    """Format a 16-bit USB descriptor value for udev attribute matching."""
    return f"{value:04x}"
