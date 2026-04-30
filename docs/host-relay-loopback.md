# Pi-to-Host Relay Loopback Test

Use this guide when you need to prove that the relay path works end to end
without depending on a paired Bluetooth keyboard or mouse.

The flow is:

1. prepare a host Python environment with `hidapi`
2. start a host-side capture against the gadget HID device
3. inject deterministic virtual keyboard and mouse events on the Pi
4. verify that the capture observes the expected relayed sequence

This validates the path:

`Pi virtual input device -> bluetooth_2_usb relay -> USB HID gadget -> host HID device`

By default, run only the lower-risk scenarios: `keyboard`, `mouse`,
`mouse_fast`, `combo`, and `consumer`. These avoid left, right, middle,
forward, back, and task mouse button down events. Run `mouse_buttons_intrusive`
only when you
intentionally want full live button-bit validation and can tolerate possible
host UI interaction.

## Preconditions

- the Pi is connected to the host through the OTG-capable data path
- `bluetooth_2_usb.service` is active on the Pi
- `B2U_AUTO_DISCOVER=true` is enabled in `/etc/default/bluetooth_2_usb`
- `/dev/uinput` exists on the Pi
- the host Python environment has `hidapi` installed for gadget discovery

Additional Linux preconditions:

- install the host-side USB udev rule
- the host user running the capture is in the `input` group

Prepare the host Python environment once:

```bash
python3 -m pip install -r requirements-host-capture.txt
```

On Linux, install the udev rule once:

```bash
sudo venv/bin/bluetooth_2_usb install-hid-udev-rule --repo-root "$PWD"
```

Recommended baseline checks on the Pi:

```bash
sudo /opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb smoketest --verbose
sudo /opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb debug --duration 10
```

## 1. Confirm host-side enumeration

On Linux:

```bash
venv/bin/bluetooth_2_usb loopback-capture --scenario keyboard --timeout-sec 1 --output json
```

Experimental: macOS

```bash
venv/bin/bluetooth_2_usb loopback-capture --scenario keyboard --timeout-sec 1 --output json
```

> [!NOTE]
> Experimental - unvalidated on real macOS hosts. The macOS variant uses the
> same capture command, but it has not yet been validated on real macOS
> hardware.

On Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\loopback-capture.ps1 --scenario keyboard --timeout-sec 1 --output json
```

If the Pi gadget is visible, the output will include candidate keyboard, mouse,
or consumer HID device paths even if the short timeout expires. On Windows,
strict capture of the actual relay sequence uses Raw Input; `hidapi` remains a
discovery step, not the primary event backend.

## 2. Start the host capture

From the repository checkout on the host:

```bash
venv/bin/bluetooth_2_usb loopback-capture --scenario combo
```

Default behavior:

- detects the gadget HID device by product name and HID usage
- waits up to `5` seconds for the complete sequence
- may temporarily claim the gadget HID interfaces while the capture runs, so do
  not assume the local desktop will process the same inputs during that window
- uses a single harness lock file; do not run multiple inject/capture sessions
  in parallel against the same host/Pi pair

If automatic detection is ambiguous, pin the nodes explicitly:

```bash
venv/bin/bluetooth_2_usb loopback-capture \
  --scenario combo \
  --keyboard-node '<candidate keyboard path>' \
  --mouse-node '<candidate mouse path>'
