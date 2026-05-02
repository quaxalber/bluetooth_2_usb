from __future__ import annotations

KEYBOARD_IN_REPORT_LENGTH = 8
KEYBOARD_OUT_REPORT_LENGTH = 1
MOUSE_IN_REPORT_LENGTH = 7
# Keep the HID input report at 7 bytes, but make the configfs request size
# larger so each write is a short packet. On Pi dwc2 this avoids an extra empty
# interrupt-IN completion after every full-size mouse report.
MOUSE_CONFIGFS_REPORT_LENGTH = 8
CONSUMER_IN_REPORT_LENGTH = 2
CONSUMER_OUT_REPORT_LENGTH = 0

# Keep descriptor bytes in HID item rows to match the Adafruit HID descriptor
# style and make item boundaries easier to review.
# fmt: off
DEFAULT_KEYBOARD_DESCRIPTOR = bytes(
    (
        0x05, 0x01,  # Usage Page (Generic Desktop)
        0x09, 0x06,  # Usage (Keyboard)
        0xA1, 0x01,  # Collection (Application)
          0x05, 0x07,  # Usage Page (Keyboard)
          0x19, 0xE0,  # Usage Minimum (Keyboard LeftControl)
          0x29, 0xE7,  # Usage Maximum (Keyboard Right GUI)
          0x15, 0x00,  # Logical Minimum (0)
          0x25, 0x01,  # Logical Maximum (1)
          0x75, 0x01,  # Report Size (1)
          0x95, 0x08,  # Report Count (8)
          0x81, 0x02,  # Input (Data, Variable, Absolute)
          0x95, 0x01,  # Report Count (1)
          0x75, 0x08,  # Report Size (8)
          0x81, 0x01,  # Input (Constant)
          0x95, 0x03,  # Report Count (3)
          0x75, 0x01,  # Report Size (1)
          0x05, 0x08,  # Usage Page (LEDs)
          0x19, 0x01,  # Usage Minimum (Num Lock)
          0x29, 0x03,  # Usage Maximum (Scroll Lock)
          0x91, 0x02,  # Output (Data, Variable, Absolute)
          0x95, 0x05,  # Report Count (5)
          0x75, 0x01,  # Report Size (1)
          0x91, 0x01,  # Output (Constant)
          0x95, 0x06,  # Report Count (6)
          0x75, 0x08,  # Report Size (8)
          0x15, 0x00,  # Logical Minimum (0)
          0x26, 0xFF,  # Logical Maximum (255)
          0x00, 0x05,  # Logical Maximum continuation, Usage Page
          0x07, 0x19,  # Usage Page continuation, Usage Minimum
          0x00, 0x2A,  # Usage Minimum continuation, Usage Maximum
          0xFF, 0x00,  # Usage Maximum continuation
          0x81, 0x00,  # Input (Data, Array)
        0xC0,  # End Collection
    )
)

DEFAULT_MOUSE_DESCRIPTOR = bytes(
    (
        0x05, 0x01,  # Usage Page (Generic Desktop)
        0x09, 0x02,  # Usage (Mouse)
        0xA1, 0x01,  # Collection (Application)
          0x09, 0x01,  # Usage (Pointer)
          0xA1, 0x00,  # Collection (Physical)
            0x05, 0x09,  # Usage Page (Button)
            0x19, 0x01,  # Usage Minimum (Button 1)
            0x29, 0x08,  # Usage Maximum (Button 8)
            0x15, 0x00,  # Logical Minimum (0)
            0x25, 0x01,  # Logical Maximum (1)
            0x95, 0x08,  # Report Count (8)
            0x75, 0x01,  # Report Size (1)
            0x81, 0x02,  # Input (Data, Variable, Absolute)
            0x05, 0x01,  # Usage Page (Generic Desktop)
            0x09, 0x30,  # Usage (X)
            0x09, 0x31,  # Usage (Y)
            0x16, 0x01,  # Logical Minimum (-32767)
            0x80, 0x26,  # Logical Minimum continuation, Logical Maximum
            0xFF, 0x7F,  # Logical Maximum continuation (32767)
            0x75, 0x10,  # Report Size (16)
            0x95, 0x02,  # Report Count (2)
            0x81, 0x06,  # Input (Data, Variable, Relative)
            0xA1, 0x02,  # Collection (Logical)
              0x09, 0x48,  # Usage (Resolution Multiplier)
              0x15, 0x00,  # Logical Minimum (0)
              0x25, 0x01,  # Logical Maximum (1)
              0x35, 0x01,  # Physical Minimum (1)
              0x45, 0x08,  # Physical Maximum (8)
              0x75, 0x02,  # Report Size (2)
              0x95, 0x01,  # Report Count (1)
              0xB1, 0x02,  # Feature (Data, Variable, Absolute)
              0x75, 0x06,  # Report Size (6)
              0x95, 0x01,  # Report Count (1)
              0xB1, 0x01,  # Feature (Constant)
              0x09, 0x38,  # Usage (Wheel)
              0x15, 0x81,  # Logical Minimum (-127)
              0x25, 0x7F,  # Logical Maximum (127)
              0x35, 0x00,  # Physical Minimum (0)
              0x45, 0x00,  # Physical Maximum (0)
              0x75, 0x08,  # Report Size (8)
              0x95, 0x01,  # Report Count (1)
              0x81, 0x06,  # Input (Data, Variable, Relative)
            0xC0,  # End Collection
            0x05, 0x0C,  # Usage Page (Consumer)
            0xA1, 0x02,  # Collection (Logical)
              0x05, 0x01,  # Usage Page (Generic Desktop)
              0x09, 0x48,  # Usage (Resolution Multiplier)
              0x15, 0x00,  # Logical Minimum (0)
              0x25, 0x01,  # Logical Maximum (1)
              0x35, 0x01,  # Physical Minimum (1)
              0x45, 0x08,  # Physical Maximum (8)
              0x75, 0x02,  # Report Size (2)
              0x95, 0x01,  # Report Count (1)
              0xB1, 0x02,  # Feature (Data, Variable, Absolute)
              0x75, 0x06,  # Report Size (6)
              0x95, 0x01,  # Report Count (1)
              0xB1, 0x01,  # Feature (Constant)
              0x05, 0x0C,  # Usage Page (Consumer)
              0x0A, 0x38, 0x02,  # Usage (AC Pan)
              0x15, 0x81,  # Logical Minimum (-127)
              0x25, 0x7F,  # Logical Maximum (127)
              0x35, 0x00,  # Physical Minimum (0)
              0x45, 0x00,  # Physical Maximum (0)
              0x75, 0x08,  # Report Size (8)
              0x95, 0x01,  # Report Count (1)
              0x81, 0x06,  # Input (Data, Variable, Relative)
            0xC0,  # End Collection
          0xC0,  # End Collection
        0xC0,  # End Collection
    )
)
# fmt: on
