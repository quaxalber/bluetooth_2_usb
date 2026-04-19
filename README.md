<!-- omit in toc -->
# Bluetooth-2-USB

![Bluetooth-2-USB Overview](https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/assets/overview.png)

Use your Bluetooth keyboard and mouse where Bluetooth usually stops being
helpful.

Bluetooth-2-USB turns a Raspberry Pi into a USB HID bridge for Bluetooth
keyboards and mice. To the target host, the Pi appears as a standard wired USB
keyboard and mouse.

That makes it handy for setups where Bluetooth is unavailable, unsupported, or
simply inconvenient, such as BIOS and boot menus, installers, kiosks, tablets,
retro systems, consoles, and other constrained hosts.

## Quick start

This is the quickest supported path to a working setup.

### 1. Clone the project to the managed install path

```bash
sudo apt update && sudo apt install -y git
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

### 4. Pair your Bluetooth device

```bash
bluetoothctl
power on
scan on
trust A1:B2:C3:D4:E5:F6
pair A1:B2:C3:D4:E5:F6
connect A1:B2:C3:D4:E5:F6
exit
```

Replace `A1:B2:C3:D4:E5:F6` with the real Bluetooth MAC address.

### 5. Verify the installation

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke.sh
```

### 6. Connect the Pi to the target host

- Pi 4B / 5: use the USB-C power port
- Pi Zero W / Zero 2 W: use the USB data port

## Requirements

You need a Raspberry Pi with both Bluetooth support and a USB OTG-capable
device-mode port. For most users, the practical choices are Pi Zero W, Zero 2
W, 4B, or 5.

- Raspberry Pi Zero W, Zero 2 W, 4B, or 5
- Raspberry Pi OS Bookworm or newer
- Internet access during installation
- Bluetooth keyboard, mouse, or both
- USB cable that supports data

Notes:
- Pi 3 models include Bluetooth, but they do not expose a suitable device-mode
  port for this project.
- On Pi Zero boards, the OTG-capable port is the USB data port, not the
  power-only port.

## Day-to-day usage

List available devices:

```bash
bluetooth_2_usb -l
```

Validate the runtime environment:

```bash
bluetooth_2_usb --validate-env
```

Restart the service after changing runtime config:

```bash
sudo systemctl restart bluetooth_2_usb.service
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

```bash
sudo /opt/bluetooth_2_usb/scripts/update.sh
```

## Uninstalling

```bash
sudo /opt/bluetooth_2_usb/scripts/uninstall.sh
```

## Diagnostics

For most issues, start with the two built-in diagnostics:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
```

