# Pi-to-Host Relay Loopback Test Playbook

Use this playbook when you need to prove that the relay path works end to end
without depending on a paired Bluetooth keyboard or mouse.

The flow is:

1. install the host-side `hidraw` udev rule
2. start a host-side capture against the gadget `hidraw` nodes
2. inject deterministic virtual keyboard and mouse events on the Pi
3. verify that the capture observes the expected relayed sequence

This validates the path:

`Pi virtual input device -> bluetooth_2_usb relay -> USB HID gadget -> host hidraw node`

## Preconditions

- the Pi is connected to the host through the OTG-capable data path
- `bluetooth_2_usb.service` is active on the Pi
- `B2U_AUTO_DISCOVER=1` is enabled in `/etc/default/bluetooth_2_usb`
- `/dev/uinput` exists on the Pi
- the host is Linux
- the host user running the capture is in the `input` group
- the host already sees the Pi gadget `hidraw` nodes

On the host, install the udev rule once:

```bash
sudo ./scripts/install_host_hidraw_udev_rule.sh
```

Then verify the group membership before running the capture:

```bash
id
```

If the user is not yet in the `input` group, add it and start a fresh login
session before continuing:

```bash
sudo usermod -aG input "$USER"
```

Recommended baseline checks on the Pi:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 5
```

## 1. Confirm the host-side gadget nodes

On the host:

```bash
ls -l /dev/hidraw* /dev/input/by-id/*USB_Combo_Device*hidraw*
```

You should see `hidraw` entries for the Pi gadget. After the udev rule is
active, the matching nodes should no longer be `root:root 0600`.

## 2. Start the host capture

From the repository checkout on the host:

```bash
./scripts/host_relay_test_capture.sh --scenario combo
```

Default behavior:

- detects the gadget `hidraw` nodes from sysfs
- waits up to `5` seconds for the complete sequence

If automatic detection is ambiguous, pin the nodes explicitly:

```bash
./scripts/host_relay_test_capture.sh \
  --scenario combo \
  --keyboard-node /dev/hidrawX \
  --mouse-node /dev/hidrawY
```

Keep this command running while you trigger the Pi-side injection.

## 3. Trigger the Pi-side injection

On the Pi:

```bash
sudo /opt/bluetooth_2_usb/scripts/pi_relay_test_inject.sh --scenario combo
```

The injector creates temporary virtual devices named:

- `B2U Test Keyboard`
- `B2U Test Mouse`

and emits this deterministic sequence:

- keyboard: `KEY_A`, `KEY_B`, `KEY_C` down/up
- mouse: `REL_X +30`, `REL_Y +15`, `BTN_LEFT` down/up

## 4. Success criteria

The host capture exits `0` and reports that it observed the expected relay
reports on the host gadget `hidraw` nodes.

The Pi-side injector exits `0` and reports that it injected the expected test
sequence through `/dev/uinput`.

## 5. Useful variants

Keyboard-only:

```bash
./scripts/host_relay_test_capture.sh --scenario keyboard
sudo /opt/bluetooth_2_usb/scripts/pi_relay_test_inject.sh --scenario keyboard
```

Mouse-only:

```bash
./scripts/host_relay_test_capture.sh --scenario mouse
sudo /opt/bluetooth_2_usb/scripts/pi_relay_test_inject.sh --scenario mouse
```

Consumer-control only:

```bash
./scripts/host_relay_test_capture.sh --scenario consumer
sudo /opt/bluetooth_2_usb/scripts/pi_relay_test_inject.sh --scenario consumer
```

## 6. Failure interpretation

### Host capture says no gadget nodes were found

- the Pi gadget may not be enumerated on the host
- the OTG cable or port may be wrong
- the host may not expose the gadget `hidraw` interfaces yet

Check:

```bash
ls -l /dev/hidraw* /dev/input/by-id/*USB_Combo_Device*hidraw*
```

### Host capture fails opening the gadget hidraw nodes

The host user likely cannot read `/dev/hidraw*`, or the udev rule has not been
applied yet.

Check:

```bash
id
ls -l /dev/hidraw* /dev/input/by-id/*USB_Combo_Device*hidraw*
```

If needed, install or re-apply the rule and then start a fresh login session:

```bash
sudo ./scripts/install_host_hidraw_udev_rule.sh
sudo usermod -aG input "$USER"
```

### Host capture times out

- the relay service on the Pi may not be active
- auto-discovery may be off
- the Pi may not have picked up the temporary virtual devices
- the host gadget hidraw path may be present but not currently carrying reports

Check on the Pi:

```bash
systemctl is-active bluetooth_2_usb.service
sudo /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --list_devices --output json
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

### Pi injection fails with missing `/dev/uinput`

The kernel/device access prerequisite for virtual test devices is missing.

Check:

```bash
ls -l /dev/uinput
```

### Host capture still affects the local desktop

The `hidraw` capture path should not inject input into the desktop at all. If
you still observe host-side effects, confirm that the host capture is using the
`hidraw` path and not an older checkout of the evdev-based harness.

## 7. CI scope

This exact loopback test is hardware-only and is not expected to run inside
GitHub Actions.

CI should instead cover:

- scenario definitions
- node autodetection and deduplication
- event matching logic
- CLI argument parsing
- exit-code behavior
