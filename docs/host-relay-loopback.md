# Pi-to-Host Relay Loopback Test

Use this guide when you need to prove that the relay path works end to end
without depending on a paired Bluetooth keyboard or mouse.

The flow is:

1. prepare a host Python environment with `hidapi`
2. start a host-side capture against the gadget HID device
3. inject deterministic virtual keyboard, mouse, and consumer-control events on the Pi
4. verify that the capture observes the expected relayed sequence

This validates the path:

`Pi virtual input device -> bluetooth_2_usb relay -> USB HID gadget -> host HID device`

Start every physical validation session with `node-discovery`. It identifies
the active keyboard, mouse, and consumer HID nodes with the smallest practical
host-side signal before running broader scenarios.

For regular full-path validation after node discovery, run `combo`. It
exercises the keyboard, mouse, and consumer-control paths in one pass. Use
`keyboard`, `mouse`, or `consumer` only when you need to isolate a specific
domain. The keyboard scenario includes the text burst plus extended function,
navigation, system, and application keys. The consumer scenario includes volume,
media transport, menu/application, and browser/navigation controls.

> [!WARNING]
> Loopback scenarios inject real host-visible HID reports. Even
> `node-discovery` can leak keyboard, mouse, or consumer-control input to the
> host UI. Run these scenarios only in a test session where unexpected key,
> pointer, scroll, media, navigation, or application-launch effects are
> acceptable.

The `node-discovery` scenario is intentionally tiny: it emits one F13
press/release pair, two mouse relative events (`REL_X=1`, `REL_X=-1`), and the
consumer volume up/down press/release pair. It is useful when duplicate gadget
instances are visible and you need to find which keyboard, mouse, and consumer
nodes are live before running `combo`.

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
sudo venv/bin/bluetooth_2_usb udev install --repo-root "$PWD"
```

For a managed host-side install, use:

```bash
sudo bluetooth_2_usb udev install
```

Recommended baseline checks on the Pi:

```bash
sudo bluetooth_2_usb smoketest --verbose
sudo bluetooth_2_usb debug --duration 10
```

## 1. Confirm host-side enumeration

On Linux:

```bash
venv/bin/bluetooth_2_usb loopback capture --scenario node-discovery --output json
```

Experimental: macOS

```bash
venv/bin/bluetooth_2_usb loopback capture --scenario node-discovery --output json
```

> [!NOTE]
> Experimental - unvalidated on real macOS hosts. The macOS variant uses the
> same capture command, but it has not yet been validated on real macOS
> hardware.

On Windows:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m bluetooth_2_usb loopback capture --scenario node-discovery --output json
```

If the Pi gadget is visible, the output will include candidate keyboard, mouse,
or consumer HID device paths even if the short timeout expires. On Windows,
strict capture of the actual relay sequence uses Raw Input; `hidapi` remains a
discovery step, not the primary event backend. Use a Python environment where
`python -c "import hid"` succeeds.

> [!NOTE]
> Loopback JSON is intentionally summarized. Normal injector output reports the
> scenario name, timing, device names, and expected event counts instead of the
> full event sequence. Capture timeouts report the candidates, any nodes that
> completed before the timeout, per-role progress counters, and the next
> expected event. They do not dump the full remaining sequence.

With the repository virtual environment on Windows:

```powershell
.\venv\Scripts\python.exe -m bluetooth_2_usb loopback capture --scenario keyboard --output json
```

## 2. Start the host capture

From the repository checkout on the host:

```bash
venv/bin/bluetooth_2_usb loopback capture --scenario combo
```

Default behavior:

- detects the gadget HID device by product name and HID usage
- waits up to the scenario-specific timeout for the complete sequence (`10`
  seconds by default; `keyboard` uses `15` seconds and `combo` uses `30`
  seconds)
- may temporarily claim the gadget HID interfaces while the capture runs, so do
  not assume the local desktop will process the same inputs during that window
- uses a single loopback lock file; do not run multiple inject/capture sessions
  in parallel against the same host/Pi pair

If automatic detection is ambiguous, pin the nodes explicitly:

```bash
venv/bin/bluetooth_2_usb loopback capture \
  --scenario combo \
  --keyboard-node '<candidate keyboard path>' \
  --mouse-node '<candidate mouse path>' \
  --consumer-node '<candidate consumer path>'
```

Keep this command running while you trigger the Pi-side injection.

When duplicate gadget instances are visible, first identify the active nodes
with the minimal discovery scenario:

```bash
venv/bin/bluetooth_2_usb loopback capture \
  --scenario node-discovery \
  --keyboard-node '<candidate keyboard path>' \
  --mouse-node '<candidate mouse path>' \
  --consumer-node '<candidate consumer path>'
```

Then, on the Pi:

```bash
sudo bluetooth_2_usb loopback inject --scenario node-discovery
```

Use the node set that succeeds here when pinning the full `combo` capture.

> [!IMPORTANT]
> Before each fresh Windows validation run after changing the gadget descriptor
> layout or USB identity:

