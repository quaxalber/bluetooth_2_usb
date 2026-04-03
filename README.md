<!-- omit in toc -->
# Bluetooth to USB
![Connection overview](images/diagram.png)
<!-- omit in toc -->
# Table of Contents
- [1. Introduction](#1-introduction)
- [2. Features](#2-features)
- [3. Requirements](#3-requirements)
- [4. Installation](#4-installation)
  - [4.1. Prerequisites](#41-prerequisites)
  - [4.2. Setup](#42-setup)
  - [4.3. Test](#43-test)
- [5. Usage](#5-usage)
- [6. Troubleshooting](#6-troubleshooting)
  - [6.1. The Pi keeps rebooting or crashes randomly](#61-the-pi-keeps-rebooting-or-crashes-randomly)
  - [6.2. The installation was successful, but I don't see any output on the target device](#62-the-installation-was-successful-but-i-dont-see-any-output-on-the-target-device)
  - [6.3. After being afk for a while, it stops working](#63-after-being-afk-for-a-while-it-stops-working)
  - [6.4. I have a different issue](#64-i-have-a-different-issue)
  - [6.5. Everything is working, but can it help me with Bitcoin mining?](#65-everything-is-working-but-can-it-help-me-with-bitcoin-mining)
- [7. Known issues](#7-known-issues)
  - [7.1. Mouse is crashing](#71-mouse-is-crashing)
- [8. Bonus points](#8-bonus-points)
- [9. Contributing](#9-contributing)
- [10. License](#10-license)
- [11. Acknowledgments](#11-acknowledgments)

# 1. Introduction
Convert a Raspberry Pi into a HID proxy that relays Bluetooth keyboard and mouse input to USB. Minimal configuration. Zero hassle.

The issue with Bluetooth devices is that you usually can't use them to wake up sleeping devices, access the BIOS or OS select menu (GRUB). Some devices don't even have a (working) Bluetooth interface.  

Sounds familiar? Congratulations! **You just found the solution!**

# 2. Features
- Simple installation and highly automated setup
- Supports various Bluetooth input devices (currently keyboard and mouse)
- Robust error handling and logging

# 3. Requirements
- Raspberry Pi with Bluetooth support, e.g. Pi 4B or Pi Zero **_W_**
- Python 3.x
- Linux OS with systemd support, e.g. [Raspberry Pi OS](https://www.raspberrypi.com/software/)

# 4. Installation
Follow these steps to install and configure the project:

## 4.1. Prerequisites 
1. Prepare your Raspberry Pi (e.g. using [Pi Imager](https://youtu.be/ntaXWS8Lk34)) and connect to WI-FI & enable SSH, if you intend to access the Pi remotely.
   
2. Connect to the Pi and update the packages:
   ```
   sudo apt update && sudo apt upgrade -y
   ```

3. Pair and trust any Bluetooth devices you wish to relay, either via GUI or:
   ``` bash
   bluetoothctl
   scan on
   pair {your-device-mac}
   trust {your-device-mac}
   ```

## 4.2. Setup 
4. On the Pi, clone the repository:  
   ```
   git clone https://github.com/quaxalber/bluetooth_2_usb.git
   ```
   
5. Navigate to the project folder:  
   ```
   cd bluetooth_2_usb
   ```

6. Run the installation script as root:  
   ```
   sudo bash install.sh
   ```

7. Restart the Pi (prompt at the end of `install.sh`)
   
8. Check which Linux input devices your Bluetooth devices are mapped to:
   
   8.1. Start an interactive Python session:
   ``` bash
   python3
   ```

   8.2. Copy & paste these commands:
   ``` python
   import evdev
   devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
   for device in devices:
       print(device.path, device.name, device.phys)
   ```

   8.3. Note the device paths of the devices you want to use:
   ``` bash
   /dev/input/event3 AceRK Mouse xx:xx:xx:xx:xx:xx
   /dev/input/event2 AceRK Keyboard yy:yy:yy:yy:yy:yy
   /dev/input/event1 vc4-hdmi-1 vc4-hdmi-1/input0
   /dev/input/event0 vc4-hdmi-0 vc4-hdmi-0/input0
   ```

9.  Specify the correct input devices in `bluetooth_2_usb.service`:
    ```
    nano bluetooth_2_usb.service
    ```

     And change `event3` and `event2` according to **8.3.** 
   
     (`Ctrl + X` > `Y` > `Enter` to exit)

10. (*optional*) If you wish to test first, without actually sending anything to the target devices, append `-s` to the `ExecStart=` command to enable sandbox mode. To increase log verbosity add `-d`.
    
11. Reload and restart service:
    ``` bash
    sudo systemctl daemon-reload
    sudo service bluetooth_2_usb restart
    ```

## 4.3. Test
12. Verify that the service is running. It should look something like this:
  ``` bash
  user@raspberrypi:~/bluetooth_2_usb $ sudo service bluetooth_2_usb status
  bluetooth_2_usb.service - Bluetooth to USB HID proxy
     Loaded: loaded (/home/user/bluetooth_2_usb/bluetooth_2_usb.service; enabled; vendor preset: enabled)
     Active: active (running) since Fri 2023-09-15 09:12:34 BST; 3h 26min ago
   Main PID: 43296 (python3)
      Tasks: 1 (limit: 8755)
        CPU: 6.787s
     CGroup: /system.slice/bluetooth_2_usb.service
             └─43296 python3 /usr/bin/bluetooth_2_usb.py --keyboard /dev/input/event2 --mouse /dev/input/event3

   Sep 15 09:12:34 raspberrypi systemd[1]: Started Bluetooth to USB HID proxy.
   Sep 15 09:12:34 raspberrypi python3[43296]: 23-09-15 09:12:34 [INFO] Available output devices: ['/dev/hidg0', '/dev/hidg1']
   Sep 15 09:12:34 raspberrypi python3[43296]: 23-09-15 09:12:34 [INFO] Keyboard (in): device /dev/input/event2, name "AceRK Keyboard", phys "yy:yy:yy:yy:yy:yy"
   Sep 15 09:12:35 raspberrypi python3[43296]: 23-09-15 09:12:35 [INFO] Keyboard (out): /dev/hidg0
   Sep 15 09:12:35 raspberrypi python3[43296]: 23-09-15 09:12:35 [INFO] Mouse (in): device /dev/input/event3, name "AceRK Mouse", phys "xx:xx:xx:xx:xx:xx"
   Sep 15 09:12:36 raspberrypi python3[43296]: 23-09-15 09:12:36 [INFO] Mouse (out): /dev/hidg1
   Sep 15 09:12:36 raspberrypi python3[43296]: 23-09-15 09:12:36 [INFO] Started keyboard event loop
   Sep 15 09:12:36 raspberrypi python3[43296]: 23-09-15 09:12:36 [INFO] Started mouse event loop
   ```
    
# 5. Usage
Connect the power USB port of your Pi (Micro-USB or USB-C) via cable with a USB port on your target device. You should hear the USB connection sound (depending on the target device) and be able to access your target device wirelessly using your Bluetooth keyboard or mouse. 

# 6. Troubleshooting

## 6.1. The Pi keeps rebooting or crashes randomly
This is likely due to the limited power the Pi gets from the host. Try these steps:
- If available, connect your Pi to a USB 3 port on the host (usually blue)
- Try to connect to the Pi via SSH instead of attaching a disply directly and remove any unnecessary peripherals
- Install a light version of your OS on the Pi (without GUI)
- Buy a [USB-C Data/Power Splitter](https://thepihut.com/products/usb-c-data-power-splitter) (or [Micro-USB](https://thepihut.com/products/micro-usb-data-power-splitter) respectively) and draw power from a sufficiently powerful power adaptor (the Pi 4B requires 3A/15W for stable operation!)

## 6.2. The installation was successful, but I don't see any output on the target device 
This could be due to a number of reasons. Try these steps:
- Verify that the service is running:
  ``` bash
  sudo service bluetooth_2_usb status
  ```
- Verify that you specified the correct input devices in `bluetooth_2_usb.service` and that sandbox mode is off (that is no `--sandbox` or `-s` flag)
- Check the log files at `/var/log/bluetooth_2_usb/` for errors 
- Increase log verbosity by appending `-d` to the command in the line starting with `ExecStart=` in `bluetooth_2_usb.service`. 
- Reload and restart service:
  ``` bash
  sudo systemctl daemon-reload
  sudo service bluetooth_2_usb restart
  ```
- When you interact with your Bluetooth devices, you should see debug output in the logs such as:
   ``` bash
   23-09-15 08:57:56 [DEBUG] Received keyboard event: [event at 1694764676.633678, code 04, type 04, val 458756]
   23-09-15 08:57:56 [DEBUG] Received keyboard event: [key event at 1694764676.633678, 30 (KEY_A), down]
   23-09-15 08:57:56 [DEBUG] Converted ecode 30 to HID keycode 4
   ```

## 6.3. After being afk for a while, it stops working 
If the device enters energy saving mode, the Pi may lose connection causing the device `/dev/input/eventX` to become unavailable. Restarting the service should fix this:
```
sudo service bluetooth_2_usb restart
```

You may also consider deactivating energy saving mode, if your device allows. 

## 6.4. I have a different issue 
Here's a few things you could try:
- Reload and restart service:
  ``` bash
  sudo systemctl daemon-reload
  sudo service bluetooth_2_usb restart
  ```
- Reboot Pi
  ``` bash
  sudo reboot 
  ```
- Re-connect the Pi to the host and check that the cable is in good shape 
- Try a different USB port on the host
- Try connecting to a different host 
- Double-check the [Installation instructions](#4-installation)
- For more help, open an [issue](https://github.com/quaxalber/bluetooth_2_usb/issues) in the [GitHub repository](https://github.com/quaxalber/bluetooth_2_usb)

## 6.5. Everything is working, but can it help me with Bitcoin mining? 
Absolutely! [Here's how](https://bit.ly/42BTC). 

# 7. Known issues 

## 7.1. Mouse is crashing
This is likely due to an issue in the upstream libraries. Hang tight and check back later, while this issue is being worked on. 

# 8. Bonus points 
After successfully setting up your Pi as a HID proxy for your Bluetooth devices, you may consider making [Raspberry OS read-only](https://learn.adafruit.com/read-only-raspberry-pi/overview). That helps preventing the SD card from wearing out and the file system from getting corrupted when powering off the Raspberry forcefully.

# 9. Contributing
Contributions are welcome! Please read the [CONTRIBUTING.md](CONTRIBUTING.md) file for guidelines.

# 10. License
This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.

"Bluetooth 2 HID" image [@PixelGordo](https://twitter.com/PixelGordo) is licensed under a [Creative Commons Attribution-NonCommercial 4.0 International License](http://creativecommons.org/licenses/by-nc/4.0/).

![License image.](https://i.creativecommons.org/l/by-nc/4.0/88x31.png)

# 11. Acknowledgments
* [Mike Redrobe](https://github.com/mikerr/pihidproxy) for the idea and the basic code logic and [HeuristicPerson's bluetooth_2_hid](https://github.com/HeuristicPerson/bluetooth_2_hid) based off this.
* [Georgi Valkov](https://github.com/gvalkov) for [python-evdev](https://github.com/gvalkov/python-evdev) making reading input devices a walk in the park. 
* The folks at [Adafruit](https://www.adafruit.com/) for [CircuitPython HID](https://github.com/adafruit/Adafruit_CircuitPython_HID) providing super smooth access to USB gadgets. 
* Special thanks to the open-source community for various other libraries and tools.
