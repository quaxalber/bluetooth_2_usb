<!-- omit in toc -->
# Bluetooth to USB

![Connection overview](images/diagram.png)

<!-- omit in toc -->
## Table of Contents

- [1. Introduction](#1-introduction)
- [2. Features](#2-features)
- [3. Requirements](#3-requirements)
- [4. Installation](#4-installation)
  - [4.1. Prerequisites](#41-prerequisites)
  - [4.2. Setup](#42-setup)
- [5. Usage](#5-usage)
  - [5.1. Command-line arguments](#51-command-line-arguments)
  - [5.2. Consuming the API from your Python code](#52-consuming-the-api-from-your-python-code)
- [6. Troubleshooting](#6-troubleshooting)
  - [6.1. The Pi keeps rebooting or crashes randomly](#61-the-pi-keeps-rebooting-or-crashes-randomly)
  - [6.2. The installation was successful, but I don't see any output on the target device](#62-the-installation-was-successful-but-i-dont-see-any-output-on-the-target-device)
  - [6.3. In bluetoothctl, my device is constantly switching on/off](#63-in-bluetoothctl-my-device-is-constantly-switching-onoff)
  - [6.4. I have a different issue](#64-i-have-a-different-issue)
  - [6.5. Everything is working, but can it help me with Bitcoin mining?](#65-everything-is-working-but-can-it-help-me-with-bitcoin-mining)
- [7. Bonus points](#7-bonus-points)
- [8. Contributing](#8-contributing)
- [9. License](#9-license)
- [10. Acknowledgments](#10-acknowledgments)

## 1. Introduction

Convert a Raspberry Pi into a HID proxy that relays Bluetooth keyboard and mouse input to USB. Minimal configuration. Zero hassle.

The issue with Bluetooth devices is that you usually can't use them to wake up sleeping devices, access the BIOS or OS select menu (GRUB). Some devices don't even have a (working) Bluetooth interface.  

Sounds familiar? Congratulations! **You just found the solution!**

## 2. Features

- Simple installation and highly automated setup 
- Supports multiple input devices (currently keyboard and mouse - more than one of each kind simultaneously)
- Supports multimedia keys (e.g. mute, volume up/down, etc.)
- Auto-reconnect feature for input devices (power off, energy saving mode, out of range, etc.)
- Robust error handling and logging
- Installation as a systemd service
- Reliable concurrency using state-of-the-art [TaskGroups](https://docs.python.org/3/library/asyncio-task.html#task-groups)
- Clean and actively maintained code base

## 3. Requirements

- ([Single-board](https://en.wikipedia.org/wiki/Single-board_computer)) computer with Bluetooth support, e.g. Raspberry Pi 4B or Raspberry Pi Zero **_W_**
- Linux OS with systemd support, e.g. [Raspberry Pi OS](https://www.raspberrypi.com/software/) (recommended)
- Python 3.11 for using [TaskGroups](https://docs.python.org/3/library/asyncio-task.html#task-groups)

## 4. Installation

Follow these steps to install and configure the project:

### 4.1. Prerequisites 

1. Install an OS on your Raspberry Pi (e.g. using [Pi Imager](https://youtu.be/ntaXWS8Lk34))
   
2. Connect to a network via Ethernet cable or [Wi-Fi](https://www.raspberrypi.com/documentation/computers/configuration.html#configuring-networking). Make sure this network has Internet access.
   
3. (*optional*) Enable [SSH](https://www.raspberrypi.com/documentation/computers/remote-access.html#ssh), if you intend to access the Pi remotely.

> [!NOTE]
> These settings above may be configured [during imaging](https://www.raspberrypi.com/documentation/computers/getting-started.html#advanced-options), [on first boot](https://www.raspberrypi.com/documentation/computers/getting-started.html#configuration-on-first-boot) or [afterwards](https://www.raspberrypi.com/documentation/computers/configuration.html). 
   
4. Connect to the Pi and update the packages:
   
   ```console
   sudo apt update && sudo apt upgrade -y
   ```

5. Pair and trust any Bluetooth devices you wish to relay, either via GUI or:
   
   ```console
   bluetoothctl
   scan on
   ```

   ... wait for your devices to show up and note their MAC addresses (you may also type the first characters and hit `TAB` for auto-completion in the following commands) ...

   ```console
   pair A1:B2:C3:D4:E5:F6
   trust A1:B2:C3:D4:E5:F6
   ```

 > [!NOTE]
 > Replace `A1:B2:C3:D4:E5:F6` by your input device's Bluetooth MAC address

### 4.2. Setup 

6. On the Pi, clone the repository:  
   
   ```console
   git clone https://github.com/quaxalber/bluetooth_2_usb.git
   ```
   
7. Navigate to the project folder: 
   
   ```console
   cd bluetooth_2_usb
   ```

8. Run the installation script as root: 
    
   ```console
   sudo bash install.sh
   ```
 
 > [!NOTE]
 > Many point-release distros, including Raspberry Pi OS, are one or two minor versions behind the latest Python version. At the time of writing this, RPi OS ships with Python 3.9.2. You could opt for a different OS, such as [Ubuntu](https://ubuntu.com/download/raspberry-pi) or [pure Debian](https://raspi.debian.net/tested-images/). Or you let the installer [build Python 3.11 from source and install it as a Debian package](https://github.com/quaxalber/bluetooth_2_usb/blob/master/install_python_3.11.sh). This is the recommended approach. Depending on your hardware, this may take a moment though. 

9. Restart the Pi (prompt at the end of `install.sh`)
   
10. Check which Linux input devices your Bluetooth devices are mapped to:
   
    10.1. Start an interactive Python session:

    ```console
    python3.11
    ```

    10.2. Copy & paste these commands (`Enter` twice):

    ```python
    import evdev
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    for device in devices:
        print(f"{device.name}\t{device.phys}\t{device.path}")
    ```

    10.3. Note the device paths of the devices you want to use:

    ```console
    AceRK Mouse     0a:1b:2c:3d:4e:5f  /dev/input/event3  <---
    AceRK Keyboard  0a:1b:2c:3d:4e:5f  /dev/input/event2  <---
    vc4-hdmi-1      vc4-hdmi-1/input0  /dev/input/event1
    vc4-hdmi-0      vc4-hdmi-0/input0  /dev/input/event0
    ```

11. Specify the correct input devices in `bluetooth_2_usb.service`:
    
    ```console
    nano bluetooth_2_usb.service
    ```

    And change `event3` and `event2` according to step **10.3.** 
   
> [!NOTE]
> `Ctrl + X` > `Y` > `Enter` to save and exit nano

12. (*optional*) If you wish to test first, without actually sending anything to the target devices, append `-s` to the `ExecStart=` command to enable sandbox mode. To increase log verbosity add `-d`.
    
13. Reload and restart service:
    
    ```console
    sudo systemctl daemon-reload
    sudo service bluetooth_2_usb restart
    ```

14. Verify that the service is running:
    
    ```console
    service bluetooth_2_usb status
    ```

    It should look something like this:

    ```console
    user@raspberrypi:~/bluetooth_2_usb $ service bluetooth_2_usb status
    ● bluetooth_2_usb.service - Bluetooth to USB HID proxy
        Loaded: loaded (/home/user/bluetooth_2_usb/bluetooth_2_usb.service; enabled; vendor preset: enabled)
        Active: active (running) since Wed 2023-10-11 18:00:58 BST; 11s ago
      Main PID: 4256 (python3.11)
          Tasks: 1 (limit: 8755)
            CPU: 328ms
        CGroup: /system.slice/bluetooth_2_usb.service
                └─4256 python3.11 /usr/bin/bluetooth_2_usb.py -k /dev/input/event2 -m /dev/input/event3

    Oct 11 18:00:58 raspberrypi systemd[1]: Started Bluetooth to USB HID proxy.
    Oct 11 18:00:58 raspberrypi python3.11[4256]: 23-10-11 18:00:58 [INFO] Launching Bluetooth 2 USB v0.3.0
    Oct 11 18:01:01 raspberrypi python3.11[4256]: 23-10-11 18:01:01 [INFO] Starting event loop for AceRK Keyboard: [device /dev/input/event2, name "AceRK Keyboard", phys "0a:1b:2c:3d:4e:5f"] >> [Keyboard gadget (/dev/hidg1) + Consumer control gadget (/dev/hidg2)]
    Oct 11 18:01:01 raspberrypi python3.11[4256]: 23-10-11 18:01:01 [INFO] Starting event loop for AceRK Mouse: [device /dev/input/event3, name "AceRK Mouse", phys "0a:1b:2c:3d:4e:5f"] >> [Boot mouse gadget (/dev/hidg0)]
    ```

> [!NOTE]
> Something seems off? Try yourself in [Troubleshooting](#6-troubleshooting)! 
    
## 5. Usage

Connect the power USB port of your Pi (Micro-USB or USB-C) via cable with a USB port on your target device. You should hear the USB connection sound (depending on the target device) and be able to access your target device wirelessly using your Bluetooth keyboard or mouse. 

> [!IMPORTANT]
> It's essential to use the small power port instead of the bigger USB-A ports, since only the power port has the [OTG](https://en.wikipedia.org/wiki/USB_On-The-Go) feature required for [USB gadgets](https://www.kernel.org/doc/html/latest/driver-api/usb/gadget.html). 

### 5.1. Command-line arguments

Currently you can provide the following CLI arguments:

```console
user@raspberrypi:~/bluetooth_2_usb $ python3.11 bluetooth_2_usb.py -h
usage: bluetooth_2_usb.py [-h] [--keyboards KEYBOARDS] [--mice MICE] [--sandbox] [--debug] [--log_to_file] [--log_path LOG_PATH] [--version]

Bluetooth to USB HID proxy. Reads incoming mouse and keyboard events (e.g., Bluetooth) and forwards them to USB using Linux's gadget mode.

options:
  -h, --help            show this help message and exit
  --keyboards KEYBOARDS, -k KEYBOARDS
                        Comma-separated list of input device paths for keyboards to be registered and connected. Default is None. Example: --keyboards /dev/input/event2,/dev/input/event4
  --mice MICE, -m MICE  Comma-separated list of input device paths for mice to be registered and connected. Default is None. Example: --mice /dev/input/event3,/dev/input/event5
  --sandbox, -s         Only read input events but do not forward them to the output devices.
  --debug, -d           Enable debug mode. Increases log verbosity
  --log_to_file, -f     Add a handler that logs to file additionally to stdout.
  --log_path LOG_PATH, -p LOG_PATH
                        The path of the log file. Default is /var/log/bluetooth_2_usb/bluetooth_2_usb.log.
  --version, -v         Display the version number of this software.
```

### 5.2. Consuming the API from your Python code

The API is designed such that it may be consumed both via CLI and from within external Python code. More details on this [coming soon](https://github.com/quaxalber/bluetooth_2_usb/issues/16)! 

## 6. Troubleshooting

### 6.1. The Pi keeps rebooting or crashes randomly

This is likely due to the limited power the Pi gets from the host's USB port. Try these steps:

- If available, connect your Pi to a USB 3 port on the host  / target device (usually blue). 
  
> [!IMPORTANT]
> *Do not use* the blue (or black) USB-A ports *of your Pi* to connect. **This won't work.** 
> 
> *Do use* the small USB power port. 

- Try to [connect to the Pi via SSH](#41-prerequisites) instead of attaching a display directly and remove any unnecessary peripherals.
  
- Install a [lite version](https://downloads.raspberrypi.org/raspios_lite_arm64/images/) of your OS on the Pi (without GUI)
  
- Get a [USB-C Data/Power Splitter](https://thepihut.com/products/usb-c-data-power-splitter) (or [Micro-USB](https://thepihut.com/products/micro-usb-data-power-splitter) respectively) and draw power from a sufficiently powerful power adaptor. This will ultimately resolve any power-related issues, and your Pi will no longer be dependent on the host's power supply. 
  
> [!NOTE]
> The Pi 4B requires 3A/15W for stable operation!

### 6.2. The installation was successful, but I don't see any output on the target device 

This could be due to a number of reasons. Try these steps:

- Verify that the service is running:
  
  ```console
  service bluetooth_2_usb status
  ```

- Verify that you specified the correct input devices in `bluetooth_2_usb.service` and that sandbox mode is off (that is no `--sandbox` or `-s` flag)
  
- Verify that your Bluetooth devices are paired, trusted, connected and *not* blocked:
  
  ```console
  bluetoothctl
  info A1:B2:C3:D4:E5:F6
  ```
  
  It should look like this:

  ```console
  user@raspberrypi:~/bluetooth_2_usb $ bluetoothctl
  Agent registered
  [CHG] Controller 0A:1B:2C:3D:4E:5F Pairable: yes
  [AceRK]# info A1:B2:C3:D4:E5:F6
  Device A1:B2:C3:D4:E5:F6 (random)
          Name: AceRK
          Alias: AceRK
          Paired: yes     <---
          Trusted: yes    <---
          Blocked: no     <---
          Connected: yes  <---
          WakeAllowed: no
          LegacyPairing: no
          UUID: Generic Access Profile    (00001800-0000-1000-8000-00805f9b34fb)
          UUID: Generic Attribute Profile (00001801-0000-1000-8000-00805f9b34fb)
          UUID: Device Information        (0000180a-0000-1000-8000-00805f9b34fb)
          UUID: Human Interface Device    (00001812-0000-1000-8000-00805f9b34fb)
          UUID: Nordic UART Service       (6e400001-b5a3-f393-e0a9-e50e24dcca9e)
  ```
  
> [!NOTE]
> Replace `A1:B2:C3:D4:E5:F6` by your input device's Bluetooth MAC address

- Reload and restart service:
  
  ```console
  sudo systemctl daemon-reload
  sudo service bluetooth_2_usb restart
  ```

- Reboot Pi
  
  ```console
  sudo reboot 
  ```

- Re-connect the Pi to the host and check that the cable is in good shape 
  
- Try a different USB port on the host
  
- Try connecting to a different host 

### 6.3. In bluetoothctl, my device is constantly switching on/off

This is a common issue, especially when the device gets paired with multiple hosts. One simple fix/workaround is to re-pair the device:

```console
bluetoothctl
power off
power on
block A1:B2:C3:D4:E5:F6
remove A1:B2:C3:D4:E5:F6
scan on
pair A1:B2:C3:D4:E5:F6
trust A1:B2:C3:D4:E5:F6
```

If the issue persists, it's worth trying to delete the cache:

```console
sudo -i
cd '/var/lib/bluetooth/0A:1B:2C:3D:4E:5F/cache'
rm -rf 'A1:B2:C3:D4:E5:F6'
exit
```

> [!NOTE]
> Replace `0A:1B:2C:3D:4E:5F` by your Pi's Bluetooth controller's MAC and `A1:B2:C3:D4:E5:F6` by your input device's MAC

### 6.4. I have a different issue 

Here's a few things you could try:

- Check the log files (default at `/var/log/bluetooth_2_usb/`) for errors
  
> [!NOTE]
> Logging to file requires the `-f` flag

- You may also query the journal to inspect the service logs in real-time:
  
  ```console
  journalctl -u bluetooth_2_usb.service -n 20 -f
  ```

- Increase log verbosity by appending `-d` to the command in the line starting with `ExecStart=` in `bluetooth_2_usb.service`. 
  
- Reload and restart service:
  
  ```console
  sudo systemctl daemon-reload
  sudo service bluetooth_2_usb restart
  ```

- For easier degguging, you may also stop the service 
  
  ```console
  sudo service bluetooth_2_usb stop
  ```

  and run the script manually, modifying arguments as required, e.g.:

  ```console
  sudo python3.11 bluetooth_2_usb.py -k /dev/input/event2 -m /dev/input/event3 -d
  ```

- When you interact with your Bluetooth devices with `-d` set, you should see debug output in the logs such as:
  
  ```console
  user@raspberrypi:~/bluetooth_2_usb $ sudo service bluetooth_2_usb stop
  user@raspberrypi:~/bluetooth_2_usb $ sudo python3.11 bluetooth_2_usb.py -k /dev/input/event2 -m /dev/input/event3 -d
  23-10-11 17:53:19 [DEBUG] CLI args: Namespace(keyboards=['/dev/input/event2'], mice=['/dev/input/event3'], sandbox=False, debug=True, log_to_file=False, log_path='/var/log/bluetooth_2_usb/bluetooth_2_usb.log', version=False)
  23-10-11 17:53:19 [DEBUG] Logging to stdout
  23-10-11 17:53:19 [INFO] Launching Bluetooth 2 USB v0.3.0
  23-10-11 17:53:19 [DEBUG] Available output devices: [Boot mouse gadget (/dev/hidg0), Keyboard gadget (/dev/hidg1), Consumer control gadget (/dev/hidg2)]
  23-10-11 17:53:22 [DEBUG] Sandbox mode disabled. All output devices activated.
  23-10-11 17:53:22 [DEBUG] Registered device link: [AceRK Keyboard]>>[/dev/hidg1+/dev/hidg2]
  23-10-11 17:53:22 [DEBUG] Registered device link: [AceRK Mouse]>>[/dev/hidg0]
  23-10-11 17:53:22 [DEBUG] Link [AceRK Keyboard]>>[/dev/hidg1+/dev/hidg2] connected.
  23-10-11 17:53:22 [DEBUG] Link [AceRK Mouse]>>[/dev/hidg0] connected.
  23-10-11 17:53:22 [DEBUG] Current tasks: {<Task pending name='[AceRK Mouse]>>[/dev/hidg0]' coro=<ComboDeviceHidProxy._async_relay_input_events() running at /home/user/bluetooth_2_usb/bluetooth_2_usb.py:222> cb=[TaskGroup._on_task_done()]>, <Task pending name='Task-1' coro=<_main() running at /home/user/bluetooth_2_usb/bluetooth_2_usb.py:380> cb=[_run_until_complete_cb() at /usr/local/lib/python3.11/asyncio/base_events.py:180]>, <Task pending name='[AceRK Keyboard]>>[/dev/hidg1+/dev/hidg2]' coro=<ComboDeviceHidProxy._async_relay_input_events() running at /home/user/bluetooth_2_usb/bluetooth_2_usb.py:222> cb=[TaskGroup._on_task_done()]>}
  23-10-11 17:53:22 [INFO] Starting event loop for AceRK Keyboard: [device /dev/input/event2, name "AceRK Keyboard", phys "0a:1b:2c:3d:4e:5f"] >> [Keyboard gadget (/dev/hidg1) + Consumer control gadget (/dev/hidg2)]
  23-10-11 17:53:22 [INFO] Starting event loop for AceRK Mouse: [device /dev/input/event3, name "AceRK Mouse", phys "0a:1b:2c:3d:4e:5f"] >> [Boot mouse gadget (/dev/hidg0)]
  23-10-11 17:53:47 [DEBUG] Received event: [event at 1697043227.896161, code 04, type 04, val 458756]
  23-10-11 17:53:47 [DEBUG] Received event: [key event at 1697043227.896161, 30 (KEY_A), down]
  23-10-11 17:53:47 [DEBUG] Converted ecode 30 to HID keycode 4
  23-10-11 17:53:47 [DEBUG] Received event: [synchronization event at 1697043227.896161, SYN_REPORT]
  23-10-11 17:53:59 [DEBUG] Received event: [relative axis event at 1697043239.157504, REL_X]
  23-10-11 17:53:59 [DEBUG] Moving mouse /dev/hidg0: (x, y, mwheel) = (125, 0, 0)
  23-10-11 17:53:59 [DEBUG] Received event: [synchronization event at 1697043239.157504, SYN_REPORT]
  ``` 

- Still not resolved? Double-check the [installation instructions](#4-installation)
  
- For more help, open an [issue](https://github.com/quaxalber/bluetooth_2_usb/issues) in the [GitHub repository](https://github.com/quaxalber/bluetooth_2_usb)

### 6.5. Everything is working, but can it help me with Bitcoin mining? 

Absolutely! [Here's how](https://bit.ly/42BTC). 

## 7. Bonus points 

After successfully setting up your Pi as a HID proxy for your Bluetooth devices, you may consider making [Raspberry OS read-only](https://learn.adafruit.com/read-only-raspberry-pi/overview). That helps preventing the SD card from wearing out and the file system from getting corrupted when powering off the Raspberry forcefully.

## 8. Contributing

Contributions are welcome! Please read the [CONTRIBUTING.md](CONTRIBUTING.md) file for guidelines.

## 9. License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.

"Bluetooth 2 HID" image [@PixelGordo](https://twitter.com/PixelGordo) is licensed under a [Creative Commons Attribution-NonCommercial 4.0 International License](http://creativecommons.org/licenses/by-nc/4.0/).

![License image.](https://i.creativecommons.org/l/by-nc/4.0/88x31.png)

## 10. Acknowledgments

* [Mike Redrobe](https://github.com/mikerr/pihidproxy) for the idea and the basic code logic and [HeuristicPerson's bluetooth_2_hid](https://github.com/HeuristicPerson/bluetooth_2_hid) based off this.
* [Georgi Valkov](https://github.com/gvalkov) for [python-evdev](https://github.com/gvalkov/python-evdev) making reading input devices a walk in the park. 
* The folks at [Adafruit](https://www.adafruit.com/) for [CircuitPython HID](https://github.com/adafruit/Adafruit_CircuitPython_HID) and [Blinka](https://github.com/quaxalber/Adafruit_Blinka/blob/main/src/usb_hid.py) providing super smooth access to USB gadgets. 
* Special thanks to the open-source community for various other libraries and tools.