1. set the Pi to the intended software revision
2. reboot the Pi
3. perform a Windows PnP admin reset
4. only then start the host capture

## 3. Trigger the Pi-side injection

On the Pi:

```bash
sudo bluetooth_2_usb loopback inject --scenario combo
```

> [!NOTE]
> When `bluetooth_2_usb.service` is active, the injector waits up to the default
> service-settle window before emitting events. This avoids racing a freshly
> re-enumerated USB HID gadget before the host has started draining reports. Set
> `B2U_LOOPBACK_SERVICE_SETTLE_SEC=0` to disable that loopback-only wait.
> Invalid values are ignored and the default settle window is used.

The injector creates temporary virtual devices named:

- `B2U Test Keyboard`
- `B2U Test Mouse`
- `B2U Test Consumer`

and emits this deterministic sequence:

- keyboard: an alternating-case burst with modifier transitions
- mouse: large relative X/Y movement, vertical wheel deltas, horizontal pan
  deltas, then all configured mouse button bits press/release
- node-discovery: F13 press/release, `REL_X=1`, `REL_X=-1`, and consumer
  volume up/down press/release
- consumer: volume, media transport, menu/application, and browser/navigation
  controls

For mouse wheel and horizontal wheel steps, the injector emits paired low-res
and high-res evdev events in the same `SYN_REPORT` frame. The host capture
expects the relay to emit one equivalent USB HID wheel or pan step.

The mouse gadget report uses one button byte, signed 16-bit relative X/Y, and
signed 8-bit vertical wheel and horizontal pan.

On Windows, the current Raw Input capture backend only maps mouse button bits
through `BTN_EXTRA`. Windows can still run every public scenario, but mouse
button validation is partial for `mouse` and `combo`; skipped buttons are
reported as `windows_skipped_mouse_buttons`.

## 4. Success criteria

The host capture exits `0` and reports that it observed the expected relay
reports on the host gadget HID device.

The Pi-side injector exits `0` and reports that it injected the expected test
sequence through `/dev/uinput`.

Injector JSON includes a compact expectation summary:

```json
{
  "expected": {
    "name": "combo",
    "keyboard_steps": 250,
    "mouse_rel_steps": 8,
    "mouse_button_steps": 16,
    "consumer_steps": 26,
    "total_steps": 300
  }
}
```

Timeout JSON focuses on the useful debugging state:

```json
{
  "message": "Timed out waiting for combo reports after 30.0s",
  "details": {
    "summary": {
      "keyboard": "250/250 complete",
      "mouse": "2/8 rel, 0/16 buttons",
      "consumer": "0/26"
    },
    "progress": {
      "mouse": [
        {
          "node": "/dev/hidraw3",
          "rel_steps_seen": 2,
          "rel_steps_expected": 8,
          "button_steps_seen": 0,
          "button_steps_expected": 16,
          "next_expected_rel": "REL_X=-210000"
        }
      ]
    }
  }
}
```

Windows Raw Input capture also includes aggregate message counts and a small
sample of observed events for device-matching issues; it intentionally avoids a
complete Raw Input event stream.

## 5. Useful variants

Keyboard-only:

```bash
venv/bin/bluetooth_2_usb loopback capture --scenario keyboard
sudo bluetooth_2_usb loopback inject --scenario keyboard
```

Mouse-only:

```bash
venv/bin/bluetooth_2_usb loopback capture --scenario mouse
sudo bluetooth_2_usb loopback inject --scenario mouse
```

Consumer-control only:

```bash
venv/bin/bluetooth_2_usb loopback capture --scenario consumer
sudo bluetooth_2_usb loopback inject --scenario consumer
```

Minimal node discovery:

```bash
venv/bin/bluetooth_2_usb loopback capture --scenario node-discovery
sudo bluetooth_2_usb loopback inject --scenario node-discovery
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
sudo venv/bin/bluetooth_2_usb udev install --repo-root "$PWD"
```

For a managed host-side install, run `sudo bluetooth_2_usb udev install`
instead.

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
sudo bluetooth_2_usb --list_devices --output json
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

The loopback sequence is intentionally forceful enough to validate chunked
mouse motion, scrolling, modifier transitions, and all configured mouse button
bits, so the capture should be treated as a dedicated verification session
rather than as a transparent observer.

### Loopback says it is already running

The loopback validator uses a single lock file and will reject parallel runs. If no other
run is active, clear the stale lock file and retry.

Lock paths:

- host Windows: `%TEMP%\bluetooth_2_usb_loopback.lock`
- host Linux/macOS: `/tmp/bluetooth_2_usb_loopback.lock`
- Pi: `/tmp/bluetooth_2_usb_loopback.lock`

## 7. CI scope

This exact loopback test is hardware-only and is not expected to run inside
GitHub Actions.

CI should instead cover:

- scenario definitions
- node autodetection and deduplication
- event matching logic
- CLI argument parsing
- exit-code behavior
