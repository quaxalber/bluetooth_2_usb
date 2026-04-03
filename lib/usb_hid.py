# SPDX-FileCopyrightText: 2021 Melissa LeBlanc-Williams for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""
`usb_hid` - support for usb hid devices via usb_gadget driver
===========================================================
See `CircuitPython:usb_hid` in CircuitPython for more details.
For now using report ids in the descriptor

# regarding usb_gadget see https://www.kernel.org/doc/Documentation/usb/gadget_configfs.txt
* Author(s): Björn Bösel
"""

import asyncio
import time
from typing import Sequence
from pathlib import Path
import os, stat
import atexit
import sys

from evdev import InputDevice

from lib.constants import Keycode
import lib.logger

logger = lib.logger.get_logger()

for module in ["dwc2", "libcomposite"]:
    if Path("/proc/modules").read_text(encoding="utf-8").find(module) == -1:
        raise Exception(  # pylint: disable=broad-exception-raised
            "%s module not present in your kernel. did you insmod it?" % module
        )
this = sys.modules[__name__]

this.gadget_root = "/sys/kernel/config/usb_gadget/adafruit-blinka"
this.boot_device = 0
this.devices = []


class GadgetDevice:
    """
    HID Device specification: see
    https://github.com/adafruit/circuitpython/blob/main/shared-bindings/usb_hid/Device.c
    """

    def __init__(
        self,
        *,
        descriptor: bytes,
        usage_page: int,
        usage: int,
        report_ids: Sequence[int],
        in_report_lengths: Sequence[int],
        out_report_lengths: Sequence[int],
        name: str = "Gadget",
    ) -> None:
        self.out_report_lengths = out_report_lengths
        self.in_report_lengths = in_report_lengths
        self.report_ids = report_ids
        self.usage = usage
        self.usage_page = usage_page
        self.descriptor = descriptor
        self._last_received_report = None
        self._name = name
        self._path = None

    def __repr__(self):
        return f"{self._name} ({self})"

    def __str__(self):
        return self._path

    def send_report(self, report: bytearray, report_id: int = None):
        """Send an HID report. If the device descriptor specifies zero or one report id's,
        you can supply `None` (the default) as the value of ``report_id``.
        Otherwise you must specify which report id to use when sending the report.
        """
        report_id = report_id or self.report_ids[0]
        device_path = self.get_device_path(report_id)
        with open(device_path, "rb+") as fd:
            if report_id > 0:
                report = bytearray(report_id.to_bytes(1, "big")) + report
            fd.write(report)

    @property
    def last_received_report(
        self,
    ) -> bytes:
        """The HID OUT report as a `bytes` (read-only). `None` if nothing received.
        Same as `get_last_received_report()` with no argument.

        Deprecated: will be removed in CircutPython 8.0.0. Use `get_last_received_report()` instead.
        """
        return self.get_last_received_report()

    def get_last_received_report(self, report_id=None) -> bytes:
        """Get the last received HID OUT or feature report for the given report ID.
        The report ID may be omitted if there is no report ID, or only one report ID.
        Return `None` if nothing received.
        """
        device_path = self.get_device_path(report_id or self.report_ids[0])
        with open(device_path, "rb+") as fd:
            os.set_blocking(fd.fileno(), False)
            report = fd.read(self.out_report_lengths[0])
            if report is not None:
                self._last_received_report = report
        return self._last_received_report

    def get_device_path(self, report_id=None):
        """
        translates the /dev/hidg device from the report id
        """
        device = (
            Path(
                "%s/functions/hid.usb%s/dev"
                % (this.gadget_root, report_id or self.report_ids[0])
            )
            .read_text(encoding="utf-8")
            .strip()
            .split(":")[1]
        )
        device_path = "/dev/hidg%s" % device
        return device_path

    KEYBOARD = None
    BOOT_KEYBOARD = None
    MOUSE = None
    BOOT_MOUSE = None
    CONSUMER_CONTROL = None


GadgetDevice.KEYBOARD = GadgetDevice(
    descriptor=bytes(
        (
            0x05,
            0x01,  # usage page (generic desktop ctrls)
            0x09,
            0x06,  # usage (keyboard)
            0xA1,
            0x01,  # collection (application)
            0x85,
            0x01,  # Report ID (1)
            0x05,
            0x07,  # usage page (kbrd/keypad)
            0x19,
            0xE0,  # usage minimum (0xe0)
            0x29,
            0xE7,  # usage maximum (0xe7)
            0x15,
            0x00,  # logical minimum (0)
            0x25,
            0x01,  # logical maximum (1)
            0x75,
            0x01,  # report size (1)
            0x95,
            0x08,  # report count (8)
            0x81,
            0x02,  # input (data,var,abs,no wrap,linear,preferred state,no null position)
            0x95,
            0x01,  # report count (1)
            0x75,
            0x08,  # report size (8)
            0x81,
            0x01,  # input (const,array,abs,no wrap,linear,preferred state,no null position)
            0x95,
            0x03,  # report count (3)
            0x75,
            0x01,  # report size (1)
            0x05,
            0x08,  # usage page (leds)
            0x19,
            0x01,  # usage minimum (num lock)
            0x29,
            0x05,  # usage maximum (kana)
            0x91,
            0x02,  # output
            # (data,var,abs,no wrap,linear,preferred state,no null position,non-volatile)
            0x95,
            0x01,  # report count (1)
            0x75,
            0x05,  # report size (5)
            0x91,
            0x01,  # output
            # (const,array,abs,no wrap,linear,preferred state,no null position,non-volatile)
            0x95,
            0x06,  # report count (6)
            0x75,
            0x08,  # report size (8)
            0x15,
            0x00,  # logical minimum (0)
            0x26,
            0xFF,
            0x00,  # logical maximum (255)
            0x05,
            0x07,  # usage page (kbrd/keypad)
            0x19,
            0x00,  # usage minimum (0x00)
            0x2A,
            0xFF,
            0x00,  # usage maximum (0xff)
            0x81,
            0x00,  # input (data,array,abs,no wrap,linear,preferred state,no null position)
            0xC0,  # end collection
        )
    ),
    usage_page=0x1,
    usage=0x6,
    report_ids=[0x1],
    in_report_lengths=[8],
    out_report_lengths=[1],
    name="Keyboard gadget",
)
GadgetDevice.MOUSE = GadgetDevice(
    descriptor=bytes(
        (
            0x05,
            0x01,  # Usage Page (Generic Desktop Ctrls)
            0x09,
            0x02,  # Usage (Mouse)
            0xA1,
            0x01,  # Collection (Application)
            0x85,
            0x02,  # Report ID (2)
            0x09,
            0x01,  # Usage (Pointer)
            0xA1,
            0x00,  # Collection (Physical)
            0x05,
            0x09,  # Usage Page (Button)
            0x19,
            0x01,  # Usage Minimum (0x01)
            0x29,
            0x05,  # Usage Maximum (0x05)
            0x15,
            0x00,  # Logical Minimum (0)
            0x25,
            0x01,  # Logical Maximum (1)
            0x95,
            0x05,  # Report Count (5)
            0x75,
            0x01,  # Report Size (1)
            0x81,
            0x02,  # Input (Data,Var,Abs,No Wrap,Linear,Preferred State,No Null Position)
            0x95,
            0x01,  # Report Count (1)
            0x75,
            0x03,  # Report Size (3)
            0x81,
            0x01,  # Input (Const,Array,Abs,No Wrap,Linear,Preferred State,No Null Position)
            0x05,
            0x01,  # Usage Page (Generic Desktop Ctrls)
            0x09,
            0x30,  # Usage (X)
            0x09,
            0x31,  # Usage (Y)
            0x15,
            0x81,  # Logical Minimum (-127)
            0x25,
            0x7F,  # Logical Maximum (127)
            0x75,
            0x08,  # Report Size (8)
            0x95,
            0x02,  # Report Count (2)
            0x81,
            0x06,  # Input (Data,Var,Rel,No Wrap,Linear,Preferred State,No Null Position)
            0x09,
            0x38,  # Usage (Wheel)
            0x15,
            0x81,  # Logical Minimum (-127)
            0x25,
            0x7F,  # Logical Maximum (127)
            0x75,
            0x08,  # Report Size (8)
            0x95,
            0x01,  # Report Count (1)
            0x81,
            0x06,  # Input (Data,Var,Rel,No Wrap,Linear,Preferred State,No Null Position)
            0xC0,  # End Collection
            0xC0,  # End Collection
        )
    ),
    usage_page=0x1,
    usage=0x02,
    report_ids=[0x02],
    in_report_lengths=[4],
    out_report_lengths=[0],
    name="Mouse gadget",
)

GadgetDevice.CONSUMER_CONTROL = GadgetDevice(
    descriptor=bytes(
        (
            0x05,
            0x0C,  # Usage Page (Consumer)
            0x09,
            0x01,  # Usage (Consumer Control)
            0xA1,
            0x01,  # Collection (Application)
            0x85,
            0x03,  # Report ID (3)
            0x75,
            0x10,  # Report Size (16)
            0x95,
            0x01,  # Report Count (1)
            0x15,
            0x01,  # Logical Minimum (1)
            0x26,
            0x8C,
            0x02,  # Logical Maximum (652)
            0x19,
            0x01,  # Usage Minimum (Consumer Control)
            0x2A,
            0x8C,
            0x02,  # Usage Maximum (AC Send)
            0x81,
            0x00,  # Input (Data,Array,Abs,No Wrap,Linear,Preferred State,No Null Position)
            0xC0,  # End Collection
        )
    ),
    usage_page=0x0C,
    usage=0x01,
    report_ids=[3],
    in_report_lengths=[2],
    out_report_lengths=[0],
    name="Consumer control gadget",
)

GadgetDevice.BOOT_KEYBOARD = GadgetDevice(
    descriptor=bytes(
        (
            0x05,
            0x01,  # usage page (generic desktop ctrls)
            0x09,
            0x06,  # usage (keyboard)
            0xA1,
            0x01,  # collection (application)
            0x05,
            0x07,  # usage page (kbrd/keypad)
            0x19,
            0xE0,  # usage minimum (0xe0)
            0x29,
            0xE7,  # usage maximum (0xe7)
            0x15,
            0x00,  # logical minimum (0)
            0x25,
            0x01,  # logical maximum (1)
            0x75,
            0x01,  # report size (1)
            0x95,
            0x08,  # report count (8)
            0x81,
            0x02,  # input (data,var,abs,no wrap,linear,preferred state,no null position)
            0x95,
            0x01,  # report count (1)
            0x75,
            0x08,  # report size (8)
            0x81,
            0x01,  # input (const,array,abs,no wrap,linear,preferred state,no null position)
            0x95,
            0x03,  # report count (3)
            0x75,
            0x01,  # report size (1)
            0x05,
            0x08,  # usage page (leds)
            0x19,
            0x01,  # usage minimum (num lock)
            0x29,
            0x05,  # usage maximum (kana)
            0x91,
            0x02,  # output
            # (data,var,abs,no wrap,linear,preferred state,no null position,non-volatile)
            0x95,
            0x01,  # report count (1)
            0x75,
            0x05,  # report size (5)
            0x91,
            0x01,  # output
            # (const,array,abs,no wrap,linear,preferred state,no null position,non-volatile)
            0x95,
            0x06,  # report count (6)
            0x75,
            0x08,  # report size (8)
            0x15,
            0x00,  # logical minimum (0)
            0x26,
            0xFF,
            0x00,  # logical maximum (255)
            0x05,
            0x07,  # usage page (kbrd/keypad)
            0x19,
            0x00,  # usage minimum (0x00)
            0x2A,
            0xFF,
            0x00,  # usage maximum (0xff)
            0x81,
            0x00,  # input (data,array,abs,no wrap,linear,preferred state,no null position)
            0xC0,  # end collection
        )
    ),
    usage_page=0x1,
    usage=0x6,
    report_ids=[0x0],
    in_report_lengths=[8],
    out_report_lengths=[1],
    name="Boot keyboard gadget",
)
GadgetDevice.BOOT_MOUSE = GadgetDevice(
    descriptor=bytes(
        (
            0x05,
            0x01,  # Usage Page (Generic Desktop Ctrls)
            0x09,
            0x02,  # Usage (Mouse)
            0xA1,
            0x01,  # Collection (Application)
            0x09,
            0x01,  # Usage (Pointer)
            0xA1,
            0x00,  # Collection (Physical)
            0x05,
            0x09,  # Usage Page (Button)
            0x19,
            0x01,  # Usage Minimum (0x01)
            0x29,
            0x05,  # Usage Maximum (0x05)
            0x15,
            0x00,  # Logical Minimum (0)
            0x25,
            0x01,  # Logical Maximum (1)
            0x95,
            0x05,  # Report Count (5)
            0x75,
            0x01,  # Report Size (1)
            0x81,
            0x02,  # Input (Data,Var,Abs,No Wrap,Linear,Preferred State,No Null Position)
            0x95,
            0x01,  # Report Count (1)
            0x75,
            0x03,  # Report Size (3)
            0x81,
            0x01,  # Input (Const,Array,Abs,No Wrap,Linear,Preferred State,No Null Position)
            0x05,
            0x01,  # Usage Page (Generic Desktop Ctrls)
            0x09,
            0x30,  # Usage (X)
            0x09,
            0x31,  # Usage (Y)
            0x15,
            0x81,  # Logical Minimum (-127)
            0x25,
            0x7F,  # Logical Maximum (127)
            0x75,
            0x08,  # Report Size (8)
            0x95,
            0x02,  # Report Count (2)
            0x81,
            0x06,  # Input (Data,Var,Rel,No Wrap,Linear,Preferred State,No Null Position)
            0x09,
            0x38,  # Usage (Wheel)
            0x15,
            0x81,  # Logical Minimum (-127)
            0x25,
            0x7F,  # Logical Maximum (127)
            0x75,
            0x08,  # Report Size (8)
            0x95,
            0x01,  # Report Count (1)
            0x81,
            0x06,  # Input (Data,Var,Rel,No Wrap,Linear,Preferred State,No Null Position)
            0xC0,  # End Collection
            0xC0,  # End Collection
        )
    ),
    usage_page=0x1,
    usage=0x02,
    report_ids=[0],
    in_report_lengths=[4],
    out_report_lengths=[0],
    name="Boot mouse gadget",
)


def disable() -> None:
    """Do not present any USB HID devices to the host computer.
    Can be called in ``boot.py``, before USB is connected.
    The HID composite device is normally enabled by default,
    but on some boards with limited endpoints, including STM32F4,
    it is disabled by default. You must turn off another USB device such
    as `usb_cdc` or `storage` to free up endpoints for use by `usb_hid`.
    """
    try:
        Path("%s/UDC" % this.gadget_root).write_text("", encoding="utf-8")
    except FileNotFoundError:
        pass

    for symlink in Path(this.gadget_root).glob("configs/**/hid.usb*"):
        symlink.unlink()

    for strings_file in Path(this.gadget_root).rglob("configs/*/strings/*/*"):
        if strings_file.is_dir():
            strings_file.rmdir()

    for strings_file in Path(this.gadget_root).rglob("configs/*/strings/*"):
        if strings_file.is_dir():
            strings_file.rmdir()
    for config_dir in Path(this.gadget_root).rglob("configs/*"):
        if config_dir.is_dir():
            config_dir.rmdir()
    for function_dir in Path(this.gadget_root).rglob("functions/*"):
        if function_dir.is_dir():
            function_dir.rmdir()
    for strings_file in Path(this.gadget_root).rglob("strings/*/*"):
        if strings_file.is_dir():
            strings_file.rmdir()
    for strings_file in Path(this.gadget_root).rglob("strings/*"):
        if strings_file.is_dir():
            strings_file.rmdir()
    try:
        Path(this.gadget_root).rmdir()
    except FileNotFoundError:
        pass
    this.devices = []


atexit.register(disable)


def enable(requested_devices: Sequence[GadgetDevice], boot_device: int = 0) -> None:
    """Specify which USB HID devices that will be available.
    Can be called in ``boot.py``, before USB is connected.

    :param Sequence devices: `Device` objects.
      If `devices` is empty, HID is disabled. The order of the ``Devices``
      may matter to the host. For instance, for MacOS, put the mouse device
      before any Gamepad or Digitizer HID device or else it will not work.
    :param int boot_device: If non-zero, inform the host that support for a
      a boot HID device is available.
      If ``boot_device=1``, a boot keyboard is available.
      If ``boot_device=2``, a boot mouse is available. No other values are allowed.
      See below.

    If you enable too many devices at once, you will run out of USB endpoints.
    The number of available endpoints varies by microcontroller.
    CircuitPython will go into safe mode after running ``boot.py`` to inform you if
    not enough endpoints are available.

    **Boot Devices**

    Boot devices implement a fixed, predefined report descriptor, defined in
    https://www.usb.org/sites/default/files/hid1_12.pdf, Appendix B. A USB host
    can request to use the boot device if the USB device says it is available.
    Usually only a BIOS or other kind of limited-functionality
    host needs boot keyboard support.

    For example, to make a boot keyboard available, you can use this code::

      usb_hid.enable((Device.KEYBOARD), boot_device=1)  # 1 for a keyboard

    If the host requests the boot keyboard, the report descriptor provided by `Device.KEYBOARD`
    will be ignored, and the predefined report descriptor will be used.
    But if the host does not request the boot keyboard,
    the descriptor provided by `Device.KEYBOARD` will be used.

    The HID boot device must usually be the first or only device presented by CircuitPython.
    The HID device will be USB interface number 0.
    To make sure it is the first device, disable other USB devices, including CDC and MSC
    (CIRCUITPY).
    If you specify a non-zero ``boot_device``, and it is not the first device, CircuitPython
    will enter safe mode to report this error.
    """
    this.boot_device = boot_device

    if len(requested_devices) == 0:
        disable()
        return

    if boot_device == 1:
        requested_devices = [GadgetDevice.BOOT_KEYBOARD]
    if boot_device == 2:
        requested_devices = [GadgetDevice.BOOT_MOUSE]

    # '''
    # 1. Creating the gadgets
    # -----------------------
    #
    # For each gadget to be created its corresponding directory must be created::
    #
    #     $ mkdir $CONFIGFS_HOME/usb_gadget/<gadget name>
    #
    # e.g.::
    #
    #     $ mkdir $CONFIGFS_HOME/usb_gadget/g1
    #
    #     ...
    #     ...
    #     ...
    #
    #     $ cd $CONFIGFS_HOME/usb_gadget/g1
    #
    # Each gadget needs to have its vendor id <VID> and product id <PID> specified::
    #
    #     $ echo <VID> > idVendor
    #     $ echo <PID> > idProduct
    #
    # A gadget also needs its serial number, manufacturer and product strings.
    # In order to have a place to store them, a strings subdirectory must be created
    # for each language, e.g.::
    #
    #     $ mkdir strings/0x409
    #
    # Then the strings can be specified::
    #
    #     $ echo <serial number> > strings/0x409/serialnumber
    #     $ echo <manufacturer> > strings/0x409/manufacturer
    #     $ echo <product> > strings/0x409/product
    # '''
    Path("%s/functions" % this.gadget_root).mkdir(parents=True, exist_ok=True)
    Path("%s/configs" % this.gadget_root).mkdir(parents=True, exist_ok=True)
    Path("%s/bcdDevice" % this.gadget_root).write_text(
        "%s" % 1, encoding="utf-8"
    )  # Version 1.0.0
    Path("%s/bcdUSB" % this.gadget_root).write_text(
        "%s" % 0x0200, encoding="utf-8"
    )  # USB 2.0
    Path("%s/bDeviceClass" % this.gadget_root).write_text(
        "%s" % 0x00, encoding="utf-8"
    )  # multipurpose i guess?
    Path("%s/bDeviceProtocol" % this.gadget_root).write_text(
        "%s" % 0x00, encoding="utf-8"
    )
    Path("%s/bDeviceSubClass" % this.gadget_root).write_text(
        "%s" % 0x00, encoding="utf-8"
    )
    Path("%s/bMaxPacketSize0" % this.gadget_root).write_text(
        "%s" % 0x08, encoding="utf-8"
    )
    Path("%s/idProduct" % this.gadget_root).write_text(
        "%s" % 0x0104, encoding="utf-8"
    )  # Multifunction Composite Gadget
    Path("%s/idVendor" % this.gadget_root).write_text(
        "%s" % 0x1D6B, encoding="utf-8"
    )  # Linux Foundation
    Path("%s/strings/0x409" % this.gadget_root).mkdir(parents=True, exist_ok=True)
    Path("%s/strings/0x409/serialnumber" % this.gadget_root).write_text(
        "213374badcafe", encoding="utf-8"
    )
    Path("%s/strings/0x409/manufacturer" % this.gadget_root).write_text(
        "quaxalber", encoding="utf-8"
    )
    Path("%s/strings/0x409/product" % this.gadget_root).write_text(
        "USB Combo Device", encoding="utf-8"
    )
    # '''
    # 2. Creating the configurations
    # ------------------------------
    #
    # Each gadget will consist of a number of configurations, their corresponding
    # directories must be created:
    #
    # $ mkdir configs/<name>.<number>
    #
    # where <name> can be any string which is legal in a filesystem and the
    # <number> is the configuration's number, e.g.::
    #
    #     $ mkdir configs/c.1
    #
    #     ...
    #     ...
    #     ...
    #
    # Each configuration also needs its strings, so a subdirectory must be created
    # for each language, e.g.::
    #
    #     $ mkdir configs/c.1/strings/0x409
    #
    # Then the configuration string can be specified::
    #
    #     $ echo <configuration> > configs/c.1/strings/0x409/configuration
    #
    # Some attributes can also be set for a configuration, e.g.::
    #
    #     $ echo 120 > configs/c.1/MaxPower
    #     '''

    for device in requested_devices:
        config_root = "%s/configs/c.1" % this.gadget_root
        Path("%s/" % config_root).mkdir(parents=True, exist_ok=True)
        Path("%s/strings/0x409" % config_root).mkdir(parents=True, exist_ok=True)
        Path("%s/strings/0x409/configuration" % config_root).write_text(
            "Config 1: ECM network", encoding="utf-8"
        )
        Path("%s/MaxPower" % config_root).write_text("250", encoding="utf-8")
        Path("%s/bmAttributes" % config_root).write_text("%s" % 0x080, encoding="utf-8")
        this.devices.append(device)
        # '''
        # 3. Creating the functions
        # -------------------------
        #
        # The gadget will provide some functions, for each function its corresponding
        # directory must be created::
        #
        #     $ mkdir functions/<name>.<instance name>
        #
        # where <name> corresponds to one of allowed function names and instance name
        # is an arbitrary string allowed in a filesystem, e.g.::
        #
        #   $ mkdir functions/ncm.usb0 # usb_f_ncm.ko gets loaded with request_module()
        #
        #   ...
        #   ...
        #   ...
        #
        # Each function provides its specific set of attributes, with either read-only
        # or read-write access. Where applicable they need to be written to as
        # appropriate.
        # Please refer to Documentation/ABI/*/configfs-usb-gadget* for more information.  '''
        for report_index, report_id in enumerate(device.report_ids):
            function_root = "%s/functions/hid.usb%s" % (this.gadget_root, report_id)
            try:
                Path("%s/" % function_root).mkdir(parents=True)
            except FileExistsError:
                continue
            Path("%s/protocol" % function_root).write_text(
                "%s" % report_id, encoding="utf-8"
            )
            Path("%s/report_length" % function_root).write_text(
                "%s" % device.in_report_lengths[report_index], encoding="utf-8"
            )
            Path("%s/subclass" % function_root).write_text("%s" % 1, encoding="utf-8")
            Path("%s/report_desc" % function_root).write_bytes(device.descriptor)
            # '''
            # 4. Associating the functions with their configurations
            # ------------------------------------------------------
            #
            # At this moment a number of gadgets is created, each of which has a number of
            # configurations specified and a number of functions available. What remains
            # is specifying which function is available in which configuration (the same
            # function can be used in multiple configurations). This is achieved with
            # creating symbolic links::
            #
            #     $ ln -s functions/<name>.<instance name> configs/<name>.<number>
            #
            # e.g.::
            #
            #     $ ln -s functions/ncm.usb0 configs/c.1  '''
            try:
                Path("%s/hid.usb%s" % (config_root, report_id)).symlink_to(
                    function_root
                )
            except FileNotFoundError:
                pass

    # ''' 5. Enabling the gadget
    # ----------------------
    # Such a gadget must be finally enabled so that the USB host can enumerate it.
    #
    # In order to enable the gadget it must be bound to a UDC (USB Device
    # Controller)::
    #
    #     $ echo <udc name> > UDC
    #
    # where <udc name> is one of those found in /sys/class/udc/*
    # e.g.::
    #
    # $ echo s3c-hsotg > UDC  '''
    udc = next(Path("/sys/class/udc/").glob("*"))
    Path("%s/UDC" % this.gadget_root).write_text("%s" % udc.name, encoding="utf-8")

    for device in requested_devices:
        device._path = device.get_device_path()


# SPDX-FileCopyrightText: 2017 Scott Shawcroft for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
`adafruit_hid`
====================================================

This driver simulates USB HID devices.

* Author(s): Scott Shawcroft, Dan Halbert

Implementation Notes
--------------------
**Software and Dependencies:**
* Adafruit CircuitPython firmware for the supported boards:
  https://github.com/adafruit/circuitpython/releases
"""


