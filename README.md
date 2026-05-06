<!-- omit in toc -->
# Bluetooth-to-USB HID Bridge for Raspberry Pi

![Bluetooth-to-USB HID bridge overview for Raspberry Pi](https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/assets/overview.png)

Use Bluetooth keyboards and mice in BIOS and boot menus, installers, kiosks,
tablets, KVM setups, retro systems, consoles, and other hosts where Bluetooth
is unavailable or inconvenient.

Bluetooth-2-USB (meaning Bluetooth to USB) turns a Raspberry Pi into a USB HID
bridge for Bluetooth keyboards and mice. To the target host, the Pi appears as
a standard wired USB keyboard and mouse.

That keeps the host side simple: no Bluetooth support, pairing flow, or
special drivers are required on the target system.

## Quick start

This is the quickest supported path to a working setup.

### 1. Clone the project to the managed install path

```bash
sudo apt update && sudo apt install -y git
sudo git clone https://github.com/quaxalber/bluetooth_2_usb.git /opt/bluetooth_2_usb
```

### 2. Install

```bash
cd /opt/bluetooth_2_usb && sudo env PYTHONPATH=src python3 -m bluetooth_2_usb install
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

> [!NOTE]
> Replace `A1:B2:C3:D4:E5:F6` with your device's real Bluetooth MAC address.
> Some devices trigger an interactive `bluetoothctl` authorization prompt
> during pairing. Answer it immediately or BlueZ may cancel the request.

### 5. Run the smoketest

```bash
sudo bluetooth_2_usb smoketest
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

> [!NOTE]
> Pi 3 models include Bluetooth, but they do not expose a suitable
> device-mode port for this project.
> On Pi 4B and Pi 5, the OTG-capable port is the USB-C power port.
> On Pi Zero boards, the OTG-capable port is the USB data port, not the
> power-only port.

## Updating

```bash
sudo bluetooth_2_usb update
```

## Uninstalling

```bash
sudo bluetooth_2_usb uninstall
```

## Diagnostics

For most issues, start with the two built-in diagnostics:

```bash
sudo bluetooth_2_usb smoketest --verbose
sudo bluetooth_2_usb debug --duration 10
```

The `smoketest` is the quick health gate. `debug` collects a fuller
redacted snapshot and can run a short bounded foreground debug session. Debug
reports are written under `/var/log/bluetooth_2_usb/` and are made copyable by
the invoking sudo user when possible. If you need the next steps after those
checks, use
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Runtime behavior

The service runs one asyncio runtime that turns UDC cable state, input hotplug,
and shutdown signals into typed runtime events. A relay supervisor consumes
those events and owns all per-device relay tasks.

Relaying starts only when the USB device controller reports `configured`.
Relaying pauses, and all HID gadget state is released, when the controller
leaves `configured`. That keeps host-visible keys and buttons from sticking
across cable disconnects, suspend transitions, and USB resets.

For implementation details, see
[docs/runtime-architecture.md](docs/runtime-architecture.md).

## Read-only operation

For the supported appliance-style read-only workflow, use
[docs/persistent-readonly.md](docs/persistent-readonly.md).

## Host wake from suspend

The normal install path focuses on reliable HID relay while the target host is
awake. Waking a suspended target host requires USB remote wake behavior from
the Pi gadget side, and that currently depends on kernel support outside the
stock Raspberry Pi OS path.

For the validated custom-kernel workflow, use
[docs/remote-wakeup-kernel.md](docs/remote-wakeup-kernel.md).

> [!WARNING]
> Wake-from-suspend support requires a patched Raspberry Pi kernel. This is not
> part of the stock install path.

## Runtime settings and CLI reference

Runtime behavior can be configured temporarily with CLI arguments when
launching manually, or persistently through `/etc/default/bluetooth_2_usb` for
the managed service. After editing the environment file, restart the service:

```bash
sudo systemctl restart bluetooth_2_usb.service
```

| CLI argument | Environment setting | Explanation |
| --- | --- | --- |
| `--auto_discover, -a` | `B2U_AUTO_DISCOVER` | Relay all suitable readable input devices automatically. This is the best default when you want the Pi to behave like a simple appliance. |
| `--device_ids DEVICE_IDS, -i DEVICE_IDS` | `B2U_DEVICE_IDS` | Pin the runtime to a specific comma-separated list of event paths, Bluetooth MACs, and case-insensitive name fragments. |
| `--grab_devices, -g` | `B2U_GRAB_DEVICES` | Grab the selected input devices so the Pi no longer consumes their local events while they are being relayed. |
| `--interrupt_shortcut INTERRUPT_SHORTCUT, -s INTERRUPT_SHORTCUT` | `B2U_INTERRUPT_SHORTCUT` | Define a plus-separated key chord that toggles relaying at runtime. Example: `-s CTRL+SHIFT+F12`. |
| `--log_to_file, -f` | `B2U_LOG_TO_FILE` | Add file logging in addition to stdout logging. |
| `--log_path LOG_PATH, -p LOG_PATH` | `B2U_LOG_PATH` | Override the path used with `--log_to_file`. |
| `--debug, -d` | `B2U_DEBUG` | Increase log verbosity for manual troubleshooting. |
| n/a | `B2U_UDC_PATH` | Optional advanced override for systems with multiple gadget-capable controllers. |
| `--list_devices, -l` | n/a | List readable input devices and exit. Use this before setting `B2U_DEVICE_IDS` or `--device_ids` if you want to confirm the paths and names the runtime actually sees. |
| `--validate-env` | n/a | Validate gadget runtime prerequisites and exit. On a normal non-gadget workstation this is expected to report missing prerequisites quickly. |
| `--output {text,json}` | n/a | Choose the output format for `--list_devices` and `--validate-env`. Use `json` for scripting or automation. |
| `--version, -v` | n/a | Print the installed version and exit. |
| `--help, -h` | n/a | Show built-in CLI help and exit. |

