<!-- omit in toc -->
# Bluetooth-to-USB HID Bridge for Raspberry Pi

![Bluetooth-to-USB HID bridge overview for Raspberry Pi](https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/assets/overview.png)

Use Bluetooth keyboards and mice in BIOS and boot menus, KVM setups, retro systems, consoles, 
and other hosts where Bluetooth is unavailable or inconvenient.

Bluetooth-2-USB ("Bluetooth to USB") turns a Raspberry Pi into a USB HID
bridge for Bluetooth keyboards and mice. To the target host, the Pi appears as
a standard wired USB keyboard and mouse.

That keeps the host side simple: no Bluetooth support, pairing flow, or
special drivers are required on the target system.

## Quick start

This is the quickest supported path to a working setup.

### 1. Clone and install

```bash
sudo apt update && sudo apt install -y git
sudo git clone https://github.com/quaxalber/bluetooth_2_usb.git /opt/bluetooth_2_usb
cd /opt/bluetooth_2_usb && sudo env PYTHONPATH=src python3 -m bluetooth_2_usb install
```

### 2. Reboot

```bash
sudo reboot
```

### 3. Pair your Bluetooth device

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

### 4. Run the smoketest

```bash
sudo bluetooth_2_usb smoketest
```

### 5. Connect the Pi to the target host

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

Start with:

```bash
sudo bluetooth_2_usb smoketest
sudo bluetooth_2_usb debug --duration 10
```

Use `smoketest --verbose` for the full probe transcript. Use `debug` when you
need a redacted report with logs and live runtime output.

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
| `B2U_MOUSE_JIGGLER` | `false` |
| `B2U_JIGGLER_SHORTCUT` | `CTRL+SHIFT+F11` |
| `B2U_JIGGLER_LED` | `scroll_lock` |
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
| `--mouse-jiggler, -j` | `B2U_MOUSE_JIGGLER` | Enable mouse jiggler. Moves the cursor 2 pixels in a random direction every ~2 minutes when no input activity is detected, preventing the host screen from timing out. |
| `--jiggler-shortcut SHORTCUT` | `B2U_JIGGLER_SHORTCUT` | A plus-separated list of key names to press simultaneously in order to toggle the mouse jiggler on/off. Only effective when `--mouse-jiggler` is enabled. Example: `CTRL+SHIFT+F11`. Toggling it blinks a keyboard LED (see `--jiggler-led`) on the relayed keyboard(s) as visual confirmation: one long (~1.5 s) glow when enabling, three slow blinks when disabling. |
| `--jiggler-led LED` | `B2U_JIGGLER_LED` | Which keyboard LED to blink for jiggler toggle feedback. Only effective when `--jiggler-shortcut` is set. Choices: `caps_lock`, `num_lock`, `scroll_lock`. Default: `scroll_lock`. Pick one your keyboard actually has; not all keyboards implement all three. |
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

## Desktop status indicator

If the Pi also runs a desktop (Raspberry Pi OS with labwc and `wf-panel-pi`),
a tray icon can show the mouse jiggler state and where input currently goes.
It is display only.

The service publishes its state to `/run/bluetooth_2_usb/status.json`. The
indicator reads that file as the desktop user with the system Python. Set it
up once with:

```bash
sudo bluetooth_2_usb tray install
```

It starts with the next desktop login. To start it right away, run
`/usr/bin/python3 /opt/bluetooth_2_usb/desktop/bluetooth_2_usb_tray.py &` as
your desktop user.

The mouse is green while the jiggler is on and red with a slash while it is
off. The badge shows the relay: blue arrow for forwarding to the USB host,
orange pause for relay paused (input stays on the Pi), hollow grey for no
usable USB host. A dashed grey outline means the service is not running. The
menu spells out the same state in text.

The indicator installs its icons into `~/.local/share/icons/hicolor`, because
`wf-panel-pi` only resolves tray icons by theme name.

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

```bash
sudo bluetooth_2_usb COMMAND [ARGS...]
```

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

Run the managed deployment health check. Use `--verbose` for the full probe
transcript.

### `debug`

Write a redacted diagnostics report. See
[TROUBLESHOOTING.md](TROUBLESHOOTING.md) for what to collect and how to
interpret the report.

### `loopback inject|capture`

Create temporary virtual input devices on the Pi and inject a deterministic
test sequence, then capture host-side gadget HID reports and verify the
expected sequence. Use [docs/host-relay-loopback.md](docs/host-relay-loopback.md)
for scenarios, host prerequisites, and capture filters.

### `device capture`

Capture source-device metadata and live evidence for new device support. For
full guidance and sharing cautions, use
[docs/device-capture.md](docs/device-capture.md).

### `udev install`

Install the Linux host-side udev rule that grants `hidapi` access to the USB
gadget device nodes.

From a host checkout or development virtual environment, point the command at
the checkout that contains the rule source:

```bash
sudo ./venv/bin/bluetooth_2_usb udev install --repo-root "$PWD"
```

### `tray install|uninstall`

Install the desktop tray indicator's packages (`python3-gi`,
`gir1.2-ayatanaappindicator3-0.1`) and autostart it for desktop users on the
Pi, or remove that autostart entry. `install` and `update` keep an existing
entry in sync, and `uninstall` removes it. See
[Desktop status indicator](#desktop-status-indicator).

### `readonly setup|status|enable|disable|migrate`

Prepare persistent ext4-backed Bluetooth state, inspect read-only state, switch
read-only mode on or off, or migrate Bluetooth state back to rootfs. For setup,
enable/disable, migration, and validation details, use
[docs/persistent-readonly.md](docs/persistent-readonly.md).

## Managed paths

| Path | Purpose |
| --- | --- |
| `/opt/bluetooth_2_usb` | Managed installation root |
| `/opt/bluetooth_2_usb/venv` | Managed virtual environment |
| `/etc/default/bluetooth_2_usb` | Structured runtime settings |
| `/etc/default/bluetooth_2_usb_readonly` | Persistent Bluetooth state configuration |
| `/var/log/bluetooth_2_usb` | Operational command and runtime diagnostic output |
| `/mnt/b2u-persist` | Default persistent mount target |
| `/mnt/b2u-persist/bluetooth` | Default persistent Bluetooth state directory |
| `/etc/systemd/system/bluetooth_2_usb.service` | Installed service unit |
| `/run/bluetooth_2_usb/status.json` | Live relay and jiggler state for the desktop indicator |
| `/etc/xdg/autostart/bluetooth_2_usb-tray.desktop` | Desktop indicator autostart entry (after `tray install`) |

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
