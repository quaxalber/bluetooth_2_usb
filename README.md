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

Use your Bluetooth keyboard and mouse where Bluetooth usually stops being helpful.

Bluetooth-2-USB turns a Raspberry Pi into a USB HID bridge for Bluetooth keyboards and mice. To the target host, the Pi appears as a standard wired USB keyboard and mouse.

That makes it useful in places where Bluetooth is unavailable, unsupported, or unreliable — including BIOS and boot menus, installers, KVM switches, kiosks, tablets, retro systems, consoles, and other constrained environments.

## Quick start

This is the shortest supported path to a working setup.

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

### 4. Pair your Bluetooth devices

Use the desktop UI or `bluetoothctl`.

```bash
bluetoothctl
power on
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
> Some devices trigger an interactive `bluetoothctl` authorization prompt during pairing. Answer that prompt immediately or BlueZ may cancel the request.

### 5. Verify the installation

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh
```

### 6. Connect the Pi to the target host

#### Raspberry Pi 4B / 5

Connect the Pi's USB-C power port to the target host. That is the OTG-capable port required for USB gadget mode.

#### Raspberry Pi Zero W / Zero 2 W

Connect the Pi's USB data port to the target host.

If possible, power the Pi from a separate stable power supply using the power-only port. That usually improves stability.

## Table of Contents

