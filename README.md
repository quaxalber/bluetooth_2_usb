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

If `git` is missing, which is common on a minimal Raspberry Pi OS Lite image,
install it first:

```bash
sudo apt update
sudo apt install -y git
```

```bash
sudo git clone https://github.com/quaxalber/bluetooth_2_usb.git /opt/bluetooth_2_usb
```

### 2. Install

```bash
sudo /opt/bluetooth_2_usb/scripts/install.sh
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

## CLI reference

Use these runtime flags in `BLUETOOTH_2_USB_ARGS` or when running the CLI
manually.

| Argument | Explanation / Example |
| --- | --- |
| `--device_ids DEVICE_IDS, -i DEVICE_IDS` | Comma-separated identifiers for the devices to relay. Each identifier may be an event path, a Bluetooth MAC address, or a case-insensitive name fragment. The matcher accepts all three kinds in the same comma-separated list. Default: none. Examples: `-i /dev/input/event4`, `-i A1:B2:C3:D4:E5:F6`, `-i logi`, `-i '/dev/input/event4,A1:B2:C3:D4:E5:F6,MX Keys'`. |
| `--auto_discover, -a` | Relay all readable input devices automatically. Good default for appliance-style setups where you do not want to curate a static device list. |
| `--grab_devices, -g` | Grab the selected input devices so the Pi no longer consumes their local events. |
| `--interrupt_shortcut INTERRUPT_SHORTCUT, -s INTERRUPT_SHORTCUT` | Plus-separated key chord that toggles relaying on and off at runtime. Default: none, feature disabled. Example: `-s CTRL+SHIFT+F12`. |
| `--list_devices, -l` | List readable input devices and exit without starting the relay. Useful before setting `DEVICE_IDS`. |
| `--log_to_file, -f` | Add file logging in addition to stdout logging. |
| `--log_path LOG_PATH, -p LOG_PATH` | Override the path used with `--log_to_file`. Default: `/var/log/bluetooth_2_usb/bluetooth_2_usb.log`. Example: `-p /tmp/bluetooth_2_usb.log`. |
| `--debug, -d` | Increase log verbosity for manual troubleshooting. |
| `--version, -v` | Print the installed Bluetooth-2-USB version and exit. |
| `--validate-env` | Validate gadget runtime prerequisites and exit. On non-gadget systems this is expected to fail fast and report the missing prerequisites. |
| `--hid-profile PROFILE` | USB HID profile to expose. Default: `compat`. Supported values: `compat`, `extended`. Example: `--hid-profile extended`. |
| `--help, -h` | Show the built-in CLI help and exit. |

## Day-to-day usage

List available devices:

```bash
bluetooth_2_usb -l
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
sudo git -C /opt/bluetooth_2_usb pull --ff-only
sudo /opt/bluetooth_2_usb/scripts/install.sh
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

If `--validate-env` reports `configfs: missing` or `udc: missing`, that usually
means you are either not on a Pi gadget-capable system or the Pi has not yet
booted with the expected gadget configuration.

### The Pi does not appear as a USB gadget

Check the boot overlay and modules:

```bash
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/firmware/config.txt 2>/dev/null || \
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/config.txt
cat /boot/firmware/cmdline.txt 2>/dev/null || cat /boot/cmdline.txt
```

Interpret those checks conservatively:

- `dtoverlay=dwc2` in `config.txt` should be present.
- `modules-load=` in `cmdline.txt` should still load `libcomposite`, and may
  also include `dwc2` on kernels where `dwc2` is built as a module.
- On newer 64-bit Bookworm and aarch64 kernels, `CONFIG_USB_DWC2=y` often means
  `dwc2` is built into the kernel. In that case, the absence of a separate
  loadable `dwc2` module is normal and not itself a failure.
- Treat missing USB gadget support as the problem, not merely the absence of a
  loadable module: if `CONFIG_USB_DWC2=y` is present, built-in `dwc2` is fine;
  otherwise make sure `dtoverlay=dwc2` is set and that `dwc2` is loaded on
  kernels that require it as a module.

Then reboot after fixing the install:

```bash
sudo /opt/bluetooth_2_usb/scripts/install.sh
sudo reboot
```

### Specific devices are not being relayed

Check what the runtime can actually see:

```bash
bluetooth_2_usb -l
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
```

Then verify that `DEVICE_IDS` really matches what the runtime reports. Matching
is based on event path, Bluetooth MAC address, or case-insensitive device-name
fragment, so stale event numbers or slightly wrong name fragments are common
operator mistakes.

If the service looks healthy but the target host still does not react, also
check the physical path:

- make sure the Pi is connected through the OTG-capable port, not a normal
  host-only USB port
- make sure the USB cable carries data, not only power
- on Pi Zero boards, prefer separate stable power and use only the data port
  for the host connection
- on Pi 4B and Pi 5, try a different USB-C cable or a different host port
- confirm the service is actually active with
  `systemctl is-active bluetooth_2_usb.service`
- inspect logs with `journalctl -u bluetooth_2_usb.service -n 100 --no-pager`
- after boot-config changes, rerun
  `sudo /opt/bluetooth_2_usb/scripts/install.sh` and reboot
  before concluding the relay path is broken

### Persistent read-only mode does not keep Bluetooth pairings

Verify that the writable state is actually mounted where expected:

```bash
findmnt /var/lib/bluetooth
findmnt /mnt/b2u-persist
grep '^B2U_' /etc/default/bluetooth_2_usb_readonly
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
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

### `uninstall.sh`

Remove the managed system integration while deliberately leaving the checkout in
place for inspection or later reuse.

### `debug.sh`

Collect a deeper redacted diagnostics bundle when `smoke_test.sh` is not enough.
It records service, boot, mount, and runtime state, then runs a bounded live
foreground debug session.

| Argument | Explanation / Example |
| --- | --- |
| `--duration DURATION_SEC` | Limit the live foreground debug run. Default: unbounded until interrupted. Example: `sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10`. |

### `smoke_test.sh`

Run the fast health check for the supported managed deployment. This is the
first script to use after install, reboot, update, or read-only changes.

| Argument | Explanation / Example |
| --- | --- |
| `--verbose` | Print the fuller health-check output instead of the compact pass/fail view. Default: disabled. Example: `sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose`. |

### `setup_persistent_bluetooth_state.sh`

Prepare the writable ext4-backed storage for `/var/lib/bluetooth` before
enabling OverlayFS.

| Argument | Explanation / Example |
| --- | --- |
| `--device DEVICE_PATH` | Required writable ext4 device or partition to mount at the persistent state path. No default. Example: `sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/mmcblk0p3`. |

### `enable_readonly_overlayfs.sh`

Switch Raspberry Pi OS into persistent read-only operation after the writable
Bluetooth-state mount has already been prepared.

### `disable_readonly_overlayfs.sh`

Return the system to normal writable mode while keeping the persistent
Bluetooth-state configuration available.

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
