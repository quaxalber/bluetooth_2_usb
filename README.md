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

For implementation details, see
[docs/runtime-architecture.md](docs/runtime-architecture.md).

## Runtime settings and CLI reference

Manual runs use CLI flags. The managed service reads runtime settings from:

```bash
/etc/default/bluetooth_2_usb
```

Default managed-service values:

| Environment setting | Default value |
| --- | --- |
| `B2U_AUTO` | `true` |
| `B2U_DEVICES` | empty |
| `B2U_GRAB` | `true` |
| `B2U_SHORTCUT` | `CTRL+SHIFT+F12` |
| `B2U_DEBUG` | `false` |

After editing the runtime settings:

```bash
sudo systemctl restart bluetooth_2_usb.service
```

Runtime CLI and environment reference:

| CLI argument | Environment setting | Explanation |
| --- | --- | --- |
| `--auto, -a` | `B2U_AUTO` | Enable auto relay. All readable input devices are relayed automatically except known excluded platform devices. |
| `--devices DEVICES` | `B2U_DEVICES` | Comma-separated list of devices to relay. Each value may match an input device path, `uniq`, `phys`, Bluetooth MAC address, or case-insensitive substring of the device name. Example: `--devices '/dev/input/event2,a1:b2:c3:d4:e5:f6,0A-1B-2C-3D-4E-5F,logi'`. |
| `--grab, -g` | `B2U_GRAB` | Grab the input devices, suppressing local events on the Pi while the devices are relayed. |
| `--shortcut SHORTCUT, -s SHORTCUT` | `B2U_SHORTCUT` | A plus-separated list of key names to press simultaneously in order to toggle relaying. |
| `--debug, -d` | `B2U_DEBUG` | Enable debug mode and increase log verbosity. |
| `--list, -l` | n/a | List all available input devices and exit. Use this before setting `B2U_DEVICES` or `--devices` if you want to confirm the paths and names the runtime actually sees. |
| `--validate-env` | n/a | Validate gadget runtime prerequisites and exit. On a normal non-gadget workstation this is expected to report missing prerequisites quickly. |
| `--output {text,json}` | n/a | Output format for `--list` and `--validate-env`. Use `json` for scripting or automation. |
| `--version, -v` | n/a | Display the version number of this software and exit. |
| `--help, -h` | n/a | Show built-in CLI help and exit. |

> [!NOTE]
> Despite the project name, broad auto relay can also relay other suitable
> Linux input devices that are visible on the Pi. The intended primary use case
> remains Bluetooth keyboard and mouse bridging.

## Read-only operation

For the supported appliance-style read-only workflow, use
[docs/persistent-readonly.md](docs/persistent-readonly.md).

## Host wake from suspend

The stock install path focuses on reliable HID relay while the target host is
awake. For wake-from-suspend support, use the validated custom-kernel workflow
in [docs/remote-wakeup-kernel.md](docs/remote-wakeup-kernel.md).

> [!NOTE]
> Wake-from-suspend support requires a patched Raspberry Pi kernel and is not
> part of the stock install path.

## Operational command reference

Managed deployment commands use the same `bluetooth_2_usb` CLI as the runtime.
During the initial source-tree install, run the module with `PYTHONPATH`
pointed at the checkout. After installation, use the managed `bluetooth_2_usb`
console command. Use built-in `--help` for the complete command-specific
interface.

### `install`

Apply the current checkout in `/opt/bluetooth_2_usb` to the managed install.
Use this after cloning into the supported install path. The managed virtual
environment is reused when it is valid; pass `--recreate-venv` to delete and
recreate it before installing.

```bash
sudo bluetooth_2_usb install
```

### `update`

Fast-forward the managed checkout and reapply `install`. This is the normal
update path for an installed system. The managed virtual environment is reused
when it is valid; pass `--recreate-venv` after dependency removals, suspected
venv corruption, or clean-install release validation.

```bash
sudo bluetooth_2_usb update
```

### `uninstall`

Remove the managed system integration while leaving the checkout in place. Use
this when you want to remove the service and CLI links without deleting the
clone.

```bash
sudo bluetooth_2_usb uninstall
```

### `smoketest`

Fast health check for the supported managed deployment. Use this first when you
want to confirm that the service, gadget path, and Bluetooth basics are
healthy.

```bash
sudo bluetooth_2_usb smoketest --verbose
```

### `debug`

Collect a redacted diagnostics report and optionally run a bounded live
foreground debug session. Use this when the `smoketest` is not enough or when
you need a report to share.

```bash
sudo bluetooth_2_usb debug --duration DURATION_SEC
```

### `loopback inject`

Create temporary virtual input devices on the Pi and inject a deterministic
test sequence into the running relay service. This is the Pi-side half of the
loopback inject/capture validation. For scenario and option details, use
[docs/host-relay-loopback.md](docs/host-relay-loopback.md).

```bash
bluetooth_2_usb loopback inject --scenario SCENARIO
```

### `loopback capture`

Capture host-side gadget HID reports and verify that the relay emitted the
expected sequence. This is the host-side half of the loopback inject/capture
validation. Pass `--devices` with a gadget path, `uniq`, `phys`, Bluetooth
MAC-shaped `uniq`, or product-name fragment. On Windows, use the same Python
CLI from an environment that can import `hid`; strict Windows event capture
uses the Python Raw Input backend.

```bash
bluetooth_2_usb loopback capture --scenario SCENARIO --devices DEVICE_FILTER
```

### `device capture`

Capture source-device metadata and live evidence for adding support for a new
keyboard, mouse, gamepad, touchpad, remote, or other Linux input/HID-like
device. For full guidance and sharing cautions, use
[docs/device-capture.md](docs/device-capture.md).

```bash
sudo bluetooth_2_usb device capture --devices DEVICE_FILTER --duration DURATION_SEC --grab
```

### `udev install`

Install the Linux host-side udev rule that grants `hidapi` access to the USB
gadget device nodes.

```bash
sudo bluetooth_2_usb udev install
```

From a host checkout or development virtual environment, point the command at
the checkout that contains the rule source:

```bash
sudo ./venv/bin/bluetooth_2_usb udev install --repo-root "$PWD"
```

### `readonly setup`

Prepare persistent ext4-backed storage for `/var/lib/bluetooth` before enabling
read-only mode. For setup, enable/disable, and validation details, use
[docs/persistent-readonly.md](docs/persistent-readonly.md).

```bash
sudo bluetooth_2_usb readonly setup --device DEVICE
```

### `readonly status`

Show the configured and live read-only state, including OverlayFS, root
filesystem, and persistent Bluetooth-state mount status.

```bash
bluetooth_2_usb readonly status
```

### `readonly enable`

Switch Raspberry Pi OS into the supported read-only mode while keeping
Bluetooth state on separate persistent storage.

```bash
sudo bluetooth_2_usb readonly enable
```

### `readonly disable`

Return the system to normal writable mode while keeping the persistent
Bluetooth-state storage configuration available.

```bash
sudo bluetooth_2_usb readonly disable
```

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