def find_device(
    devices: Sequence[GadgetDevice], *, usage_page: int, usage: int
) -> GadgetDevice:
    """Search through the provided sequence of devices to find the one with the matching
    usage_page and usage."""
    if hasattr(devices, "send_report"):
        devices = [devices]  # type: ignore
    for device in devices:
        if (
            device.usage_page == usage_page
            and device.usage == usage
            and hasattr(device, "send_report")
        ):
            return device
    raise ValueError("Could not find matching HID device.")


# SPDX-FileCopyrightText: 2017 Dan Halbert for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
`adafruit_hid.keyboard.Keyboard`
====================================================

* Author(s): Scott Shawcroft, Dan Halbert
"""

_MAX_KEYPRESSES = 6


class KeyboardGadget:
    """Send HID keyboard reports."""

    LED_NUM_LOCK = 0x01
    """LED Usage ID for Num Lock"""
    LED_CAPS_LOCK = 0x02
    """LED Usage ID for Caps Lock"""
    LED_SCROLL_LOCK = 0x04
    """LED Usage ID for Scroll Lock"""
    LED_COMPOSE = 0x08
    """LED Usage ID for Compose"""

    # No more than _MAX_KEYPRESSES regular keys may be pressed at once.

    def __init__(self, devices: Sequence[GadgetDevice] = this.devices) -> None:
        """Create a Keyboard object that will send keyboard HID reports.

        Devices can be a sequence of devices that includes a keyboard device or a keyboard device
        itself. A device is any object that implements ``send_report()``, ``usage_page`` and
        ``usage``.
        """
        self._keyboard_device = find_device(devices, usage_page=0x1, usage=0x06)

        # Reuse this bytearray to send keyboard reports.
        self.report = bytearray(8)

        # report[0] modifiers
        # report[1] unused
        # report[2:8] regular key presses

        # View onto byte 0 in report.
        self.report_modifier = memoryview(self.report)[0:1]

        # List of regular keys currently pressed.
        # View onto bytes 2-7 in report.
        self.report_keys = memoryview(self.report)[2:]

        # No keyboard LEDs on.
        self._led_status = b"\x00"

        # Do a no-op to test if HID device is ready.
        # If not, wait a bit and try once more.
        try:
            self.release_all()
        except OSError:
            time.sleep(1)
            self.release_all()

    def __repr__(self):
        return repr(self._keyboard_device)

    def __str__(self):
        return str(self._keyboard_device)

    def press(self, *keycodes: int) -> None:
        """Send a report indicating that the given keys have been pressed.

        :param keycodes: Press these keycodes all at once.
        :raises ValueError: if more than six regular keys are pressed.

        Keycodes may be modifiers or regular keys.
        No more than six regular keys may be pressed simultaneously.

        Examples::

            from adafruit_hid.keycode import Keycode

            # Press ctrl-x.
            kbd.press(Keycode.LEFT_CONTROL, Keycode.X)

            # Or, more conveniently, use the CONTROL alias for LEFT_CONTROL:
            kbd.press(Keycode.CONTROL, Keycode.X)

            # Press a, b, c keys all at once.
            kbd.press(Keycode.A, Keycode.B, Keycode.C)
        """
        for keycode in keycodes:
            self._add_keycode_to_report(keycode)
        self._keyboard_device.send_report(self.report)

    def release(self, *keycodes: int) -> None:
        """Send a USB HID report indicating that the given keys have been released.

        :param keycodes: Release these keycodes all at once.

        If a keycode to be released was not pressed, it is ignored.

        Example::

            # release SHIFT key
            kbd.release(Keycode.SHIFT)
        """
        for keycode in keycodes:
            self._remove_keycode_from_report(keycode)
        self._keyboard_device.send_report(self.report)

    def release_all(self) -> None:
        """Release all pressed keys."""
        for i in range(8):
            self.report[i] = 0
        self._keyboard_device.send_report(self.report)

    def send(self, *keycodes: int) -> None:
        """Press the given keycodes and then release all pressed keys.

        :param keycodes: keycodes to send together
        """
        self.press(*keycodes)
        self.release_all()

    def _add_keycode_to_report(self, keycode: int) -> None:
        """Add a single keycode to the USB HID report."""
        modifier = Keycode.modifier_bit(keycode)
        if modifier:
            # Set bit for this modifier.
            self.report_modifier[0] |= modifier
        else:
            report_keys = self.report_keys
            # Don't press twice.
            for i in range(_MAX_KEYPRESSES):
                report_key = report_keys[i]
                if report_key == 0:
                    # Put keycode in first empty slot. Since the report_keys
                    # are compact and unique, this is not a repeated key
                    report_keys[i] = keycode
                    return
                if report_key == keycode:
                    # Already pressed.
                    return
            # All slots are filled. Shuffle down and reuse last slot
            for i in range(_MAX_KEYPRESSES - 1):
                report_keys[i] = report_keys[i + 1]
            report_keys[-1] = keycode

    def _remove_keycode_from_report(self, keycode: int) -> None:
        """Remove a single keycode from the report."""
        modifier = Keycode.modifier_bit(keycode)
        if modifier:
            # Turn off the bit for this modifier.
            self.report_modifier[0] &= ~modifier
        else:
            report_keys = self.report_keys
            # Clear the at most one matching slot and move remaining keys down
            j = 0
            for i in range(_MAX_KEYPRESSES):
                pressed = report_keys[i]
                if not pressed:
                    break  # Handled all used report slots
                if pressed == keycode:
                    continue  # Remove this entry
                if i != j:
                    report_keys[j] = report_keys[i]
                j += 1
            # Clear any remaining slots
            while j < _MAX_KEYPRESSES and report_keys[j]:
                report_keys[j] = 0
                j += 1

    @property
    def led_status(self) -> bytes:
        """Returns the last received report"""
        # get_last_received_report() returns None when nothing was received
        led_report = self._keyboard_device.get_last_received_report()
        if led_report is not None:
            self._led_status = led_report
        return self._led_status

    def led_on(self, led_code: int) -> bool:
        """Returns whether an LED is on based on the led code

        Examples::

            import usb_hid
            from adafruit_hid.keyboard import Keyboard
            from adafruit_hid.keycode import Keycode
            import time

            # Initialize Keyboard
            kbd = Keyboard(usb_hid.devices)

            # Press and release CapsLock.
            kbd.press(Keycode.CAPS_LOCK)
            time.sleep(.09)
            kbd.release(Keycode.CAPS_LOCK)

            # Check status of the LED_CAPS_LOCK
            print(kbd.led_on(Keyboard.LED_CAPS_LOCK))

        """
        return bool(self.led_status[0] & led_code)


# SPDX-FileCopyrightText: 2017 Dan Halbert for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
`adafruit_hid.mouse.Mouse`
====================================================

* Author(s): Dan Halbert
"""


