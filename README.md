<!-- omit in toc -->
# Bluetooth to USB

![Bluetooth to USB Overview](https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/assets/overview.png)

Turn a Raspberry Pi into a USB HID bridge for Bluetooth keyboards and mice. To the target host it looks like a normal wired USB keyboard/mouse, so it can work in BIOS, boot menus, installers, kiosks, tablets, game consoles and other environments where Bluetooth is unavailable or unreliable.

## Why people use it

- Use Bluetooth keyboards and mice on hosts that only accept wired USB HID
- Control BIOS, boot menus, installers and KVM targets with the same wireless peripherals you already own
- Leave a Pi attached as a small appliance-like bridge instead of re-pairing each host
- Build read-mostly or read-only Raspberry Pi setups for embedded and unattended installs

## Typical user stories

- "I want my Bluetooth keyboard to work before the OS boots."
- "I want one tiny adapter I can keep on a rack server or retro machine."
- "I want to use my living-room keyboard on devices with poor Bluetooth support."
- "I want a setup other people can install and operate without learning USB gadget internals."

## Features

- Managed installation into `/opt/bluetooth_2_usb`
- systemd-first runtime with configurable flags in `/etc/default/bluetooth_2_usb`
- Auto-discovery, auto-reconnect and optional input grabbing
- Host-oriented HID profiles for compatibility-first behavior
- Diagnostics and smoke tests suitable for issue reports
- Two read-only modes:
  - `easy`: minimal effort, best-effort persistence
  - `persistent`: power-user mode with persistent Bluetooth state

## Requirements

- Raspberry Pi with Bluetooth and USB OTG gadget support
- Recommended boards: Pi Zero W, Pi Zero 2 W, Pi 4B, Pi 5
- Raspberry Pi OS Bookworm or newer
- Python 3.11+

> Raspberry Pi 3B/3B+ do not expose a usable USB device-mode port for this project.

## Install

### One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh | sudo bash
```

As with any `curl | bash` installer, inspect the script before running it if you are not comfortable trusting it blindly. A safer pattern is:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh -o /tmp/bluetooth_2_usb-bootstrap.sh
less /tmp/bluetooth_2_usb-bootstrap.sh
sudo bash /tmp/bluetooth_2_usb-bootstrap.sh
```

After installation:

