#!/usr/bin/env python
'''
Reads incoming mouse and keyboard events (e.g., Bluetooth) and forwards them to USB using Linux's gadget mode.
'''

try:
    import argparse
    from argparse import Namespace
    import asyncio
    from asyncio import TaskGroup, Task
    from datetime import datetime
    import logging
    import signal
    import sys
    from typing import List, NoReturn, Optional, Tuple

    from evdev import InputDevice, InputEvent, categorize, ecodes, list_devices

    from lib.constants import key_event
    import lib.evdev_converter as converter
    import lib.logger
    import lib.usb_hid
    from lib.usb_hid import GadgetDevice, MouseGadget, KeyboardGadget, DevicePair
except ImportError as e:
    print(f'Error importing modules. [{e}]')
    raise

logger = lib.logger.get_logger()


class ComboDeviceHidProxy:
    def __init__(self, 
            keyboard_in: Optional[str] = None, 
            mouse_in: Optional[str] = None, 
            is_sandbox: bool = False
        ) -> None:
        self._init_variables(is_sandbox)
        self._enable_usb_gadgets()
        self._init_devices(keyboard_in, mouse_in)

    def _init_variables(self, 
            is_sandbox: bool = False
        ) -> None:
        self._device_pairs: List[DevicePair] = []
        self._is_sandbox = is_sandbox
        self._task_group = None 

    def _enable_usb_gadgets(self,
            gadgets_enabled: bool = True
        ) -> None:
        try:
            if gadgets_enabled:
                lib.usb_hid.enable([GadgetDevice.BOOT_MOUSE, GadgetDevice.KEYBOARD])
                logger.debug(f'Available output devices: {lib.usb_hid.devices}')
            else:
                lib.usb_hid.disable()
                logger.warning(f'Disabled all output devices!')
        except Exception as e:
            logger.error(f'Failed to enable/disable devices. [{e}]')
            sys.exit(1)

    def _init_devices(self, 
            keyboard_in: Optional[str] = None, 
            mouse_in: Optional[str] = None
        ) -> None:
        try:
            self._init_mouse(mouse_in)
            self._init_keyboard(keyboard_in)
            if self._is_sandbox:
                self._enable_sandbox()
            for pair in self._device_pairs:
                logger.debug(repr(pair))
        except Exception as e:
            logger.error(f'Failed to initialize devices. [{e}]')
            sys.exit(1)

    def _init_mouse(self, 
            mouse_in: Optional[str] = None
        ) -> None:
        if not mouse_in:
            return
        mouse_pair = DevicePair(
            InputDevice(mouse_in),
            MouseGadget(),
            name = 'Mouse'
        )
        self._device_pairs.append(mouse_pair)

    def _init_keyboard(self, 
            keyboard_in: Optional[str] = None
        ) -> None:
        if not keyboard_in:
            return
        keyboard_pair = DevicePair(
            InputDevice(keyboard_in),
            KeyboardGadget(),
            name = 'Keyboard'
        )
        self._device_pairs.append(keyboard_pair)

    def _enable_sandbox(self,
            sandbox_enabled: bool = True
        ) -> None:
        self._is_sandbox = sandbox_enabled
        outputs_enabled = not sandbox_enabled
        for pair in self._device_pairs:
            pair.enable_output(outputs_enabled)
        if sandbox_enabled:
            logger.warning('Sandbox mode enabled! All output devices deactivated.')
        else:
            logger.warning('Sandbox mode disabled. All output devices activated.')
    
    async def async_run_event_loop(self) -> NoReturn:
        while True:
            try:
                async with TaskGroup() as self._task_group:
                    for pair in self._device_pairs:
                        self._create_task(pair)
                    logger.debug(f'Running tasks: {asyncio.all_tasks()}')
            except* Exception as e:
                logger.error(f'Error(s) in TaskGroup: [{e.exceptions}]')
            logger.critical(f'Event loop closed. Trying to restart.')
            await asyncio.sleep(5) 

    def _create_task(self, 
            device_pair: DevicePair
        ) -> Task:
        task = self._task_group.create_task(
                self.async_process_events(device_pair),
                name=device_pair.name()
            )
        return task
    
    async def async_process_events(self, 
            device_pair: DevicePair
        ) -> None:
        logger.info(f'Started event loop for {repr(device_pair)}')
        try:
            device_in = device_pair.input()
            device_out = device_pair.output()
            async for event in device_in.async_read_loop():
                if not event: 
                    continue
                await self.async_handle_event(event, device_out) 
        except OSError:
            reconnected = await self.async_reconnect_device(device_pair)
            if not reconnected:
                logger.critical(f'Reconnecting failed for {device_in}.')
                raise
            self._delete_task(device_pair, restart = True)   
        except Exception as e:
            logger.error(f'Failed reading events from {device_in}. Cancelling this task. [{e}]')
            self._delete_task(device_pair, restart = False)

    def _delete_task(self,
            device_pair: DevicePair, 
            restart: bool = False
        ) -> None:
        task = self._get_task(device_pair)
        self._cancel_task(task)
        if restart:
            device_pair.reset_input()
            self._create_task(device_pair)

    def _get_task(self, 
            device_pair: DevicePair
        ) -> Task:
        for task in asyncio.all_tasks():
            if task.get_name() == device_pair.name():
                return task
        return None

    def _cancel_task(self, 
            task: Task
        ) -> None:
        if self._is_running(task):
            task.cancel()

    def _is_running(self, 
            task: Task
        ) -> bool:
        return task and not task.cancelled() and not task.cancelling() and not task.done()

    async def async_handle_event(self, 
            event: InputEvent, 
            device_out: GadgetDevice
        ) -> None:
        logger.debug(f'Received event: [{categorize(event)}] for {device_out}') 
        if self.is_key_up_or_down(event):
            await self.async_send_key(event, device_out)
        elif self.is_mouse_move(event):
            await self.async_send_mouse_move(event, device_out)   
    
    def is_key_up_or_down(self, 
            event: InputEvent
        ) -> bool:
        return event.type == ecodes.EV_KEY and event.value in [key_event.DOWN, key_event.UP]   
    
    def is_mouse_move(self, 
            event: InputEvent
        ) -> bool:
        return event.type == ecodes.EV_REL 

    async def async_send_key(self, 
            event: InputEvent, 
            device_out: GadgetDevice
        ) -> None:
        key = converter.to_hid_key(event.code) 
        if not key: 
            return
        try:
            if event.value == key_event.DOWN:
                device_out.press(key)
            elif event.value == key_event.UP:
                device_out.release(key)
        except Exception as e:
            logger.error(f'Error sending key event [{categorize(event)}] to {device_out} [{e}]')

    async def async_send_mouse_move(self, 
            event: InputEvent, 
            mouse_out: MouseGadget
        ) -> None:
        x, y, mwheel = self._get_mouse_movement(event)
        logger.debug(f'Sending mouse event: (x, y, mwheel) = {(x, y, mwheel)} to {mouse_out}')
        try:
            mouse_out.move(x, y, mwheel)
        except Exception as e:
            logger.error(f'Error sending mouse move event [{categorize(event)}] to {mouse_out} [{e}]')

    def _get_mouse_movement(self, 
            event: InputEvent
        ) -> Tuple[int, int, int]:
        x, y, mwheel = 0, 0, 0
        if event.code == ecodes.REL_X:
            x = event.value
        elif event.code == ecodes.REL_Y:
            y = event.value
        elif event.code == ecodes.REL_WHEEL:
            mwheel = event.value
        return x, y, mwheel

    async def async_reconnect_device(self, 
            device_pair: DevicePair, 
            delay_seconds: float=1
        ) -> bool:
        device_in = device_pair.input()
        start_time = datetime.now()
        last_log_time = start_time
        logger.critical(f'Lost connection to {device_in}. Trying to reconnect...')

        while device_in.path not in list_devices():
            last_log_time = self._log_reconnection_attempt(device_in, start_time, last_log_time)
            await asyncio.sleep(delay_seconds) 

        logger.info(f'Successfully reconnected to {device_in}.')

        return True

    def _log_reconnection_attempt(self, 
            device_in: InputDevice, 
            start_time: datetime, 
            last_log_time: datetime
        ) -> datetime:
        current_time = datetime.now()
        elapsed_minutes = (current_time - start_time).total_seconds() / 60
        minutes_since_last_log = (current_time - last_log_time).total_seconds() / 60
        should_write_log = self._should_write_log(elapsed_minutes, minutes_since_last_log)

        if should_write_log:
            logger.info(f'Still trying to reconnect to {device_in}...')
            last_log_time = current_time

        return last_log_time

    def _should_write_log(self, 
            elapsed_minutes: float, 
            minutes_since_last_log: float
        ) -> bool:
        should_write_log = False

        if elapsed_minutes <= 10 and minutes_since_last_log >= 1:
            should_write_log = True 
        elif elapsed_minutes > 10 and minutes_since_last_log >= 30:
            should_write_log = True
        return should_write_log