`smoke.sh` is the quick health gate. `debug.sh` collects a fuller redacted
snapshot and can run a short bounded foreground debug session. If you need the
next steps after those checks, use [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Persistent read-only operation

For the supported appliance-style read-only workflow, use
[docs/persistent-readonly.md](docs/persistent-readonly.md).

## Host wake from suspend

Wake-from-suspend support requires a patched Raspberry Pi kernel. For the
validated custom-kernel workflow, use
[docs/remote-wakeup-kernel.md](docs/remote-wakeup-kernel.md).

## Out of scope

Workstation-specific Pi connectivity recovery and host boot-policy tuning vary
too much by lab setup, network layout, and local policy to document as a
portable product workflow here.

## Configuration

The service reads structured runtime settings from:

```bash
/etc/default/bluetooth_2_usb
```

Default content:

```bash
B2U_AUTO_DISCOVER=true
B2U_DEVICE_IDS=
B2U_GRAB_DEVICES=true
B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12
B2U_LOG_TO_FILE=false
B2U_LOG_PATH=/var/log/bluetooth_2_usb/bluetooth_2_usb.log
B2U_DEBUG=false
B2U_UDC_PATH=
```

Meaning:

- `B2U_AUTO_DISCOVER=true` is the easiest default. It relays all suitable
  readable input devices except known excluded platform devices.
- `B2U_DEVICE_IDS` is the better fit when you want to pin the runtime to a
  specific set of devices instead of broad auto-discovery.
- `B2U_GRAB_DEVICES=true` grabs the selected input devices so the Pi stops
  consuming their local events. That is usually what you want for an
  appliance-like setup, but it also means the Pi will not keep using those
  inputs locally while they are grabbed.
- `B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12` defines a key chord that toggles
  relaying on and off.
- `B2U_LOG_TO_FILE=false` disables file logging by default.
- `B2U_LOG_PATH=...` controls the file path used when file logging is enabled.
- `B2U_DEBUG=false` keeps normal log verbosity.
- `B2U_UDC_PATH` is optional and only needed when you must pin UDC detection on
  a system with multiple gadget-capable controllers.

You can mix different kinds of device identifiers in one `B2U_DEVICE_IDS`
value, for example:

```bash
B2U_DEVICE_IDS=/dev/input/event4,A1:B2:C3:D4:E5:F6,MX Keys
```

That example pins the runtime to one explicit event path, one Bluetooth MAC,
and one case-insensitive device-name fragment.

After editing the runtime config:

```bash
sudo systemctl restart bluetooth_2_usb.service
```

## CLI reference

| Argument | Explanation |
| --- | --- |
| `--auto_discover, -a` | Relay all suitable readable input devices automatically. This is the best default when you want the Pi to behave like a simple appliance. |
| `--device_ids DEVICE_IDS, -i DEVICE_IDS` | Pin the runtime to a specific set of devices. The value is a comma-separated list of event paths, Bluetooth MACs, and case-insensitive name fragments, and you can mix those forms in one list. Example: `bluetooth_2_usb -i '/dev/input/event4,A1:B2:C3:D4:E5:F6,MX Keys'`. |
| `--grab_devices, -g` | Grab the selected input devices so the Pi no longer consumes their local events while they are being relayed. |
| `--interrupt_shortcut INTERRUPT_SHORTCUT, -s INTERRUPT_SHORTCUT` | Define a plus-separated key chord that toggles relaying at runtime. Example: `-s CTRL+SHIFT+F12`. |
| `--list_devices, -l` | List readable input devices and exit. Use this before setting `B2U_DEVICE_IDS` or `--device_ids` if you want to confirm the paths and names the runtime actually sees. |
| `--log_to_file, -f` | Add file logging in addition to stdout logging. |
| `--log_path LOG_PATH, -p LOG_PATH` | Override the path used with `--log_to_file`. |
| `--debug, -d` | Increase log verbosity for manual troubleshooting. |
| `--version, -v` | Print the installed version and exit. |
| `--validate-env` | Validate gadget runtime prerequisites and exit. On a normal non-gadget workstation this is expected to report missing prerequisites quickly. |
| `--output {text,json}` | Choose the output format for `--list_devices` and `--validate-env`. Use `json` for scripting or automation. |
| `--help, -h` | Show built-in CLI help and exit. |

## Script reference

Managed deployment scripts live in `/opt/bluetooth_2_usb/scripts/` after
installation.

### `install.sh`

Apply the current checkout in `/opt/bluetooth_2_usb` to the managed install.
Use this after cloning into the supported install path.

### `update.sh`

Fast-forward the managed checkout and call `install.sh` only when the checkout
actually changed. This is the normal update path for an installed system.

### `uninstall.sh`

Remove the managed system integration while leaving the checkout in place. Use
this when you want to remove the service and wrapper without deleting the clone.

### `smoke.sh`

Fast health check for the supported managed deployment. Use this first when you
want to confirm that the service, gadget path, and Bluetooth basics are healthy.

| Argument | Meaning |
| --- | --- |
| `--verbose` | Print fuller diagnostics, including the collected summary data. |

### `debug.sh`

Collect a redacted diagnostics report and optionally run a bounded live
foreground debug session. Use this when `smoke.sh` is not enough or when you
need a report to share.

| Argument | Meaning |
| --- | --- |
| `--duration DURATION_SEC` | Limit the live debug run. Omit it to keep the foreground session running until interrupted. |

### `inject.sh`

Create temporary virtual input devices on the Pi and inject a deterministic
test sequence into the running relay service. This is the Pi-side half of the
loopback harness.

### `capture.sh`

Capture host-side gadget HID reports and verify that the relay emitted the
expected sequence. This is the host-side half of the loopback harness.

### `capture.ps1`

Windows PowerShell wrapper for the same host-capture flow.

### `install-hid-udev-rule.sh`

Install the Linux host-side udev rule that grants `hidapi` access to the USB
gadget device nodes.

### `readonly-setup.sh`

Prepare writable ext4-backed storage for `/var/lib/bluetooth` before enabling
persistent read-only mode.

### `readonly-enable.sh`

Switch Raspberry Pi OS into the supported persistent read-only mode while
keeping Bluetooth state on separate writable storage.

### `readonly-disable.sh`

Return the system to normal writable mode while keeping the persistent
Bluetooth-state configuration available.

## Managed paths

| Path | Purpose |
| --- | --- |
| `/opt/bluetooth_2_usb` | Managed installation root |
| `/opt/bluetooth_2_usb/venv` | Managed virtual environment |
| `/etc/default/bluetooth_2_usb` | Structured runtime configuration |
| `/etc/default/bluetooth_2_usb_readonly` | Persistent read-only configuration |
| `/var/log/bluetooth_2_usb` | Script and report output |
| `/mnt/b2u-persist` | Default persistent mount target |
| `/mnt/b2u-persist/bluetooth` | Default persistent Bluetooth state directory |
| `/etc/systemd/system/bluetooth_2_usb.service` | Installed service unit |

## Development and release

- Contributor workflow: [CONTRIBUTING.md](CONTRIBUTING.md)
- Pi validation flow: [docs/cli-service-test.md](docs/cli-service-test.md)
- Loopback harness: [docs/host-relay-loopback.md](docs/host-relay-loopback.md)
- Persistent read-only workflow: [docs/persistent-readonly.md](docs/persistent-readonly.md)
- Doc consistency review: [docs/doc-consistency-review.md](docs/doc-consistency-review.md)
- Release tagging and versioning: [docs/release-versioning-policy.md](docs/release-versioning-policy.md)

## License

This project is licensed under the [MIT License](LICENSE).

The overview image is by Laura T. and is licensed under
[CC BY-NC 4.0](http://creativecommons.org/licenses/by-nc/4.0/).