```bash
sudo reboot
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

### Clone-and-install

```bash
git clone https://github.com/quaxalber/bluetooth_2_usb.git
cd bluetooth_2_usb/scripts
sudo bash install.sh
```

## Choose your mode

| Mode | Best for | Setup effort | Bluetooth persistence |
| --- | --- | --- | --- |
| Normal | Everyday use without a read-only root filesystem | Low | Normal writable system behavior |
| Read-only Easy Mode | Simple appliance-style deployments | Low | Best effort only |
| Read-only Persistent Mode | Embedded and production-like installs | Medium | Supported persistent Bluetooth state |

### Normal mode

Use this if you just want the Pi to bridge Bluetooth input to USB and you do not care about a read-only root filesystem.

### Read-only Easy Mode

Use this if you want a simple appliance-like setup with minimal effort.

- Activates Raspberry Pi OS OverlayFS
- Keeps the boot partition writable
- Stores recovery snapshots of `/etc/machine-id` and `/var/lib/bluetooth` on `/boot`
- Best-effort only for Bluetooth persistence

Recommended command:

```bash
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode easy
```

### Read-only Persistent Mode

Use this if you want reliable Bluetooth identity, pairings and reconnect behavior in read-only operation.

- Activates Raspberry Pi OS OverlayFS
- Stores Bluetooth state on a separate writable ext4 filesystem
- Bind-mounts that persistent state to `/var/lib/bluetooth`
- Intended for power users and production-like setups

Typical flow:

```bash
sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/your-device
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode persistent
sudo reboot
```

## Daily usage

Useful commands:

```bash
bluetooth_2_usb --list_devices
bluetooth_2_usb --validate-env
bluetooth_2_usb --dry-run --debug
```

Most installs use the default service configuration from:

```bash
/etc/default/bluetooth_2_usb
```

Default value:

```bash
BLUETOOTH_2_USB_ARGS="--auto_discover --grab_devices --interrupt_shortcut CTRL+SHIFT+F12 --hid-profile compat"
```

Important runtime options:

- `--auto_discover`: relay readable input devices automatically
- `--grab_devices`: stop the Pi from also consuming local input events
- `--interrupt_shortcut CTRL+SHIFT+F12`: toggle relaying on or off
- `--hid-profile compat|extended`: choose the HID descriptor set
- `--validate-env`: validate gadget prerequisites and exit
- `--dry-run`: run a non-binding diagnostic pass
- `--no-bind`: skip gadget initialization entirely

### HID profiles

- `compat`: default profile; exposes boot-compatible keyboard and mouse interfaces first for maximum host compatibility
- `extended`: keeps the broader keyboard behavior used by earlier releases

## Updating

```bash
sudo /opt/bluetooth_2_usb/scripts/update.sh
```

## Uninstalling

```bash
sudo /opt/bluetooth_2_usb/scripts/uninstall.sh --purge --revert-boot
```

## Diagnostics

Generate a Markdown debug report:

```bash
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact
```

`--redact` masks host identifiers such as the hostname, `machine-id`, `PARTUUID` and Bluetooth MAC addresses with explicit placeholders like `<<REDACTED_HOSTNAME>>`, so the report is safer to share in public issues. Omit it only if you explicitly need raw values for local debugging.

Validate the installation:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

## Read-only guide

### Easy Mode

Recommended flow:

1. Install `bluetooth_2_usb`
2. Pair and trust your Bluetooth devices
3. Confirm everything works normally
4. Enable easy read-only mode
5. Reboot
6. Run `smoke_test.sh --verbose`

Command:

```bash
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode easy
```

Important limitations:

- Easy mode is best effort only
- It does not relocate live Bluetooth state to persistent writable storage
- It keeps recovery snapshots on `/boot`, but `/boot` is not used as the live Bluetooth state store
- It is useful for simple setups and recovery snapshots, not as a strong persistence guarantee

### Persistent Mode

Recommended flow:

1. Install `bluetooth_2_usb`
2. Pair and test your devices in normal mode
3. Prepare a writable ext4 filesystem for persistent Bluetooth state
4. Run the persistent-state setup script
5. Enable persistent read-only mode
6. Reboot
7. Run `smoke_test.sh --verbose`
8. Verify reconnect behavior after a reboot or power-cycle

Prepare persistent Bluetooth state:

```bash
sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/your-device
```

Enable persistent read-only mode:

```bash
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode persistent
```

Default persistent layout:

- Persistent mount: `/mnt/b2u-persist`
- Bluetooth state dir: `/mnt/b2u-persist/bluetooth`
- Bind mount target: `/var/lib/bluetooth`

Important notes:

- b2u does not repartition your disk for you
- The persistent device/filesystem must be provided by the user
- ext4 is the supported filesystem for persistent Bluetooth state
- The boot partition is intentionally not used as the live Bluetooth state store
- `smoke_test.sh --verbose` should report `Read-only mode: persistent` and `Bluetooth state persistent: yes`

### Disable read-only mode

```bash
sudo /opt/bluetooth_2_usb/scripts/disable_readonly_overlayfs.sh
```

This disables OverlayFS again. Persistent Bluetooth-state configuration is intentionally kept in place.

## Troubleshooting

### No UDC detected

- Reboot after installation
- Check `dtoverlay=dwc2` in `config.txt`
- Check `modules-load=` in `cmdline.txt`
- Verify `ls /sys/class/udc`

### Service starts but host does not react

- Verify that you are connected to the correct OTG-capable port
- Try another cable
- Run `bluetooth_2_usb --validate-env`
- Review `journalctl -u bluetooth_2_usb.service -n 100 --no-pager`

### Windows host issues

- Use the default `compat` HID profile first
- Re-test after reconnecting the USB cable to the host
- Include `debug.sh --redact` output when opening an issue

### Read-only mode issues

- Check which mode you are actually using:
  - `easy`
  - `persistent`
- In persistent mode, verify that `/var/lib/bluetooth` is a separate bind mount
- Verify `/etc/machine-id` before and after reboot
- Treat easy mode as a convenience workflow, not as a persistence guarantee

## Technical details

`install.sh` performs these steps:

1. Detect the correct boot files under `/boot/firmware` or `/boot`
2. Normalize `dtoverlay=dwc2` and `modules-load=` configuration
3. Install the project into `/opt/bluetooth_2_usb`
4. Create a virtual environment at `/opt/bluetooth_2_usb/venv`
5. Install the Python package into that venv
6. Install `bluetooth_2_usb.service` into `/etc/systemd/system/`
7. Install a convenience wrapper at `/usr/local/bin/bluetooth_2_usb`

Persistent read-only mode additionally installs:

- a mount unit for the persistent writable storage
- `var-lib-bluetooth.mount` to bind persistent Bluetooth state to `/var/lib/bluetooth`
- a `bluetooth.service` drop-in so BlueZ waits for the bind mount

`smoke_test.sh` distinguishes between:

- `disabled`
- `easy`
- `persistent`

In `persistent` mode it fails if Bluetooth state is not actually mounted persistently.

## Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -U pip setuptools wheel
pip install -e .
```

```bash
python -m bluetooth_2_usb --list_devices
python -m bluetooth_2_usb --dry-run --debug
```