def __parse_args() -> Namespace:
    parser = argparse.ArgumentParser(description = 'Bluetooth to HID proxy.')
    parser.add_argument('--keyboard', '-k', type = str, default=None, help = 'Input device path for keyboard')
    parser.add_argument('--mouse', '-m', type = str, default=None, help = 'Input device path for mouse')
    parser.add_argument('--sandbox', '-s', action = 'store_true', default = False, help = 'Only read input events but do not forward them to the output devices.')
    parser.add_argument('--debug', '-d', action = 'store_true', default = False, help = 'Increase log verbosity')
    parser.add_argument('--log_to_file', '-f', action = 'store_true', default = False, help = 'Add a handler that logs to file')
    parser.add_argument('--log_path', '-p', type = str, default = '/var/log/bluetooth_2_usb/bluetooth_2_usb.log', help = 'The path of the log file')
    args = parser.parse_args()
    return args

def __signal_handler(sig, frame) -> NoReturn:
    logger.info(f'Exiting gracefully. Received signal: {sig}, frame: {frame}')
    sys.exit(0)

signal.signal(signal.SIGINT, __signal_handler)
signal.signal(signal.SIGTERM, __signal_handler)

async def __main(args: Namespace) -> NoReturn:
    """
    Run the main event loop to read events from the input device and forward them to the corresponding USB device.
    
    Parameters:
        args (Namespace): Command-line arguments.
    """
    proxy = ComboDeviceHidProxy(args.keyboard, args.mouse, args.sandbox)
    await proxy.async_run_event_loop()
    logger.critical(f'Main exited prematurely.')

if __name__ == '__main__':
    """
    Entry point for the script. Sets up logging, parses command-line arguments, and starts the event loop.
    """
    try:
        args = __parse_args()  
        if args.debug:
            logger.setLevel(logging.DEBUG)
            logger.debug(f'CLI args: {args}')
        if args.log_to_file:
            lib.logger.add_file_handler(args.log_path)
        asyncio.run(__main(args))
    except Exception as e:
        logger.error(f'Houston, we have an unhandled problem. Abort mission. [{e}]') 
        raise 