- [Highlights](#highlights)
- [Requirements](#requirements)
- [Day-to-day usage](#day-to-day-usage)
- [Updating](#updating)
- [Uninstalling](#uninstalling)
- [Diagnostics](#diagnostics)
- [Persistent read-only operation](#persistent-read-only-operation)
- [Host wake from suspend](#host-wake-from-suspend)
- [Boot optimization](#boot-optimization)
- [Troubleshooting](#troubleshooting)
- [Configuration](#configuration)
- [CLI reference](#cli-reference)
- [Script reference](#script-reference)
- [Managed paths](#managed-paths)
- [Development and release](#development-and-release)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Highlights

- Bluetooth keyboard and mouse input relayed as standard USB HID
- Auto-discovery and auto-reconnect for supported input devices
- Optional input grabbing so the Pi does not also consume local keyboard and mouse events
- Broad support for everyday multimedia and consumer-control keys such as
  volume, mute, play/pause, track controls, and many common shortcut keys
- A conservative USB HID gadget setup aimed at broad host compatibility
- A well-supported diagnostics surface built around `--validate-env`, `smoke_test.sh`, and `debug.sh`
- Optional persistent read-only operation with writable Bluetooth state on a separate ext4 filesystem
- A single supported managed-install workflow in `/opt/bluetooth_2_usb`

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
> - Raspberry Pi 3 models include Bluetooth, but they do not expose a suitable USB device-mode port for this project.
> - On Pi 4B and Pi 5, the OTG-capable port is the USB-C power port.
> - On Pi Zero boards, the OTG-capable port is the USB data port, not the power-only port.

## Day-to-day usage

List available devices:

```bash
bluetooth_2_usb -l
```

Example text output:

```text
          ╷                 ╷                   ╷                   ╷
 Status   │ Device          │ Identity          │ Path              │ Exclusion Reason
 ═════════╪═════════════════╪═══════════════════╪═══════════════════╪══════════════════════
 relay    │ Kappa Keyboard  │ a1:b2:c3:d4:e5:f6 │ /dev/input/event4 │
 skip     │ vc4-hdmi-0      │ vc4-hdmi-0/input0 │ /dev/input/event0 │ name prefix vc4-hdmi
          ╵                 ╵                   ╵                   ╵
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

Restart the service after changing runtime config:

```bash
sudo systemctl restart bluetooth_2_usb.service
```

## Updating

Update the managed checkout:

```bash
sudo /opt/bluetooth_2_usb/scripts/update.sh
```

## Uninstalling

Remove the managed system integration:

```bash
sudo /opt/bluetooth_2_usb/scripts/uninstall.sh
```

## Diagnostics

Start with the quick health check:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

If that is not enough, collect the fuller debug report:

```bash
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
```

For most problems, these are the first two commands to run.

## Persistent read-only operation

For the persistent read-only workflow, writable Bluetooth-state setup, and
rollback path, use
[docs/pi/persistent-readonly.md](docs/pi/persistent-readonly.md).

## Host wake from suspend

Bluetooth-2-USB can wake a sleeping or suspended host when you use the
custom-kernel workflow in
[docs/pi/remote-wakeup-kernel.md](docs/pi/remote-wakeup-kernel.md).

## Boot optimization

For the boot-optimization workflow, validation, rollback, and the tested
`NetworkManager`/netplan migration path, use
[docs/pi/boot-optimization.md](docs/pi/boot-optimization.md).

## Troubleshooting

For troubleshooting flows and follow-up checks, use
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

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

- `B2U_AUTO_DISCOVER=true` relays all suitable readable input devices except known excluded platform devices.
- `B2U_DEVICE_IDS` is the precise alternative when you want to pin the runtime to specific event paths, Bluetooth MACs, or case-insensitive device-name fragments.
- `B2U_GRAB_DEVICES=true` grabs the selected input devices so the Pi stops consuming their local events.
- `B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12` defines a plus-separated key chord that toggles relaying on and off at runtime.
- `B2U_LOG_TO_FILE=false` disables file logging by default.
- `B2U_LOG_PATH=...` controls the file path used when file logging is enabled.
- `B2U_DEBUG=false` keeps normal log verbosity.
- `B2U_UDC_PATH` is optional and only needed if you must pin UDC detection on a system with multiple gadget-capable controllers.

After editing that file, restart the service:

```bash
sudo systemctl restart bluetooth_2_usb.service
```

> [!NOTE]
> Despite the project name, broad auto-discovery can also relay other suitable Linux input devices that are visible on the Pi; the intended primary use case remains Bluetooth keyboard and mouse bridging.

## CLI reference

Use these runtime flags when running the CLI manually.

| Argument | Explanation / Example |
| --- | --- |
| `--auto_discover, -a` | Relay all readable suitable input devices automatically, except known excluded platform devices. Good default for appliance-style setups where you do not want to curate a static device list. |
| `--device_ids DEVICE_IDS, -i DEVICE_IDS` | Comma-separated identifiers for the devices to relay. Each identifier may be an event path, a Bluetooth MAC address, or a case-insensitive name fragment. The matcher accepts all three kinds in the same comma-separated list. Default: none. Examples: `-i /dev/input/event4`, `-i A1:B2:C3:D4:E5:F6`, `-i logi`, `-i '/dev/input/event4,A1:B2:C3:D4:E5:F6,MX Keys'`. |
| `--grab_devices, -g` | Grab the selected input devices so the Pi no longer consumes their local events. |
| `--interrupt_shortcut INTERRUPT_SHORTCUT, -s INTERRUPT_SHORTCUT` | Plus-separated key chord that toggles relaying on and off at runtime. Default: none when unset at the CLI. Example: `-s CTRL+SHIFT+F12`. |
| `--list_devices, -l` | List readable input devices and exit without starting the relay. Text output is shown as a formatted table with headers; `--output json` keeps the machine-readable form. Useful before setting `DEVICE_IDS`. |
| `--log_to_file, -f` | Add file logging in addition to stdout logging. |
| `--log_path LOG_PATH, -p LOG_PATH` | Override the path used with `--log_to_file`. Default: `/var/log/bluetooth_2_usb/bluetooth_2_usb.log`. Example: `-p /tmp/bluetooth_2_usb.log`. |
| `--debug, -d` | Increase log verbosity for manual troubleshooting. |
| `--version, -v` | Print the installed Bluetooth-2-USB version and exit. |
| `--validate-env` | Validate gadget runtime prerequisites and exit. On non-gadget systems this is expected to fail fast and report the missing prerequisites. |
| `--output {text,json}` | Output format for `--list_devices` and `--validate-env`. Default: `text`. |
| `--help, -h` | Show the built-in CLI help and exit. |

## Script reference

Managed deployment scripts live in `/opt/bluetooth_2_usb/scripts/` after
installation. The host-side helper `scripts/check_pi_connectivity.sh` is meant
to be run from a workstation checkout instead.

### `install.sh`

Apply the current checkout in `/opt/bluetooth_2_usb` to the managed install. This is the main deployment entrypoint for first install and for explicit re-application of the current checkout. On current Raspberry Pi OS Lite images, the install flow also clears common Bluetooth soft-blocked `rfkill` defaults so pairing can start from a known-good controller state.

### `update.sh`

Fast-forward the managed checkout and call `install.sh` only when the checkout
changed. If the current branch is already up to date, the script exits
successfully without reinstalling anything. The script refuses to update a
dirty managed checkout. This is the supported update path for an existing
managed deployment.

### `uninstall.sh`

Remove the managed system integration while deliberately leaving the checkout in place for inspection or later reuse.

### `smoke_test.sh`

Run the fast health check for the supported managed deployment. This is the first script to use after install, reboot, update, or read-only changes. It fails on broken platform, runtime, or Bluetooth-controller prerequisites, and warns when no paired or relayable devices are currently visible. In that case the final line stays successful but is rendered as `PASSED (with warnings)`. It also checks the detected UDC state and warns when the gadget controller is present but not currently `configured`.

| Argument | Explanation / Example |
| --- | --- |
| `--verbose` | Print the fuller health-check output instead of the compact pass/fail view. Default: disabled. Example: `sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose`. |

### `debug.sh`

Collect a deeper redacted diagnostics bundle when `smoke_test.sh` is not enough. It records service, boot, Bluetooth, mount, and runtime state, then runs a bounded live foreground debug session. The report includes the detected UDC state and shows whether it is currently `configured`.

| Argument | Explanation / Example |
| --- | --- |
| `--duration DURATION_SEC` | Limit the live foreground debug run. Default: unbounded until interrupted. Example: `sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10`. |

### `optimize_pi_boot.sh`

Reduce Pi boot delays that are not required for `bluetooth_2_usb`. The script
can disable `cloud-init` on already provisioned hosts, disable
`NetworkManager-wait-online.service`, remove `ds=nocloud...` from
`cmdline.txt`, persist transient netplan-generated `NetworkManager` profiles as
native keyfiles while disabling the generated `/etc/netplan/90-NM-*.yaml`
overrides, and optionally freeze the current DHCP IPv4 settings as a static
NetworkManager profile. It writes rollback state to
`/var/lib/bluetooth_2_usb/optimize_pi_boot_state.env` so the managed host can
be restored later.

| Argument | Explanation / Example |
| --- | --- |
| `--dry-run` | Show the planned host changes without mutating the system. Example: `sudo /opt/bluetooth_2_usb/scripts/optimize_pi_boot.sh --dry-run --static-ip auto`. |
| `--rollback` | Restore the previously captured host state and, unless `--no-reboot` is also set, reboot immediately afterwards. |
| `--no-reboot` | Do not reboot automatically after apply or explicit rollback. |
| `--static-ip auto` | Freeze the currently active DHCP IPv4 address, gateway, and DNS values for `wlan0` as a static profile. |
| `--static-ip CIDR --gateway IPV4 --dns CSV` | Apply explicit static IPv4 settings instead of auto-detecting them. Example: `sudo /opt/bluetooth_2_usb/scripts/optimize_pi_boot.sh --static-ip 192.168.2.215/24 --gateway 192.168.2.1 --dns 1.1.1.1,9.9.9.9,192.168.2.1`. |

### `pi_relay_test_inject.sh`

Create temporary virtual keyboard and mouse devices on the Pi and inject a deterministic test sequence into the running relay service.

| Argument | Explanation / Example |
| --- | --- |
| `--scenario {keyboard,mouse,combo,consumer,text_burst}` | Select which deterministic test sequence to inject. Default: `combo`. Example: `sudo /opt/bluetooth_2_usb/scripts/pi_relay_test_inject.sh --scenario combo`. |
| `--pre-delay-ms PRE_DELAY_MS` | Wait after creating the virtual devices before sending events. Default: `1000`. |
| `--event-gap-ms EVENT_GAP_MS` | Delay between injected events. Default: `40`. |

### `host_relay_test_capture.sh`

Capture host-side gadget HID reports and verify that the relay emitted the expected sequence. Use this wrapper on Linux and macOS. The host Python environment must have `hidapi` installed, for example via `python3 -m pip install -r requirements-host-capture.txt`. On Linux, unprivileged access also needs the host-side USB udev rule. Depending on the host HID stack, opening the gadget interfaces for capture can temporarily claim them while the test is running, so do not assume the local desktop will continue to process the same keyboard, mouse, or consumer inputs during the capture window. The default test sequence therefore uses non-text keyboard keys and tiny mouse-relative movements. On Windows, use the PowerShell wrapper below; it uses `hidapi` for gadget discovery and Raw Input for strict event capture.

> [!NOTE]
> The Linux host flow is actively exercised. The macOS wrapper path is
> documented for parity, but it has not yet been validated on a real macOS host.

The harness is single-run only and uses a lock file. If a previous run was interrupted, clear stale lock files before retrying:

- host: `%TEMP%\\bluetooth_2_usb_test_harness.lock` on Windows
- host: `/tmp/bluetooth_2_usb_test_harness.lock` on Linux and macOS
- Pi: `/tmp/bluetooth_2_usb_test_harness.lock`

Before each fresh Windows validation run after changing the gadget descriptor layout or USB identity:

1. set the target Pi to the intended software revision
2. reboot the Pi
3. perform a Windows PnP admin reset
4. only then start the host capture

| Argument | Explanation / Example |
| --- | --- |
| `--scenario {keyboard,mouse,combo,consumer,text_burst}` | Expected test sequence. Default: `combo`. Example: `./scripts/host_relay_test_capture.sh --scenario combo`. |
| `--timeout-sec TIMEOUT_SEC` | Time to wait for the full sequence. Default: `5`. |
| `--keyboard-node PATH` | Override the detected host keyboard HID device path. |
| `--mouse-node PATH` | Override the detected host mouse HID device path. |
| `--consumer-node PATH` | Override the detected host consumer-control HID device path. |

### `host_relay_test_capture.ps1`

Windows PowerShell wrapper for the same host-capture flow.

| Argument | Explanation / Example |
| --- | --- |
| same as `host_relay_test_capture.sh` | Example: `powershell -ExecutionPolicy Bypass -File .\\scripts\\host_relay_test_capture.ps1 --scenario combo`. |

### `install_host_hidapi_udev_rule.sh`

Install the Linux host-side udev rule that grants `hidapi` write access to the USB gadget device nodes.

| Argument | Explanation / Example |
| --- | --- |
| none | Linux only. Run once on the receiving host. Example: `sudo ./scripts/install_host_hidapi_udev_rule.sh`. |

### `check_pi_connectivity.sh`

Workstation-side probe for Raspberry Pi SSH, mDNS, and IPv6 link-local
reachability. It is intended for recurring cases where the Pi is reachable but
plain hostname SSH or IPv4 behaves inconsistently. The script does not mutate
SSH configuration; it prints a recommended `~/.ssh/config` block when a scoped
link-local probe succeeds.

| Argument | Explanation / Example |
| --- | --- |
| `--host HOST` | Required Pi hostname or SSH alias to probe. Example: `./scripts/check_pi_connectivity.sh --host pi0w`. |
| `--user USER` | SSH user. Default: current local user. |
| `--link-local IPV6` | Known Pi link-local IPv6 address without `%scope`. |
| `--interface IFACE` | Workstation network interface used with `--link-local`. Example: `wlp38s0`. |
| `--timeout SEC` | Connect timeout for ping and SSH probes. Default: `5`. |

### `setup_persistent_bluetooth_state.sh`

Prepare the writable ext4-backed storage for `/var/lib/bluetooth` before enabling OverlayFS.

| Argument | Explanation / Example |
| --- | --- |
| `--device DEVICE_PATH` | Required writable ext4 device or partition to mount at the persistent state path. No default. Example: `sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/mmcblk0p3`. |

### `enable_readonly_overlayfs.sh`

Switch Raspberry Pi OS into persistent read-only operation after the writable Bluetooth-state mount has already been prepared.

### `disable_readonly_overlayfs.sh`

Return the system to normal writable mode while keeping the persistent Bluetooth-state configuration available.

## Managed paths

| Path | Purpose |
| --- | --- |
| `/opt/bluetooth_2_usb` | Managed installation root |
| `/opt/bluetooth_2_usb/venv` | Managed virtual environment |
| `/etc/default/bluetooth_2_usb` | Structured runtime configuration for the service |
| `/etc/default/bluetooth_2_usb_readonly` | Persistent read-only mode configuration |
| `/var/log/bluetooth_2_usb` | Script and report output |
| `/mnt/b2u-persist` | Default persistent mount target |
| `/mnt/b2u-persist/bluetooth` | Default persistent Bluetooth state directory |
| `/etc/systemd/system/bluetooth_2_usb.service` | Installed service unit |

## Development and release

Contributor workflow details live in [CONTRIBUTING.md](CONTRIBUTING.md).

Release tagging and versioning rules are documented in [docs/process/release-versioning-policy.md](docs/process/release-versioning-policy.md).

For practical validation and debugging workflows, also see:

- [docs/pi/cli-service-test.md](docs/pi/cli-service-test.md)
- [docs/pi/boot-optimization.md](docs/pi/boot-optimization.md)
- [docs/pi/connectivity-troubleshooting.md](docs/pi/connectivity-troubleshooting.md)
- [docs/pi/connectivity-recovery.md](docs/pi/connectivity-recovery.md)
- [docs/pi/host-relay-loopback.md](docs/pi/host-relay-loopback.md)
- [docs/pi/manual-test-plan.md](docs/pi/manual-test-plan.md)
- [docs/process/doc-consistency-review.md](docs/process/doc-consistency-review.md)

## License

This project is licensed under the [MIT License](LICENSE).

The overview image is by Laura T. and is licensed under [CC BY-NC 4.0](http://creativecommons.org/licenses/by-nc/4.0/).

## Acknowledgments

- [Mike Redrobe](https://github.com/mikerr/pihidproxy) for the original Pi HID proxy idea
- [HeuristicPerson](https://github.com/HeuristicPerson/bluetooth_2_hid) for related prior art
- [Georgi Valkov](https://github.com/gvalkov) for [`python-evdev`](https://github.com/gvalkov/python-evdev)
- [Adafruit](https://www.adafruit.com/) for CircuitPython HID and Blinka, which helped make USB gadget access much smoother
- Everyone who tests the project on real hardware and reports what works, what fails, and how to improve it

---

<div align="center">

👀 Written by Eyes<br>
🤖 Assisted by Technology and AI<br>
☕ Powered by Coffee<br>
🫶 Developed with Love

</div>