> [!NOTE]
> Despite the project name, broad auto-discovery can also relay other suitable
> Linux input devices that are visible on the Pi. The intended primary use case
> remains Bluetooth keyboard and mouse bridging.

## Operational command reference

Managed deployment commands use the same `bluetooth_2_usb` CLI as the runtime.
During the initial source-tree install, run the module with `PYTHONPATH`
pointed at the checkout. After installation, use the managed `bluetooth_2_usb`
console command.

### `install`

Apply the current checkout in `/opt/bluetooth_2_usb` to the managed install.
Use this after cloning into the supported install path. The managed virtual
environment is reused when it is valid; pass `--recreate-venv` to delete and
recreate it before installing.

### `update`

Fast-forward the managed checkout and reapply `install`. This is the normal
update path for an installed system. The managed virtual environment is reused
when it is valid; pass `--recreate-venv` after dependency removals, suspected
venv corruption, or clean-install release validation.

### `uninstall`

Remove the managed system integration while leaving the checkout in place. Use
this when you want to remove the service and CLI links without deleting the
clone.

### `smoketest`

Fast health check for the supported managed deployment. Use this first when you
want to confirm that the service, gadget path, and Bluetooth basics are
healthy.

| Argument | Meaning |
| --- | --- |
| `--verbose` | Print fuller diagnostics, including the collected summary data. |
| `--output {text,json}` | Choose the output format. JSON output is written to stdout for automation; probe text is redirected to stderr. |

### `debug`

Collect a redacted diagnostics report and optionally run a bounded live
foreground debug session. Use this when the `smoketest` is not enough or when
you need a report to share.

| Argument | Meaning |
| --- | --- |
| `--duration DURATION_SEC` | Limit the live debug run. Omit it to keep the foreground session running until interrupted. |

### `loopback inject`

Create temporary virtual input devices on the Pi and inject a deterministic
test sequence into the running relay service. This is the Pi-side half of the
loopback inject/capture validation.

### `loopback capture`

Capture host-side gadget HID reports and verify that the relay emitted the
expected sequence. This is the host-side half of the loopback inject/capture
validation. On Windows, use the same Python CLI from an environment that can
import `hid`; strict Windows event capture uses the Python Raw Input backend.

### `device capture`

Capture source-device metadata and live evidence for adding support for a new
keyboard, mouse, gamepad, touchpad, remote, or other Linux input/HID-like
device. For full guidance, use
[docs/device-capture.md](docs/device-capture.md).

```bash
sudo bluetooth_2_usb device capture --device /dev/input/event4 --duration 30 --grab
```

### `udev install`

Install the Linux host-side udev rule that grants `hidapi` access to the USB
gadget device nodes.

### `readonly setup`

Prepare persistent ext4-backed storage for `/var/lib/bluetooth` before enabling
read-only mode.

### `readonly status`

Show the configured and live read-only state, including OverlayFS, root
filesystem, and persistent Bluetooth-state mount status.

### `readonly enable`

Switch Raspberry Pi OS into the supported read-only mode while keeping
Bluetooth state on separate persistent storage.

### `readonly disable`

Return the system to normal writable mode while keeping the persistent
Bluetooth-state storage configuration available.

## Managed paths

| Path | Purpose |
| --- | --- |
| `/opt/bluetooth_2_usb` | Managed installation root |
| `/opt/bluetooth_2_usb/venv` | Managed virtual environment |
| `/etc/default/bluetooth_2_usb` | Structured runtime settings |
| `/etc/default/bluetooth_2_usb_readonly` | Read-only configuration |
| `/var/log/bluetooth_2_usb` | Operational command and runtime diagnostic output |
| `/mnt/b2u-persist` | Default persistent mount target |
| `/mnt/b2u-persist/bluetooth` | Default persistent Bluetooth state directory |
| `/etc/systemd/system/bluetooth_2_usb.service` | Installed service unit |

## Development and release

- Contributor workflow: [CONTRIBUTING.md](CONTRIBUTING.md)
- Pi validation flow: [docs/cli-service-test.md](docs/cli-service-test.md)
- Loopback inject/capture validation: [docs/host-relay-loopback.md](docs/host-relay-loopback.md)
- Read-only workflow: [docs/persistent-readonly.md](docs/persistent-readonly.md)
- Doc consistency review: [docs/doc-consistency-review.md](docs/doc-consistency-review.md)
- Release tagging and versioning: [docs/release-versioning-policy.md](docs/release-versioning-policy.md)

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

Written by Eyes<br>
Assisted by Technology and AI<br>
Powered by Coffee<br>
Developed with Love

</div>
