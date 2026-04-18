<!-- omit in toc -->
# Bluetooth-2-USB

![Bluetooth-2-USB Overview](https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/assets/overview.png)

Use your Bluetooth keyboard and mouse where Bluetooth usually stops being
helpful.

Bluetooth-2-USB turns a Raspberry Pi into a USB HID bridge for Bluetooth
keyboards and mice. To the target host, the Pi appears as a standard wired USB
keyboard and mouse.

## Quick start

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
sudo /opt/bluetooth_2_usb/scripts/diagnostics/smoke_test.sh
```

### 6. Connect the Pi to the target host

- Pi 4B / 5: use the USB-C power port
- Pi Zero W / Zero 2 W: use the USB data port

## Requirements

- Raspberry Pi Zero W, Zero 2 W, 4B, or 5
- Raspberry Pi OS Bookworm or newer
- Internet access during installation
- Bluetooth keyboard, mouse, or both
- USB cable that supports data

Notes:
- Pi 3 models include Bluetooth but do not expose a suitable device-mode port.
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

Start with:

```bash
sudo /opt/bluetooth_2_usb/scripts/diagnostics/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/diagnostics/debug.sh --duration 10
```

For troubleshooting flows beyond those two commands, use
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Persistent read-only operation

For the supported persistent read-only workflow, use
[docs/pi/persistent-readonly.md](docs/pi/persistent-readonly.md).

## Host wake from suspend

Wake-from-suspend support requires a patched Raspberry Pi kernel. Use
[docs/pi/remote-wakeup-kernel.md](docs/pi/remote-wakeup-kernel.md).

## Out of scope

Site-specific workstation-to-Pi connectivity recovery and host boot-policy
optimization are intentionally not part of the product docs. Those topics depend
too heavily on local lab policy, network layout, and host assumptions.

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

- `B2U_AUTO_DISCOVER=true` relays all suitable readable input devices except
  known excluded platform devices.
- `B2U_DEVICE_IDS` pins the runtime to specific event paths, Bluetooth MACs, or
  case-insensitive device-name fragments.
- `B2U_GRAB_DEVICES=true` grabs the selected input devices so the Pi stops
  consuming their local events.
- `B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12` defines a key chord that toggles
  relaying on and off.
- `B2U_LOG_TO_FILE=false` disables file logging by default.
- `B2U_LOG_PATH=...` controls the file path used when file logging is enabled.
- `B2U_DEBUG=false` keeps normal log verbosity.
- `B2U_UDC_PATH` is optional and only needed when you must pin UDC detection on
  a system with multiple gadget-capable controllers.

After editing that file:

```bash
sudo systemctl restart bluetooth_2_usb.service
```

## CLI reference

| Argument | Meaning |
| --- | --- |
| `--auto_discover, -a` | Relay all suitable readable input devices automatically. |
| `--device_ids DEVICE_IDS, -i DEVICE_IDS` | Comma-separated event paths, Bluetooth MACs, or case-insensitive name fragments. |
| `--grab_devices, -g` | Grab the selected input devices so the Pi no longer consumes their local events. |
| `--interrupt_shortcut INTERRUPT_SHORTCUT, -s INTERRUPT_SHORTCUT` | Plus-separated key chord that toggles relaying at runtime. |
| `--list_devices, -l` | List readable input devices and exit. |
| `--log_to_file, -f` | Add file logging in addition to stdout logging. |
| `--log_path LOG_PATH, -p LOG_PATH` | Override the path used with `--log_to_file`. |
| `--debug, -d` | Increase log verbosity. |
| `--version, -v` | Print the installed version and exit. |
| `--validate-env` | Validate gadget runtime prerequisites and exit. |
| `--output {text,json}` | Output format for `--list_devices` and `--validate-env`. |
| `--help, -h` | Show built-in CLI help and exit. |

## Script reference

Managed deployment scripts live in `/opt/bluetooth_2_usb/scripts/` after
installation.

### `install.sh`

Apply the current checkout in `/opt/bluetooth_2_usb` to the managed install.

### `update.sh`

Fast-forward the managed checkout and call `install.sh` only when the checkout
changed.

### `uninstall.sh`

Remove the managed system integration while leaving the checkout in place.

### `diagnostics/smoke_test.sh`

Fast health check for the supported managed deployment.

| Argument | Meaning |
| --- | --- |
| `--verbose` | Print the fuller health-check output. |

### `diagnostics/debug.sh`

Collect a redacted diagnostics report and optionally run a bounded live
foreground debug session.

| Argument | Meaning |
| --- | --- |
| `--duration DURATION_SEC` | Limit the live debug run. |

### `testing/pi_relay_test_inject.sh`

Create temporary virtual input devices on the Pi and inject a deterministic
test sequence into the running relay service.

### `host/host_relay_test_capture.sh`

Capture host-side gadget HID reports and verify that the relay emitted the
expected sequence.

### `host/host_relay_test_capture.ps1`

Windows PowerShell wrapper for the same host-capture flow.

### `host/install_host_hidapi_udev_rule.sh`

Install the Linux host-side udev rule that grants `hidapi` access to the USB
gadget device nodes.

### `readonly/setup_persistent_bluetooth_state.sh`

Prepare writable ext4-backed storage for `/var/lib/bluetooth`.

### `readonly/enable_readonly_overlayfs.sh`

Switch Raspberry Pi OS into persistent read-only operation.

### `readonly/disable_readonly_overlayfs.sh`

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
- Pi validation flow: [docs/pi/cli-service-test.md](docs/pi/cli-service-test.md)
- Loopback harness: [docs/pi/host-relay-loopback.md](docs/pi/host-relay-loopback.md)
- Persistent read-only workflow: [docs/pi/persistent-readonly.md](docs/pi/persistent-readonly.md)
- Doc consistency review: [docs/process/doc-consistency-review.md](docs/process/doc-consistency-review.md)
- Release tagging and versioning: [docs/process/release-versioning-policy.md](docs/process/release-versioning-policy.md)

## License

This project is licensed under the [MIT License](LICENSE).

The overview image is by Laura T. and is licensed under
[CC BY-NC 4.0](http://creativecommons.org/licenses/by-nc/4.0/).
