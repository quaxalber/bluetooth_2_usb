<!-- omit in toc -->
# Bluetooth-2-USB

![Bluetooth-2-USB Overview](https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/assets/overview.png)

---

<div align="center">

[![CI](https://github.com/quaxalber/bluetooth_2_usb/actions/workflows/ci.yml/badge.svg)](https://github.com/quaxalber/bluetooth_2_usb/actions/workflows/ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/quaxalber/bluetooth_2_usb?display_name=tag&sort=semver)](https://github.com/quaxalber/bluetooth_2_usb/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![Raspberry Pi OS](https://img.shields.io/badge/Raspberry%20Pi%20OS-Bookworm%2B-C51A4A)](https://www.raspberrypi.com/software/)

</div>

---

Turn a Raspberry Pi into a USB HID bridge for Bluetooth keyboards and mice.

To the target host, the Pi appears as a standard wired USB keyboard and mouse.
That makes Bluetooth-2-USB useful in BIOS and boot menus, installers, KVM
switches, kiosks, tablets, retro systems, consoles, and other environments
where Bluetooth is unavailable or inconvenient.

## Highlights

- Bluetooth keyboard and mouse input relayed as standard USB HID
- Auto-discovery and auto-reconnect for supported input devices
- Optional input grabbing so the Pi does not also consume local keyboard/mouse
  events
- HID compatibility profiles for stricter hosts
- A small diagnosis surface built around `--validate-env`, `smoke_test.sh`, and
  `debug.sh`
- Optional persistent read-only operation with writable Bluetooth state on a
  separate ext4 filesystem

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
> - Raspberry Pi 3 models include Bluetooth, but they do not expose a suitable
>   USB device-mode port for this project.
> - On Pi 4B and Pi 5, the OTG-capable port is the USB-C power port.
> - On Pi Zero boards, the OTG-capable port is the USB data port, not the
>   power-only port.

## Quick start

### 1. Clone to the managed install path

The supported deployment model is a normal Git checkout at
`/opt/bluetooth_2_usb`.

```bash
sudo git clone https://github.com/quaxalber/bluetooth_2_usb.git /opt/bluetooth_2_usb
cd /opt/bluetooth_2_usb
```

### 2. Install

```bash
sudo ./scripts/install.sh
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

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh
```

### 6. Connect the Pi to the target host

#### Raspberry Pi 4B / 5

Connect the Pi's USB-C power port to the target host. That is the OTG-capable
port required for USB gadget mode.

#### Raspberry Pi Zero W / Zero 2 W

Connect the Pi's USB data port to the target host.

If possible, power the Pi from a separate stable power supply using the
power-only port. That usually improves stability.

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

Advanced runtime override:

- Set `BLUETOOTH_2_USB_UDC_PATH=/sys/class/udc/.../state` in the service
  environment file only if you need to pin UDC detection on a system with
  multiple controllers.

## Common CLI options

- `--auto_discover`
  Relay readable input devices automatically.
- `--grab_devices`
  Prevent the Pi from also consuming local input events.
- `--interrupt_shortcut CTRL+SHIFT+F12`
  Toggle relaying on or off so you can temporarily use the Pi locally.
- `--device_ids ...`
  Restrict relaying to specific input devices by event path, MAC address, or
  partial name.
- `--hid-profile compat|extended`
  Select the USB HID descriptor profile.
- `--validate-env`
  Validate gadget runtime prerequisites and exit.

Concrete `--device_ids` examples:

- One exact event node:
  `bluetooth_2_usb --device_ids /dev/input/event4`
- One Bluetooth MAC address:
  `bluetooth_2_usb --device_ids A1:B2:C3:D4:E5:F6`
- One device-name fragment:
  `bluetooth_2_usb --device_ids logi`
- A mixed filter list:
  `bluetooth_2_usb --device_ids '/dev/input/event4,A1:B2:C3:D4:E5:F6,MX Keys'`

The matcher accepts event paths, Bluetooth MAC addresses, and case-insensitive
name fragments in the same comma-separated list.

## Day-to-day usage

List available devices:

```bash
bluetooth_2_usb --list_devices
```

Validate the runtime environment:

```bash
bluetooth_2_usb --validate-env
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

Update the managed checkout and re-apply the system integration:

```bash
cd /opt/bluetooth_2_usb
sudo git pull --ff-only
sudo ./scripts/install.sh
```

This keeps the operational model simple:

- Git decides which commit or branch you are on.
- `install.sh` reapplies boot config, the virtual environment, the service, and
  the wrapper for the current checkout.

## Uninstalling

Remove the managed service, wrapper, env files, and persistent Bluetooth-state
mount integration:

```bash
sudo /opt/bluetooth_2_usb/scripts/uninstall.sh
```

The checkout at `/opt/bluetooth_2_usb` is intentionally left in place.

## Diagnostics

Quick health check:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

Deeper issue report with a live foreground debug run:

```bash
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
```

`debug.sh` temporarily stops the service if it is running, launches a
foreground Bluetooth-2-USB `--debug` session, and restores the service
afterward. Host identifiers such as the hostname, `machine-id`, UUIDs,
PARTUUIDs, and Bluetooth MAC addresses are redacted automatically in the saved
report.

## Persistent read-only operation

Bluetooth-2-USB supports the normal writable mode and one persistent read-only
mode for appliance-like deployments.

### What persistent read-only mode does

- enables Raspberry Pi OS OverlayFS for the root filesystem
- keeps Bluetooth state on a separate writable ext4 filesystem
- bind-mounts that Bluetooth state to `/var/lib/bluetooth`

### What it does not do

- create the ext4 filesystem for you
- repartition your SD card automatically
- make Bluetooth state persistent without separate writable storage

### Persistent read-only flow

1. Install Bluetooth-2-USB and confirm normal operation first.
2. Prepare an ext4 filesystem for Bluetooth state.
3. Run:

```bash
sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/YOUR-PARTITION
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh
sudo reboot
```

After reboot:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

> [!IMPORTANT]
> Replace `/dev/YOUR-PARTITION` with the real ext4 partition you intend to use.
> Double-check the target with `lsblk -f` before formatting or enabling
> persistent Bluetooth state.

### Preparing the persistent filesystem

Identify the target device:

```bash
lsblk -f
```

If needed, create ext4 on the real spare partition:

```bash
sudo mkfs.ext4 -L B2U_PERSIST /dev/YOUR-PARTITION
```

### Disabling read-only mode

```bash
sudo /opt/bluetooth_2_usb/scripts/disable_readonly_overlayfs.sh
sudo reboot
```

## Troubleshooting

### The service does not start

```bash
bluetooth_2_usb --validate-env
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

### The Pi does not appear as a USB gadget

Check the boot overlay and modules:

```bash
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/firmware/config.txt 2>/dev/null || \
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/config.txt
cat /boot/firmware/cmdline.txt 2>/dev/null || cat /boot/cmdline.txt
```

Then reboot after fixing the install:

```bash
cd /opt/bluetooth_2_usb
sudo ./scripts/install.sh
sudo reboot
```

### You need a report for an issue

```bash
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
```

## Script reference

All managed deployment scripts live in `/opt/bluetooth_2_usb/scripts/` after
installation.

### `install.sh`

Apply the current checkout in `/opt/bluetooth_2_usb` to the managed install.
This is the main deployment entrypoint for first install and for later
re-application after `git pull`.

| Aspect | Value |
| --- | --- |
| Run from | `/opt/bluetooth_2_usb` |
| Purpose | Patch boot config, rebuild the managed virtualenv, install the service, and refresh the wrapper |
| Public options | none |
| Typical invocation | `sudo ./scripts/install.sh` |

### `uninstall.sh`

Remove the managed system integration while deliberately leaving the checkout in
place for inspection or later reuse.

| Aspect | Value |
| --- | --- |
| Run from | anywhere |
| Purpose | Remove the service, wrapper, env files, and persistent Bluetooth-state mount integration |
| Public options | none |
| Typical invocation | `sudo /opt/bluetooth_2_usb/scripts/uninstall.sh` |

### `debug.sh`

Collect a deeper redacted diagnostics bundle when `smoke_test.sh` is not enough.
It records service, boot, mount, and runtime state, then runs a bounded live
foreground debug session.

| Aspect | Value |
| --- | --- |
| Run from | anywhere |
| Purpose | Produce a redacted Markdown report for issue triage |
| Public options | `--duration <sec>` |
| Typical invocation | `sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10` |

### `smoke_test.sh`

Run the fast health check for the supported managed deployment. This is the
first script to use after install, reboot, update, or read-only changes.

| Aspect | Value |
| --- | --- |
| Run from | anywhere |
| Purpose | Verify boot config, UDC visibility, service state, CLI validation, and persistent Bluetooth state wiring |
| Public options | `--verbose` |
| Typical invocation | `sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose` |

### `setup_persistent_bluetooth_state.sh`

Prepare the writable ext4-backed storage for `/var/lib/bluetooth` before
enabling OverlayFS.

| Aspect | Value |
| --- | --- |
| Run from | anywhere |
| Purpose | Configure, mount, seed, and bind-mount persistent Bluetooth state |
| Public options | `--device <path>` |
| Typical invocation | `sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/YOUR-PARTITION` |

### `enable_readonly_overlayfs.sh`

Switch Raspberry Pi OS into persistent read-only operation after the writable
Bluetooth-state mount has already been prepared.

| Aspect | Value |
| --- | --- |
| Run from | anywhere |
| Purpose | Enable OverlayFS while preserving writable Bluetooth state on the persistent mount |
| Public options | none |
| Typical invocation | `sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh` |

### `disable_readonly_overlayfs.sh`

Return the system to normal writable mode while keeping the persistent
Bluetooth-state configuration available.

| Aspect | Value |
| --- | --- |
| Run from | anywhere |
| Purpose | Disable OverlayFS and keep the persistent Bluetooth-state layout intact |
| Public options | none |
| Typical invocation | `sudo /opt/bluetooth_2_usb/scripts/disable_readonly_overlayfs.sh` |

## Managed paths

| Path | Purpose |
| --- | --- |
| `/opt/bluetooth_2_usb` | Managed installation root |
| `/opt/bluetooth_2_usb/venv` | Managed virtual environment |
| `/etc/default/bluetooth_2_usb` | Optional runtime arguments for the service |
| `/etc/default/bluetooth_2_usb_readonly` | Persistent read-only mode configuration |
| `/var/log/bluetooth_2_usb` | Script and report output |
| `/mnt/b2u-persist` | Default persistent mount target |
| `/mnt/b2u-persist/bluetooth` | Default persistent Bluetooth state directory |
| `/etc/systemd/system/bluetooth_2_usb.service` | Installed service unit |

## Development and release

Contributor workflow details live in [CONTRIBUTING.md](CONTRIBUTING.md).
Release tagging and versioning rules are documented in
[docs/release-versioning-policy.md](docs/release-versioning-policy.md).

## License

This project is licensed under the [MIT License](LICENSE).

The overview image is by Laura T. and is licensed under
[CC BY-NC 4.0](http://creativecommons.org/licenses/by-nc/4.0/).

## Acknowledgments

- [Mike Redrobe](https://github.com/mikerr/pihidproxy) for the original Pi HID
  proxy idea
- [HeuristicPerson](https://github.com/HeuristicPerson/bluetooth_2_hid) for
  related prior art
- [Georgi Valkov](https://github.com/gvalkov) for
  [`python-evdev`](https://github.com/gvalkov/python-evdev)
- [Adafruit](https://www.adafruit.com/) for CircuitPython HID and Blinka, which
  helped make USB gadget access much smoother
- Everyone who tests the project on real hardware and reports what works, what
  fails, and how to improve it

---

<div align="center">

👀 Written by Eyes<br>
🤖 Assisted by Technology and AI<br>
☕ Powered by Coffee<br>
🫶 Developed with Love

</div>
