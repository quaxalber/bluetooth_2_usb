<!-- omit in toc -->
# Bluetooth to USB

![Bluetooth to USB Overview](https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/assets/overview.png)

Turn a Raspberry Pi into a USB HID bridge for Bluetooth keyboards and mice.

To the target host, the Pi appears as a standard wired USB keyboard and mouse. That makes Bluetooth to USB useful in BIOS and boot menus, installers, KVM switches, kiosks, tablets, retro systems, consoles, and other environments where Bluetooth is unavailable, unsupported, or unreliable.

Bluetooth to USB is designed to be practical for both hobby setups and appliance-like deployments: install it, pair your devices, connect the Pi to the target host, and use your Bluetooth peripherals as if they were wired.

## Why people use it

- Use Bluetooth keyboards and mice on hosts that only accept wired USB HID
- Control BIOS, boot menus, recovery environments, and installers with the same wireless peripherals you already own
- Keep one small Pi attached to a target system instead of re-pairing each host
- Build durable read-mostly or read-only Raspberry Pi setups for embedded or unattended use

## Highlights

- Managed installation into `/opt/bluetooth_2_usb`
- systemd-first runtime with configuration in `/etc/default/bluetooth_2_usb`
- Auto-discovery and auto-reconnect for supported input devices
- Optional input grabbing so the Pi does not also consume local keyboard/mouse events
- HID compatibility profiles for hosts with stricter USB expectations
- Diagnostics and smoke tests designed for issue reports and field debugging
- Optional read-only modes for more appliance-like deployments

## Requirements

- A Raspberry Pi with:
  - Bluetooth support
  - USB OTG gadget support
- Recommended boards:
  - Raspberry Pi Zero W
  - Raspberry Pi Zero 2 W
  - Raspberry Pi 4B
  - Raspberry Pi 5
- Raspberry Pi OS Bookworm or newer
- Internet access during installation
- A Bluetooth keyboard, mouse, or both
- A USB cable that supports data, not power only

> [!NOTE]
> Raspberry Pi 3 models include Bluetooth, but they do not expose a suitable USB device-mode port for this project.

> [!NOTE]
> On Pi 4B and Pi 5, the OTG-capable port is the USB-C power port. On Pi Zero boards, the OTG-capable port is the USB data port, not the power-only port.

## Quick start

### 1. Prepare the Pi

Install Raspberry Pi OS Bookworm or newer, connect the Pi to the network, and optionally enable SSH if you plan to administer it remotely.

### 2. Install Bluetooth to USB

Fastest path:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh | sudo bash
```

Safer path if you prefer to inspect the installer first:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh -o /tmp/bluetooth_2_usb-bootstrap.sh
less /tmp/bluetooth_2_usb-bootstrap.sh
sudo bash /tmp/bluetooth_2_usb-bootstrap.sh
```

### 3. Reboot

```bash
sudo reboot
```

### 4. Pair and trust your Bluetooth devices

You can pair devices through the desktop UI or with `bluetoothctl`.

Example CLI flow:

```bash
bluetoothctl
scan on
```

Wait for your device to appear, then trust, pair, and connect it:

```bash
trust A1:B2:C3:D4:E5:F6
pair A1:B2:C3:D4:E5:F6
connect A1:B2:C3:D4:E5:F6
exit
```

> [!NOTE]
> Replace `A1:B2:C3:D4:E5:F6` with your device's Bluetooth MAC address.

### 5. Verify the installation

Check the service:

```bash
sudo systemctl status bluetooth_2_usb.service
```

You want to see `active (running)`.

Run the smoke test:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

### 6. Connect the Pi to the target host

#### Raspberry Pi 4B / 5

Connect the Pi's **USB-C power port** to the target host. That is the OTG-capable port required for USB gadget mode.

Do **not** use the Pi's USB-A host ports for the connection to the target system.

#### Raspberry Pi Zero / Zero 2 W

Connect the Pi's **USB data port** to the target host.

If possible, power the Pi from a separate stable power supply using the power-only port. That usually improves stability.

## Installation options

### Bootstrap installer

The bootstrap script downloads a repository archive and then runs the managed installer:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh | sudo bash
```

Useful options:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh | sudo bash -s -- --branch main --no-reboot
```

