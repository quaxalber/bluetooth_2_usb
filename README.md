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

| Script | Purpose | Public options |
| --- | --- | --- |
| `install.sh` | Apply the current checkout in `/opt/bluetooth_2_usb` to the managed install, including boot config, virtualenv, service, and wrapper. | none |
| `uninstall.sh` | Remove the managed service integration while leaving the checkout in place. | none |
| `debug.sh` | Collect a redacted Markdown debug report with service state, boot config, mount state, dmesg, CLI validation, and a live foreground debug run. | `--duration <sec>` |
| `smoke_test.sh` | Perform a quick installation and runtime health check for boot config, UDC, service state, environment validation, and persistent Bluetooth state. | `--verbose` |
| `setup_persistent_bluetooth_state.sh` | Configure and activate the writable ext4 mount and bind mount for `/var/lib/bluetooth`. | `--device <path>` |
| `enable_readonly_overlayfs.sh` | Enable Raspberry Pi OS OverlayFS after persistent Bluetooth state has already been prepared. | none |
| `disable_readonly_overlayfs.sh` | Disable Raspberry Pi OS OverlayFS while leaving the persistent Bluetooth-state mount configuration in place. | none |

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
