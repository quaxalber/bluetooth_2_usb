#!/usr/bin/env python
"""
Reads incoming mouse and keyboard events (e.g., Bluetooth) and forwards them to USB using Linux's gadget mode.
"""

import argparse
import asyncio
from datetime import datetime
import logging
import signal
import sys
import time
from typing import Union
import usb_hid
from usb_hid import Device as OutputDevice

from adafruit_hid.keyboard import Keyboard
from adafruit_hid.mouse import Mouse
from evdev import InputDevice, InputEvent, categorize, ecodes, list_devices

from lib.constants import errno, key_event
import lib.evdev_converter as converter
import lib.logger

logger = lib.logger.get_logger()

class ComboDeviceHidProxy:
    def __init__(self, keyboard_in: str=None, mouse_in: str=None, is_sandbox: bool=False):
        self._init_variables()
        self._enable_usb_gadgets(keyboard_in, mouse_in)
        self._init_devices(keyboard_in, mouse_in)
        if is_sandbox:
            self._enable_sandbox()

    def _init_variables(self):
        self.keyboard_in = None            
        self.keyboard_out = None
        self.mouse_in = None     
        self.mouse_out = None
        self.is_sandbox = False

    def _enable_usb_gadgets(self, keyboard_in: str=None, mouse_in: str=None):
        try:
            requested_devices = self._get_requested_devices(keyboard_in, mouse_in)
            usb_hid.enable(requested_devices)
        except Exception as e:
            logger.error(f"Failed to enable devices. [{e}]")
            sys.exit(1)

    def _get_requested_devices(self, keyboard_in: str=None, mouse_in: str=None):
        requested_devices = []
        if keyboard_in is not None:
            requested_devices.append(OutputDevice.KEYBOARD)
        if mouse_in is not None:
            requested_devices.append(OutputDevice.MOUSE)
        return requested_devices

    def _init_devices(self, keyboard_in: str=None, mouse_in: str=None):
        try:
            logger.info(f'Available output devices: {self._available_out_devices_repr()}')
            if keyboard_in is not None:
                self._init_keyboard(keyboard_in)
            if mouse_in is not None:
                self._init_mouse(mouse_in)
        except Exception as e:
            logger.error(f"Failed to initialize devices. [{e}]")
            sys.exit(1)

    def _init_keyboard(self, keyboard_in: str):
        self.keyboard_in = InputDevice(keyboard_in)               
        logger.info(f'Keyboard (in): {self.keyboard_in}')
        self.keyboard_out = Keyboard(usb_hid.devices)
        logger.info(f'Keyboard (out): {self._keyboard_out_repr()}')

    def _init_mouse(self, mouse_in: str):
        self.mouse_in = InputDevice(mouse_in)
        logger.info(f'Mouse (in): {self.mouse_in}')
        self.mouse_out = Mouse(usb_hid.devices)
        logger.info(f'Mouse (out): {self._mouse_out_repr()}')

    def _enable_sandbox(self):
        self.is_sandbox = True
        self.keyboard_out = None
        self.mouse_out = None
        logger.warning('Sandbox mode enabled! All output devices deactivated.')
  
    def _available_out_devices_repr(self) -> str:
        return [self.device_repr(dev) for dev in usb_hid.devices]

    def _keyboard_out_repr(self) -> str:
        return self.device_repr(self.keyboard_out._keyboard_device)

    def _mouse_out_repr(self) -> str:
        return self.device_repr(self.mouse_out._mouse_device)

    def device_repr(self, device: Union[InputDevice, OutputDevice]) -> str:
        if isinstance(device, InputDevice):
            return f'{device.name} ({device.path})'
        elif isinstance(device, OutputDevice):
            class_name = type(device).__name__
            device_path = device.get_device_path(None)
            return f'{class_name} ({device_path})'
    
    def run_event_loop(self):
        if self.keyboard_in is not None:
            asyncio.ensure_future(
                self.async_read_and_handle_events(self.keyboard_in, self.keyboard_out)
            )
        if self.mouse_in is not None:
            asyncio.ensure_future(
                self.async_read_and_handle_events(self.mouse_in, self.mouse_out)
            )
        loop = asyncio.get_event_loop()
        loop.run_forever()
    
    async def async_read_and_handle_events(self, device_in: InputDevice, device_out: OutputDevice):
        logger.info(f"Started event loop for {self.device_repr(device_in)}")
        try:
            async for event in device_in.async_read_loop():
                if event is None: 
                    continue
                self.handle_event(event, device_out) 
        except OSError as e:
            if e.errno == errno.OSError.NO_SUCH_DEVICE:
                self.reconnect_input_device(device_in)
            else:
                raise e
        except Exception as e:
            logger.error(f"Failed reading events from {self.device_repr(device_in)} [{e}]") 

    def handle_event(self, event: InputEvent, device_out: OutputDevice):
        logger.debug(f"Received event: [{categorize(event)}] for {self.device_repr(device_out)}") 
        if self.is_key_up_or_down(event):
            self.send_key(event, device_out)
        elif self.is_mouse_move(event):
            self.send_mouse_move(event, device_out)   
    
    def is_key_up_or_down(self, event: InputEvent):
        return event.type == ecodes.EV_KEY and event.value in [key_event.DOWN, key_event.UP]   
    
    def is_mouse_move(self, event: InputEvent):
        return event.type == ecodes.EV_REL 

    def send_key(self, event: InputEvent, device_out: OutputDevice):
        key = converter.to_hid_key(event.code) 
        if key is None or self.is_sandbox: 
            return
        try:
            if event.value == key_event.DOWN:
                device_out.press(key)
            elif event.value == key_event.UP:
                device_out.release(key)
        except Exception as e:
            logger.error(f"Error sending key event [{categorize(event)}] to {self.device_repr(device_out)} [{e}]")

    def send_mouse_move(self, event: InputEvent, mouse_out: Mouse):
        x, y, mwheel = 0, 0, 0
        if event.code == ecodes.REL_X:
            x = event.value
        elif event.code == ecodes.REL_Y:
            y = event.value
        elif event.code == ecodes.REL_WHEEL:
            mwheel = event.value
        logger.debug(f"Sending mouse event: (x, y, mwheel) = {(x, y, mwheel)} to {self.device_repr(mouse_out)}")
        if self.is_sandbox: 
            return
        try:
            mouse_out.move(x, y, mwheel)
        except Exception as e:
            logger.error(f"Error sending mouse move event [{categorize(event)}] to {self.device_repr(mouse_out)} [{e}]")

    def reconnect_input_device(self, device_in: InputDevice, wait_seconds: float=5):
        start_time = datetime.now()
        last_log_time = start_time
        logger.warn(f"Lost connection to {self.device_repr(device_in)}. Trying to reconnect...")

        while True:
            if device_in.path in list_devices():
                logger.info(f"Successfully reconnected to {self.device_repr(device_in)}")
                break
            else:
                last_log_time = self._log_failed_reconnection_attempt(device_in, start_time, last_log_time)
                time.sleep(wait_seconds) 

    def _log_failed_reconnection_attempt(
            self, 
            device_in: InputDevice, 
            start_time: datetime, 
            last_log_time: datetime) -> datetime:
        
        current_time = datetime.now()
        elapsed_minutes = (current_time - start_time).total_seconds() / 60
        minutes_since_last_log = (current_time - last_log_time).total_seconds() / 60
        should_write_log = False

        if elapsed_minutes <= 10 and minutes_since_last_log >= 1:
            should_write_log = True 
        elif minutes_since_last_log >= 10:
            should_write_log = True
        if should_write_log:
            logger.info(f"Still trying to reconnect to {self.device_repr(device_in)}...")
            last_log_time = current_time

        return last_log_time
 
def parse_args():
    parser = argparse.ArgumentParser(description='Bluetooth to HID proxy.')
    parser.add_argument('--keyboard', '-k', type=str, default=None, help='Input device path for keyboard')
    parser.add_argument('--mouse', '-m', type=str, default=None, help='Input device path for mouse')
    parser.add_argument('--sandbox', '-s', action='store_true', default=False, help='Only read input events but do not forward them to the output devices.')
    parser.add_argument('--debug', '-d', action='store_true', default=False, help='Increase log verbosity.')
    args = parser.parse_args()
    return args

def signal_handler(sig, frame):
    logger.info(f'Exiting gracefully. Received signal: {sig}, frame: {frame}')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    try:
        args = parse_args()  
        if args.debug:
            logger.setLevel(logging.DEBUG)
        proxy = ComboDeviceHidProxy(args.keyboard, args.mouse, args.sandbox)
        proxy.run_event_loop()
    except Exception as e:
        logger.error(f"Unhandled error while processing input events. Abort mission. [{e}]")   