class MouseGadget:
    """Send USB HID mouse reports."""

    def __init__(self, devices: Sequence[GadgetDevice] = this.devices):
        """Create a Mouse object that will send USB mouse HID reports.

        Devices can be a sequence of devices that includes a keyboard device or a keyboard device
        itself. A device is any object that implements ``send_report()``, ``usage_page`` and
        ``usage``.
        """
        self._mouse_device = find_device(devices, usage_page=0x1, usage=0x02)

        # Reuse this bytearray to send mouse reports.
        # report[0] buttons pressed (LEFT, MIDDLE, RIGHT)
        # report[1] x movement
        # report[2] y movement
        # report[3] wheel movement
        self.report = bytearray(4)

        # Do a no-op to test if HID device is ready.
        # If not, wait a bit and try once more.
        try:
            self._send_no_move()
        except OSError:
            time.sleep(1)
            self._send_no_move()

    def __repr__(self):
        return repr(self._mouse_device)

    def __str__(self):
        return str(self._mouse_device)

    def press(self, buttons: int) -> None:
        """Press the given mouse buttons.

        :param buttons: a bitwise-or'd combination of ``LEFT_BUTTON``,
            ``MIDDLE_BUTTON``, and ``RIGHT_BUTTON``.

        Examples::

            # Press the left button.
            m.press(Mouse.LEFT_BUTTON)

            # Press the left and right buttons simultaneously.
            m.press(Mouse.LEFT_BUTTON | Mouse.RIGHT_BUTTON)
        """
        self.report[0] |= buttons
        self._send_no_move()

    def release(self, buttons: int) -> None:
        """Release the given mouse buttons.

        :param buttons: a bitwise-or'd combination of ``LEFT_BUTTON``,
            ``MIDDLE_BUTTON``, and ``RIGHT_BUTTON``.
        """
        self.report[0] &= ~buttons
        self._send_no_move()

    def release_all(self) -> None:
        """Release all the mouse buttons."""
        self.report[0] = 0
        self._send_no_move()

    def click(self, buttons: int) -> None:
        """Press and release the given mouse buttons.

        :param buttons: a bitwise-or'd combination of ``LEFT_BUTTON``,
            ``MIDDLE_BUTTON``, and ``RIGHT_BUTTON``.

        Examples::

            # Click the left button.
            m.click(Mouse.LEFT_BUTTON)

            # Double-click the left button.
            m.click(Mouse.LEFT_BUTTON)
            m.click(Mouse.LEFT_BUTTON)
        """
        self.press(buttons)
        self.release(buttons)

    def move(self, x: int = 0, y: int = 0, wheel: int = 0) -> None:
        """Move the mouse and turn the wheel as directed.

        :param x: Move the mouse along the x axis. Negative is to the left, positive
            is to the right.
        :param y: Move the mouse along the y axis. Negative is upwards on the display,
            positive is downwards.
        :param wheel: Rotate the wheel this amount. Negative is toward the user, positive
            is away from the user. The scrolling effect depends on the host.

        Examples::

            # Move 100 to the left. Do not move up and down. Do not roll the scroll wheel.
            m.move(-100, 0, 0)
            # Same, with keyword arguments.
            m.move(x=-100)

            # Move diagonally to the upper right.
            m.move(50, 20)
            # Same.
            m.move(x=50, y=-20)

            # Roll the mouse wheel away from the user.
            m.move(wheel=1)
        """
        # Send multiple reports if necessary to move or scroll requested amounts.
        while x != 0 or y != 0 or wheel != 0:
            partial_x = self._limit(x)
            partial_y = self._limit(y)
            partial_wheel = self._limit(wheel)
            self.report[1] = partial_x & 0xFF
            self.report[2] = partial_y & 0xFF
            self.report[3] = partial_wheel & 0xFF
            self._mouse_device.send_report(self.report)
            x -= partial_x
            y -= partial_y
            wheel -= partial_wheel

    def _send_no_move(self) -> None:
        """Send a button-only report."""
        self.report[1] = 0
        self.report[2] = 0
        self.report[3] = 0
        self._mouse_device.send_report(self.report)

    @staticmethod
    def _limit(dist: int) -> int:
        return min(127, max(-127, dist))