```

Keep this command running while you trigger the Pi-side injection.

Before each fresh Windows validation run after changing the gadget descriptor
layout or USB identity:

1. set the Pi to the intended software revision
2. reboot the Pi
3. perform a Windows PnP admin reset
4. only then start the host capture

## 3. Trigger the Pi-side injection

On the Pi:

```bash
sudo /opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb loopback-inject --scenario combo
```

When `bluetooth_2_usb.service` is active, the injector waits up to the default
service-settle window before emitting events. This avoids racing a freshly
re-enumerated USB HID gadget before the host has started draining reports. Set
`B2U_LOOPBACK_SERVICE_SETTLE_SEC=0` to disable that harness-only wait. Invalid
values are ignored and the default settle window is used.

The injector creates temporary virtual devices named:

- `B2U Test Keyboard`
- `B2U Test Mouse`

and emits this deterministic sequence:

- keyboard: `KEY_F13`, `KEY_F14`, `KEY_F15` down/up
- mouse: `REL_X +1`, `REL_X -1`, `REL_Y +1`, `REL_Y -1`,
  `REL_WHEEL +1`, `REL_WHEEL -1`, `REL_HWHEEL +1`, `REL_HWHEEL -1`,
  one coalesced `REL_X +2` / `REL_Y -3` / `REL_HWHEEL +1` frame, then
  side/extra mouse button bits press/release

For mouse wheel and horizontal wheel steps, the injector emits paired low-res
and high-res evdev events in the same `SYN_REPORT` frame. The host capture
expects the relay to emit one equivalent USB HID wheel or pan step.

The `mouse_fast` scenario emits large relative X/Y movement plus fast vertical
wheel and horizontal pan deltas that require multiple USB HID reports. Use it to
stress high-speed mouse movement and scrolling forwarding:

```bash
venv/bin/bluetooth_2_usb loopback-capture --scenario mouse_fast
sudo /opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb loopback-inject --scenario mouse_fast
```

The mouse gadget report uses one button byte, signed 16-bit relative X/Y, and
signed 8-bit vertical wheel and horizontal pan.

To validate all eight button bits, run the explicit intrusive button scenario:

```bash
venv/bin/bluetooth_2_usb loopback-capture --scenario mouse_buttons_intrusive
sudo /opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb loopback-inject --scenario mouse_buttons_intrusive
```

On Windows, the current Raw Input capture backend only maps mouse button bits
through `BTN_EXTRA`. It rejects `mouse_buttons_intrusive` with
`EXIT_PREREQUISITE` because that scenario also includes `BTN_FORWARD`,
`BTN_BACK`, and `BTN_TASK`; use the default `mouse` or `combo` scenario there,
or run intrusive button validation on a backend that can surface every button
bit.

## 4. Success criteria

The host capture exits `0` and reports that it observed the expected relay
reports on the host gadget HID device.

The Pi-side injector exits `0` and reports that it injected the expected test
sequence through `/dev/uinput`.

## 5. Useful variants

Keyboard-only:

```bash
venv/bin/bluetooth_2_usb loopback-capture --scenario keyboard
sudo /opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb loopback-inject --scenario keyboard
```

Mouse-only:

```bash
venv/bin/bluetooth_2_usb loopback-capture --scenario mouse
sudo /opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb loopback-inject --scenario mouse
```

Consumer-control only:

```bash
venv/bin/bluetooth_2_usb loopback-capture --scenario consumer
sudo /opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb loopback-inject --scenario consumer
```

## 6. Failure interpretation

### Host capture says no gadget nodes were found

- the Pi gadget may not be enumerated on the host
- the OTG cable or port may be wrong
- the host may not expose the gadget HID device yet
- the host Python may not have `hidapi` installed for discovery

On Linux, also confirm that the udev rule was installed and the Pi was
reconnected afterwards.

### Host capture fails opening the gadget HID device

On Linux this usually means `hidapi` can enumerate the USB gadget but lacks the
required write access to the underlying USB device node.

Check:

```bash
id
ls -l /dev/bus/usb/*/*
```

If needed:

```bash
sudo venv/bin/bluetooth_2_usb install-hid-udev-rule --repo-root "$PWD"
```

### Host capture times out

- the relay service on the Pi may not be active
- auto-discovery may be off
- the Pi may not have picked up the temporary virtual devices
- the host gadget HID device may be present but not currently carrying reports
- on Windows, candidate enumeration may be fine while Raw Input still sees the
  wrong device instance after a stale PnP state; re-run the PnP admin reset

Check on the Pi:

```bash
systemctl is-active bluetooth_2_usb.service
sudo /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --list_devices --output json
sudo journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

### Pi injection fails with missing `/dev/uinput`

The kernel/device access prerequisite for virtual test devices is missing.

Check:

```bash
ls -l /dev/uinput
```

### Host capture changes local desktop behavior

That can happen. Opening the gadget HID interfaces for capture may temporarily
claim them while the test is running, which can reduce or suppress normal local
handling of the same keyboard, mouse, or consumer inputs.

The loopback sequence still uses non-text keyboard keys and tiny mouse-rel
movements so the test remains low-impact if the local desktop does process the
events, but the capture should be treated as a dedicated verification session
rather than as a transparent observer.

### Harness says it is already running

The harness uses a single lock file and will reject parallel runs. If no other
run is active, clear the stale lock file and retry.

Lock paths:

- host Windows: `%TEMP%\bluetooth_2_usb_test_harness.lock`
- host Linux/macOS: `/tmp/bluetooth_2_usb_test_harness.lock`
- Pi: `/tmp/bluetooth_2_usb_test_harness.lock`

## 7. CI scope

This exact loopback test is hardware-only and is not expected to run inside
GitHub Actions.

CI should instead cover:

- scenario definitions
- node autodetection and deduplication
- event matching logic
- CLI argument parsing
- exit-code behavior
