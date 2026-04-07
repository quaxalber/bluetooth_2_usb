# Pi Manual Test Plan

This plan covers the checks that still need a human on the Raspberry Pi or at the connected target host.

Use it after the automated CLI and service playbook has already passed.

## Goal

Confirm that the current code works not just at the script and service level, but also in the real hardware scenarios that matter:

- Bluetooth pairing and reconnect behavior
- read-only mode after reboot
- persistent Bluetooth state with real storage
- OTG HID behavior on the target host
- long-running network stability on the Pi

## Preconditions

Before running this manual plan, these should already be true:

- `smoke_test.sh --verbose` passes
- `debug.sh --duration 10 --redact` produces a sane report
- the `smoke_test.sh` and `debug.sh` output has been reviewed for correctness and internal consistency, not just exit status
- install, update, uninstall, bootstrap, and tag-based install have already been validated
- the Pi is on the code revision you actually want to evaluate

Useful baseline commands:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact
systemctl is-active bluetooth_2_usb.service
python3 -m bluetooth_2_usb --version 2>/dev/null || bluetooth_2_usb --version
```

## 1. Normal runtime with real input devices

Purpose:

- confirm that the Pi sees the intended keyboards and mice
- confirm that Bluetooth-2-USB activates relays for them

Run on the Pi:

```bash
sudo /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --list_devices
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

What to check manually:

- the expected keyboard or mouse appears in the device list
- the journal shows relay activation for the expected `/dev/input/event*`
- no repeated crash or restart loop is visible

Pass criteria:

- intended devices are listed
- service remains active
- relay activation is visible in the journal

## 2. OTG target host end-to-end input

Purpose:

- confirm that input actually reaches the target host

This is the most important remaining functional test. Agentic checks cannot prove this.

Start this on the Pi first:

```bash
journalctl -u bluetooth_2_usb.service -f
```

Then on the target host:

- connect the Pi OTG/device port
- focus a text field
- type a distinctive string
- repeat with `Shift`, `Ctrl`, `Alt`, and function keys
- if a mouse is involved, also test movement, left click, right click, and wheel

What to note:

- whether the host enumerates the gadget reliably
- whether the host sees the keyboard and mouse as expected
- whether key presses are delayed, duplicated, or dropped
- whether the wrong HID profile is in use

If you want a captured report afterwards, run:

```bash
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact
```

Pass criteria:

- the target host receives the intended input
- no stuck modifiers
- no relay interruption under normal use

## 3. Windows host compatibility

Purpose:

- confirm that the `compat` profile really behaves on Windows

Run on the Pi before testing:

```bash
systemctl is-active bluetooth_2_usb.service
sudo /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --version
journalctl -u bluetooth_2_usb.service -n 50 --no-pager
```

Then on the Windows host:

- confirm enumeration in Device Manager
- type in Notepad and a browser text field
- test modifiers and function keys
- unplug and reconnect the OTG cable once

What to note:

- whether enumeration is stable
- whether Windows delays or suppresses input
- whether reconnect requires manual intervention

Pass criteria:

- normal typing works
- reconnect works without reinstalling the device
- no obvious HID descriptor problem remains

## 4. BIOS / boot menu / pre-OS host validation

Purpose:

- confirm the actual reason this project exists: pre-OS HID compatibility

Run on the Pi before connecting to the target machine:

```bash
systemctl is-active bluetooth_2_usb.service
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh
```

Then on the target machine:

- enter BIOS, UEFI, or the boot device picker
- try arrow keys, `Enter`, `Esc`, and any relevant function keys

Pass criteria:

- the target machine accepts keyboard input before the OS boots

## 5. Easy read-only mode after reboot

Purpose:

- confirm the supported best-effort read-only flow actually boots and reports cleanly

Enable easy mode on the Pi:

```bash
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode easy
sudo reboot
```

