# Device Capture

Use device capture when requesting or adding support for a new keyboard, mouse,
gamepad, touchpad, remote, or other Linux input/HID-like device. It collects
source-device metadata, evdev capabilities and input properties, compact live
input snapshots, and best-effort hidraw report summaries from the real device.

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

During the countdown, exercise the controls that should be supported. Press the
keys, buttons, axes, wheels, pads, or remote controls that matter for the
support request. If no controls are used, the artifact can still include useful
static metadata, but the live section will only prove that no input evidence was
observed.

## Arguments

| Argument | Meaning |
| --- | --- |
| `--devices DEVICES` | Comma-separated source input-device filters. Required. |
| `--duration DURATION_SEC` | Capture duration in seconds. Default: `30`. |
| `--output PATH` | JSONL output path. Default: generated under `./device_capture/`. |
| `--grab` | Exclusively grab matched input event devices during capture. |
| `--include-hidraw`, `--no-include-hidraw` | Include matching hidraw reports when available. Default: enabled. |
| `--live-mode {summarized,raw}` | Choose compact summaries or raw event/report records. Default: `summarized`. |
| `--max-report-bytes BYTES` | Maximum bytes retained from one hidraw report. Default: `4096`. |
| `--max-file-bytes BYTES` | Maximum bytes retained from one metadata file. Default: `65536`. |

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

If the matched devices do not expose a usable name, the generated file name uses
`device` rather than the filter text.

The command prints the final file name and a short summary when it finishes.
When run with `sudo`, the artifact is handed back to the invoking sudo user
when possible so it can be copied without requiring sudo.

Use `--output` to choose an explicit path:

```bash
sudo bluetooth_2_usb device capture --devices /dev/input/event4 --duration 30 --grab --output ./device_capture/my_device.jsonl
```

## Summarized And Raw Modes

The default `--live-mode summarized` is preferred for support requests. It
keeps compact per-key, per-axis, per-`EV_MSC`, sync, event-type coverage, and
hidraw report summaries so repeated events do not create unnecessary data
volume. Summarized captures also include a short ordered sample of the first
live evdev events, which helps maintainers see relationships such as
`MSC_SCAN -> KEY_* -> SYN_REPORT` without needing raw mode.

Use raw mode only when a maintainer asks for every event and report:

```bash
sudo bluetooth_2_usb device capture --devices /dev/input/event4 --duration 30 --grab --live-mode raw
```

Raw mode can include every live evdev event and hidraw report observed during
the capture window. Raw default filenames include `_raw` before the timestamp.

## Interrupting Capture

Stop an active capture with `Ctrl-C`. The command writes a partial capture with
an end record when possible, then prints the output path.