### Clone-and-install

```bash
git clone https://github.com/quaxalber/bluetooth_2_usb.git
cd bluetooth_2_usb
sudo ./scripts/install.sh
```

### Install a specific branch or tag

Useful when testing a feature branch or release candidate:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh | sudo bash -s -- --branch YOUR-BRANCH-OR-TAG
```

## Configuration

The service reads optional runtime flags from:

```bash
/etc/default/bluetooth_2_usb
```

Default value:

```bash
BLUETOOTH_2_USB_ARGS="--auto_discover --grab_devices --interrupt_shortcut CTRL+SHIFT+F12 --hid-profile compat"
```

After editing that file, restart the service:

```bash
sudo systemctl restart bluetooth_2_usb.service
```

### Common runtime options

- `--auto_discover`  
  Relay readable input devices automatically.

- `--grab_devices`  
  Prevent the Pi from also consuming local input events.

- `--interrupt_shortcut CTRL+SHIFT+F12`  
  Toggle relaying on or off so you can temporarily use the Pi locally.

- `--device_ids ...`  
  Restrict relaying to specific input devices by event path, MAC address, or partial name.

- `--hid-profile compat|extended`  
  Select the USB HID descriptor profile.

- `--validate-env`  
  Validate gadget runtime prerequisites and exit.

- `--dry-run`  
  Run environment validation without binding the USB gadgets.

- `--no-bind`  
  Skip gadget initialization and perform diagnostic validation only.

### HID profiles

- `compat`  
  Default. Prioritizes host compatibility and is the right first choice for most users.

- `extended`  
  Keeps the broader behavior used by earlier releases and may help when you specifically want the older profile behavior.

## Day-to-day usage

List available devices:

```bash
bluetooth_2_usb --list_devices
```

Validate the runtime environment:

```bash
bluetooth_2_usb --validate-env
```

Run a non-binding diagnostic pass:

```bash
bluetooth_2_usb --dry-run --debug
```

Inspect recent service logs:

```bash
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

Follow logs live:

```bash
journalctl -u bluetooth_2_usb.service -f
```

## Updating

Update the installed checkout and recreate the virtual environment:

```bash
sudo /opt/bluetooth_2_usb/scripts/update.sh
```

## Uninstalling

Remove the service and helper files:

```bash
sudo /opt/bluetooth_2_usb/scripts/uninstall.sh
```

Remove the installation directory as well:

```bash
sudo /opt/bluetooth_2_usb/scripts/uninstall.sh --purge
```

Also revert managed boot configuration changes:

```bash
sudo /opt/bluetooth_2_usb/scripts/uninstall.sh --purge --revert-boot
```

## Diagnostics

Generate a Markdown debug report:

```bash
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact
```

`--redact` masks host identifiers such as the hostname, `machine-id`, UUIDs, PARTUUIDs, and Bluetooth MAC addresses. It is the recommended mode for reports shared in public issues.

Run a health check:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

## Read-only modes

Bluetooth to USB supports two OverlayFS-based operating modes for users who want a more appliance-like Raspberry Pi deployment.

| Mode       | Best for                                     | Setup effort | Bluetooth persistence                |
| ---------- | -------------------------------------------- | ------------ | ------------------------------------ |
| Normal     | Everyday use on a writable system            | Low          | Standard writable behavior           |
| Easy       | Simple read-mostly deployments               | Low          | Best effort only                     |
| Persistent | Embedded or production-like read-only setups | Medium       | Supported persistent Bluetooth state |

### Easy mode

Easy mode enables Raspberry Pi OS OverlayFS and stores recovery snapshots on the boot partition.

Use it when you want a simpler read-only setup and understand that Bluetooth persistence is best effort only.

Recommended flow:

1. Install Bluetooth to USB
2. Pair and trust your Bluetooth devices
3. Confirm normal operation first
4. Enable easy mode
5. Reboot
6. Run the smoke test again

Enable it with:

```bash
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode easy
```

> [!IMPORTANT]
> Easy mode is convenient, but it does **not** make `/var/lib/bluetooth` persist on a dedicated writable mount. Treat it as best effort, not as a hard persistence guarantee.