After reboot:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact
findmnt /
sudo raspi-config nonint get_overlay_now
cat /etc/default/bluetooth_2_usb_readonly
```

What to check manually:

- the system comes back cleanly
- `overlay_status` reports enabled
- the service still starts and runs
- relay behavior still works

Important interpretation:

- easy mode does not guarantee Bluetooth pairing persistence
- OverlayFS only makes the writable layer live in RAM
- this reduces writes to the root filesystem, but does not create durable Bluetooth persistence

Pass criteria:

- system boots
- service runs
- smoke and debug remain sane
- OTG input still works

## 6. Persistent mode with real storage

Purpose:

- validate the fully supported read-only mode with real writable ext4 storage for `/var/lib/bluetooth`

You need one of:

- a spare USB storage device
- an extra ext4 partition on the system SD card

Recommended first choice:

- a separate USB storage device

Why:

- easier to swap, wipe, or retry
- less risk than repartitioning the system card
- better at reducing write wear on the system SD card

Important note:

- an extra ext4 partition on the same SD card solves persistence
- it does not reduce SD wear in the same way as putting the writable state on separate storage

Identify the device:

```bash
lsblk -f
```

If needed, create ext4 on the real spare device:

```bash
sudo mkfs.ext4 -L B2U_PERSIST /dev/YOUR-DEVICE
```

Prepare persistent Bluetooth state:

```bash
sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/YOUR-DEVICE
```

Enable persistent read-only mode:

```bash
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode persistent
sudo reboot
```

After reboot:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact
findmnt /var/lib/bluetooth
findmnt /mnt/b2u-persist
cat /etc/default/bluetooth_2_usb_readonly
```

What to verify:

- `/mnt/b2u-persist` is mounted from the intended ext4 storage
- `/var/lib/bluetooth` is a bind mount from that persistent location
- `bluetooth_2_usb.service` still starts normally

Pass criteria:

- persistent mount is active
- bind mount is correct
- service and relay still work

## 7. Bluetooth pairing persistence across reboot

Purpose:

- confirm the real value of persistent mode

Before reboot:

```bash
bluetoothctl paired-devices
sudo /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --list_devices
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

Then:

- pair the target Bluetooth keyboard or mouse
- confirm it works on the target host
- reboot the Pi

After reboot:

```bash
bluetoothctl paired-devices
sudo /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --list_devices
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

Pass criteria:

- the paired device remains known after reboot
- reconnect works without re-pairing
- input still reaches the target host

## 8. Bluetooth persistence across hard power loss

Purpose:

- confirm the setup survives a realistic appliance-style interruption

Before cutting power:

```bash
bluetoothctl paired-devices
systemctl is-active bluetooth_2_usb.service
```

Then:

- cut power to the Pi
- restore power
- wait for full boot

After boot:

```bash
systemctl is-active bluetooth_2_usb.service
bluetoothctl paired-devices
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

Pass criteria:

- no re-pairing required
- no broken persistent mount
- no service crash on startup

## 9. Long-running Wi-Fi / SSH stability

Purpose:

- confirm the earlier reachability issue is actually gone

Run these periodically from your workstation:

```bash
ping -c 5 pi4b
ssh -4 pi4b 'hostname'
```

Run this periodically on the Pi:

```bash
nmcli connection show
nmcli -g 802-11-wireless.powersave connection show "YOUR-WIFI-CONNECTION"
journalctl -b -u NetworkManager --no-pager | tail -n 50
```

> Replace `YOUR-WIFI-CONNECTION` with the name shown by `nmcli connection show`.

Pass criteria:

- no unexplained SSH timeouts during normal runtime
- no loss of reachability while the service is active

## 10. What to record for each manual run

Collect this block and paste it into your notes for each run:

```bash
uname -a
cat /etc/os-release
echo MODE=$(grep '^B2U_READONLY_MODE=' /etc/default/bluetooth_2_usb_readonly 2>/dev/null || echo disabled)
echo SERVICE=$(systemctl is-active bluetooth_2_usb.service)
systemctl status bluetooth_2_usb.service --no-pager
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

## Suggested result template

```text
Normal runtime:
- passed / failed
- notes

OTG host input:
- passed / failed
- host type
- notes

Windows compatibility:
- passed / failed
- notes

BIOS / pre-OS:
- passed / failed
- notes

Easy read-only after reboot:
- passed / failed
- notes

Persistent mode with real storage:
- passed / failed
- storage type
- notes

Bluetooth reconnect after reboot:
- passed / failed
- notes

Bluetooth reconnect after power loss:
- passed / failed
- notes

Wi-Fi / SSH long-run stability:
- passed / failed
- notes
```