class DummyGadget:
    def __init__(self, actual_gadget):
        self._actual_gadget = actual_gadget

    def __repr__(self):
        return f"Dummy {repr(self._actual_gadget)}"

    def __str__(self):
        return f"{self._actual_gadget} (Dummy)"

    def press(self, *keycodes: int) -> None:
        pass

    def release(self, *keycodes: int) -> None:
        pass

    def release_all(self) -> None:
        pass

    def send(self, *keycodes: int) -> None:
        pass

    @property
    def led_status(self) -> bytes:
        return b"\x00"

    def led_on(self, led_code: int) -> bool:
        return False

    def click(self, buttons: int) -> None:
        pass

    def move(self, x: int = 0, y: int = 0, wheel: int = 0) -> None:
        pass


class DeviceLink:
    def __init__(self, device_in: InputDevice, device_out: GadgetDevice):
        self._device_in = None
        self._device_in_name = None
        self._device_in_path = None
        if isinstance(device_in, InputDevice):
            self._device_in = device_in
            self._device_in_name = device_in.name
            self._device_in_path = device_in.path
        self._device_out = device_out
        self._device_out_enabled = False
        self._device_out_dummy = DummyGadget(device_out)
        if device_out:
            self._device_out_enabled = True

    def __repr__(self):
        return f"{self._device_in_name}: [{self._device_in}] >> [{repr(self.output())}]"

    def __str__(self):
        return f"[{self._device_in_name}]>>[{self.output()}]"

    def input(self) -> InputDevice:
        return self._device_in

    async def async_reset_input(self) -> None:
        self._device_in = None
        while True:
            try:
                self._device_in = InputDevice(self._device_in_path)
                break
            except Exception as e:
                logger.error(f"Error resetting input {self._device_in_path} [{e}]")
                await asyncio.sleep(5)

    def output(self) -> GadgetDevice:
        if not self._device_out_enabled:
            return self._device_out_dummy
        return self._device_out

    def enable_output(self, enabled: bool = True):
        self._device_out_enabled = enabled