### Persistent mode

Persistent mode is the right choice if you need stable Bluetooth identity, pairings, and reconnect behavior while the root filesystem is read-only.

It uses a separate writable ext4 filesystem for Bluetooth state and bind-mounts it to `/var/lib/bluetooth`.

Recommended flow:

1. Install Bluetooth to USB
2. Pair and verify your devices in normal mode
3. Prepare a writable ext4 filesystem
4. Configure persistent Bluetooth state
5. Enable persistent read-only mode
6. Reboot
7. Run the smoke test
8. Verify reconnect behavior after reboot or power loss

Prepare persistent Bluetooth state:

Replace `/dev/your-device` with the path to your writable ext4 filesystem, for example `/dev/sda1` or `/dev/mmcblk0p3`:

```bash
sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/sda1
```

Enable persistent mode:

```bash
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode persistent
```

Default layout:

- Persistent mount: `/mnt/b2u-persist`
- Bluetooth state directory: `/mnt/b2u-persist/bluetooth`
- Bind mount target: `/var/lib/bluetooth`

> [!IMPORTANT]
> Persistent mode expects an ext4 filesystem that you provide. The project does not repartition your disk automatically.

### Disable read-only mode

```bash
sudo /opt/bluetooth_2_usb/scripts/disable_readonly_overlayfs.sh
```

## Troubleshooting

### The Pi reboots, crashes, or behaves unstably

This is often a power issue.

Try the following:

- Use a stable external power supply where possible
- Prefer Raspberry Pi OS Lite for lower overhead
- Remove unnecessary peripherals from the Pi
- On Pi 4B/5, consider a USB-C data/power splitter if the host cannot supply enough power
- On Pi Zero boards, power the board separately and use the data port only for the host connection

### The service is running, but the target host does not react

Check the basics first:

```bash
sudo systemctl status bluetooth_2_usb.service
bluetooth_2_usb --validate-env
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

Then verify:

- You are connected to the correct OTG-capable port
- The USB cable supports data
- The Bluetooth devices are paired, trusted, connected, and not blocked
- The target host is seeing a new USB device
- Restarting the service or reconnecting the cable changes anything

Useful command:

```bash
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

### A Bluetooth device keeps disconnecting or flapping

This can happen when the same peripheral has stale pairings or cache entries across multiple hosts.

A common recovery flow is:

```bash
bluetoothctl
power off
power on
block A1:B2:C3:D4:E5:F6
remove A1:B2:C3:D4:E5:F6
scan on
trust A1:B2:C3:D4:E5:F6
pair A1:B2:C3:D4:E5:F6
connect A1:B2:C3:D4:E5:F6
exit
```

If the issue persists, run `sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact` and open an issue with the output.

### Read-only mode is enabled, but reconnect behavior is unreliable

Confirm which mode you are using:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

Things to verify:

- `easy` mode is only best effort
- `persistent` mode should show Bluetooth state as persistent
- `/var/lib/bluetooth` should be a bind mount in persistent mode
- `/etc/machine-id` should remain stable

### Need help?

Please open an issue and include:

- Pi model
- Raspberry Pi OS version
- Kernel version
- Target host type
- Exact commands or scripts used
- Output from `smoke_test.sh --verbose`
- Output from `debug.sh --duration 10 --redact`

## Contributing

Contributions are welcome, including documentation improvements, bug reports, hardware validation, and code changes.

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

The overview image is by Laura T. and is licensed under [CC BY-NC 4.0](http://creativecommons.org/licenses/by-nc/4.0/).

## Acknowledgments

- [Mike Redrobe](https://github.com/mikerr/pihidproxy) for the original Pi HID proxy idea
- [HeuristicPerson](https://github.com/HeuristicPerson/bluetooth_2_hid) for related prior art
- [Georgi Valkov](https://github.com/gvalkov) for [`python-evdev`](https://github.com/gvalkov/python-evdev)
- [Adafruit](https://www.adafruit.com/) for CircuitPython HID and Blinka, which helped make USB gadget access much smoother
- Everyone who tests the project on real hardware and reports what works, what fails, and how to improve it
