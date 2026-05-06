# Device Capture

Use device capture when requesting or adding support for a new keyboard, mouse,
gamepad, touchpad, remote, or other Linux input/HID-like device. It collects
source-device metadata, evdev capabilities, compact live input snapshots, and
best-effort hidraw report summaries from the real device.

Capture output is redacted with the same pipeline used by diagnostics reports,
but captures are still local artifacts that can include typed keys, button
presses, raw report bytes, MAC addresses, and unique device IDs. Review the
JSONL before sharing it publicly.

## Basic Capture

```bash
sudo bluetooth_2_usb device capture --devices /dev/input/event4 --duration 30 --grab
```

`--devices` accepts a comma-separated list of input device filters. Each filter
may match an input event path, `uniq`, `phys`, Bluetooth MAC address, or
case-insensitive name fragment. If the filters match multiple input event
devices, all matches are captured into the same JSONL artifact.

`--grab` exclusively grabs the matched input event devices while capture runs.
Use it when collecting support data so the Pi desktop/session does not also
consume the same input. While grabbed, those inputs may not control the Pi
locally.

## Name Or MAC Filter

```bash
sudo bluetooth_2_usb device capture --devices "Magic Trackpad" --duration 30 --grab
```

Name fragments are matched case-insensitively. Bluetooth MAC filters are useful
when one physical device exposes several event nodes with related names.

## Output Location

When `--output` is omitted, captures are written under the current directory:

```text
./device_capture/<matched-device-name>[_raw]_<timestamp>.jsonl
```

The command prints the final file name and a short summary when it finishes.
When run with `sudo`, the artifact is handed back to the invoking sudo user
when possible so it can be copied without requiring sudo.

Use `--output` to choose an explicit path:

```bash
sudo bluetooth_2_usb device capture --devices /dev/input/event4 --duration 30 --grab --output ./device_capture/my_device.jsonl
```

## Summarized And Raw Modes

The default `--live-mode summarized` is preferred for support requests. It
keeps compact per-key, per-axis, sync, and hidraw report summaries so repeated
events do not create unnecessary data volume.

Use raw mode only when a maintainer asks for every event and report:

```bash
sudo bluetooth_2_usb device capture --devices /dev/input/event4 --duration 30 --grab --live-mode raw
```

Raw mode can include every live evdev event and hidraw report observed during
the capture window. Raw default filenames include `_raw` before the timestamp.

## Interrupting Capture

Stop an active capture with `Ctrl-C`. The command writes a partial capture with
an end record when possible, then prints the output path.
