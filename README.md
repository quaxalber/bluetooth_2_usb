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

On current Raspberry Pi OS 64-bit Lite images, the installer also clears a
common Bluetooth soft-blocked `rfkill` default so pairing can start from a
known-good controller state.

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
- [Configuration](#configuration)
- [CLI reference](#cli-reference)
- [Day-to-day usage](#day-to-day-usage)
- [Updating](#updating)
- [Uninstalling](#uninstalling)
- [Diagnostics](#diagnostics)
- [Persistent read-only operation](#persistent-read-only-operation)
- [Optional host wake from suspend](#optional-host-wake-from-suspend)
- [Optional boot optimization](#optional-boot-optimization)
- [Troubleshooting](#troubleshooting)
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
- A small, well-supported diagnostics surface built around `--validate-env`, `smoke_test.sh`, and `debug.sh`
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

On narrower terminals, columns such as `Device` and `Exclusion Reason` may wrap onto multiple lines.

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

Bluetooth-2-USB supports the normal writable mode and one persistent read-only mode for appliance-like deployments.

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
> Double-check the target with `lsblk -f` before formatting or enabling persistent Bluetooth state.

> [!NOTE]
> In principle you can also take the writable space from the same physical
> device that holds the root filesystem, for example by carving out a separate
> ext4 partition on that SD card or SSD. That avoids extra physical media, but
> it does not reduce SD-card wear the way moving that writable state to a USB
> stick or other separate storage can. It also increases the risk of
> partitioning mistakes and gives you less separation during maintenance or
> recovery.

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

## Optional host wake from suspend

Bluetooth-2-USB can wake a sleeping or suspended host when you use the optional
custom-kernel workflow in
[pi-remote-wakeup-kernel-playbook.md](docs/pi-remote-wakeup-kernel-playbook.md).

This has been tested on a Pi 4B with:

- Raspberry Pi 4 Model B Rev 1.4
- patched `rpi-6.12.y` kernel `6.12.81-b2u-wake+`
- installed `/boot/config-$(uname -r)` for built-in gadget-driver detection
- keyboard-only `wakeup_on_write` enabled:
  - `hid.usb0=1`
  - `hid.usb1=0`
  - `hid.usb2=0`

On that tested setup, wake from host suspend works through normal keyboard
input relayed by Bluetooth-2-USB.

The playbook has also been exercised successfully on a Raspberry Pi Zero W
with patched kernel `6.12.81-b2u-wake`, the documented ARM32 LLVM fallback,
keyboard-only `wakeup_on_write`, a passing post-reboot smoketest after
clearing persistent `systemd-rfkill` Bluetooth soft-block state, and confirmed
end-to-end wake from host suspend through normal keyboard input relayed by
Bluetooth-2-USB. Pi 4B and Pi Zero W are both confirmed end-to-end wake
setups; Pi Zero W is also the validated 32-bit bring-up path for the custom
wake kernel.

## Optional boot optimization

If the Pi is already provisioned and no longer needs `cloud-init` on every
boot, you can trim the boot path and optionally freeze the currently working
DHCP IPv4 settings as a static NetworkManager profile.

Preview the changes first:

```bash
sudo /opt/bluetooth_2_usb/scripts/optimize_pi_boot.sh --dry-run --static-ip auto
```

Apply them and reboot automatically:

```bash
sudo /opt/bluetooth_2_usb/scripts/optimize_pi_boot.sh --static-ip auto
```

Use explicit static IPv4 settings instead of freezing the current DHCP lease:

```bash
sudo /opt/bluetooth_2_usb/scripts/optimize_pi_boot.sh \
  --static-ip 192.168.2.215/24 \
  --gateway 192.168.2.1 \
  --dns 1.1.1.1,9.9.9.9,192.168.2.1
```

Rollback is also built in:

```bash
sudo /opt/bluetooth_2_usb/scripts/optimize_pi_boot.sh --rollback
```

## Troubleshooting

Start every troubleshooting pass with the two built-in diagnostics first:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
```

Use `smoke_test.sh` as the quick health gate and `debug.sh` as the fuller redacted state snapshot. The subsections below are for follow-up checks that go beyond what those two tools already collect.

For a real end-to-end relay check without depending on a paired Bluetooth device, use the host/Pi loopback harness in `docs/pi-host-relay-loopback-test-playbook.md`.

### The service does not start

```bash
bluetooth_2_usb --validate-env
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

If `--validate-env` reports `configfs: missing` or `udc: missing`, that usually means you are either not on a Pi gadget-capable system or the Pi has not yet booted with the expected gadget configuration.

### The Pi does not appear as a USB gadget

Check the boot overlay and modules:

```bash
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/firmware/config.txt 2>/dev/null || \
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/config.txt
cat /boot/firmware/cmdline.txt 2>/dev/null || cat /boot/cmdline.txt
```

Interpret those checks conservatively:

- `dtoverlay=dwc2` in `config.txt` should be present.
- `modules-load=` in `cmdline.txt` should still load `libcomposite`, and may also include `dwc2` on kernels where `dwc2` is built as a module.
- On newer 64-bit Bookworm and aarch64 kernels, `CONFIG_USB_DWC2=y` often means `dwc2` is built into the kernel. In that case, the absence of a separate loadable `dwc2` module is normal and not itself a failure.
- Treat missing USB gadget support as the problem, not merely the absence of a loadable module: if `CONFIG_USB_DWC2=y` is present, built-in `dwc2` is fine; otherwise make sure `dtoverlay=dwc2` is set and that `dwc2` is loaded on kernels that require it as a module.

### Specific devices are not being relayed

Check what the runtime can actually see:

```bash
bluetooth_2_usb -l
```

Then verify that `DEVICE_IDS` really matches what the runtime reports. Matching is based on event path, Bluetooth MAC address, or case-insensitive device-name fragment, so stale event numbers or slightly wrong name fragments are common operator mistakes.

If the service looks healthy but the target host still does not react, also check the physical path:

- make sure the Pi is connected through the OTG-capable port, not a normal host-only USB port
- make sure the USB cable carries data, not only power
- on Pi Zero boards, prefer separate stable power and use only the data port for the host connection
- on Pi 4B and Pi 5, try a different USB-C cable or a different host port
- confirm the service is actually active with `systemctl is-active bluetooth_2_usb.service`

If you need to isolate the relay path from Bluetooth pairing state, run the host/Pi loopback harness from `docs/pi-host-relay-loopback-test-playbook.md`.

### Bluetooth pairing or scanning is flaky even though `bluetooth.service` is active

Do not treat `systemctl status bluetooth` on its own as a health check. A running `bluetooth.service` can still leave the controller powered off or rfkill-blocked.

Check the real controller state first:

```bash
sudo bluetoothctl show
sudo btmgmt info
rfkill list
grep -H . /sys/class/rfkill/rfkill*/{soft,hard,state} 2>/dev/null
```

If `smoke_test.sh` or `debug.sh` already show the adapter as healthy, switch to an interactive `bluetoothctl` session and complete the actual bonding flow there. The common failure mode is not missing BlueZ, but an unanswered pairing prompt or a bonding handshake that never completes.

The managed installer already clears common Bluetooth `rfkill` soft blocks on
Raspberry Pi OS Lite during installation. If the controller becomes blocked
again later, inspect the live `rfkill` state instead of assuming the install
did not run.

If the block comes back specifically after a reboot, also inspect the persisted
`systemd-rfkill` state under `/var/lib/systemd/rfkill`. A saved Bluetooth
state of `1` there can re-apply the soft block on later boots even when the
runtime and BlueZ are otherwise healthy.

If you already know the adapter is soft-blocked, clear that first:

```bash
sudo sh -c 'echo 0 > /sys/class/rfkill/rfkill0/soft'
```

If you need that fix to survive reboot, also clear the persisted Bluetooth
state files:

```bash
sudo sh -c 'for f in /var/lib/systemd/rfkill/*:bluetooth; do printf "0\n" > "$f"; done'
sudo rfkill unblock bluetooth
sudo systemctl restart bluetooth
```

Then work interactively:

```bash
sudo bluetoothctl
```

Inside `bluetoothctl`, watch for agent prompts and answer them explicitly. Some BLE devices connect briefly, then drop again unless the authorization prompt is accepted in time. Repeated short `Connected: yes` / `Connected: no` transitions without a durable bonded state usually mean the pairing handshake is not completing, not that the device is already usable.

For stubborn bonding or connect/disconnect flip-flops, use a conservative reset flow:

1. Start an interactive session:

```bash
sudo bluetoothctl
```

2. Reset the adapter state:

```text
power off
power on
```

3. Clear the stale device state and pair again:

```text
block A1:B2:C3:D4:E5:F6
remove A1:B2:C3:D4:E5:F6
scan on
trust A1:B2:C3:D4:E5:F6
pair A1:B2:C3:D4:E5:F6
connect A1:B2:C3:D4:E5:F6
```

`remove` clears the stored BlueZ device record for that device and is often the
right next step when you have a half-broken bonding state. This is a recovery
flow for hard failures, not the normal first pairing attempt.

If the BlueZ device cache itself looks stale, you can clear it more directly.
This is destructive for saved pairings:

```bash
sudo systemctl stop bluetooth
sudo find /var/lib/bluetooth -maxdepth 2 -type d
```

Remove only the affected device directory under the adapter first, then start
Bluetooth again:

```bash
sudo rm -rf '/var/lib/bluetooth/AA:BB:CC:DD:EE:FF/A1:B2:C3:D4:E5:F6'
sudo systemctl start bluetooth
```

Only remove larger parts of `/var/lib/bluetooth` if targeted cleanup does not
help and you are prepared to pair devices again from scratch.

### Persistent read-only mode does not keep Bluetooth pairings

Verify that the writable state is actually mounted where expected:

```bash
findmnt /var/lib/bluetooth
findmnt /mnt/b2u-persist
grep '^B2U_' /etc/default/bluetooth_2_usb_readonly
```

## Script reference

Managed deployment scripts live in `/opt/bluetooth_2_usb/scripts/` after
installation.

### `install.sh`

Apply the current checkout in `/opt/bluetooth_2_usb` to the managed install. This is the main deployment entrypoint for first install and for explicit re-application of the current checkout.

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
`cmdline.txt`, and optionally freeze the current DHCP IPv4 settings as a
static NetworkManager profile. It writes rollback state to
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

Release tagging and versioning rules are documented in [docs/release-versioning-policy.md](docs/release-versioning-policy.md).

For practical validation and debugging workflows, also see:

- [docs/pi-cli-service-test-playbook.md](docs/pi-cli-service-test-playbook.md)
- [docs/pi-host-relay-loopback-test-playbook.md](docs/pi-host-relay-loopback-test-playbook.md)
- [docs/pi-manual-test-plan.md](docs/pi-manual-test-plan.md)
- [docs/doc-consistency-review-playbook.md](docs/doc-consistency-review-playbook.md)

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
