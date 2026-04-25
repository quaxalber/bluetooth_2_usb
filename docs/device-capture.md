# Device Capture

Use this guide when a gamepad, trackpad, drawing tablet, mouse wheel, or
keyboard LED behavior needs real-device data before support can be completed.

The capture helper prints redacted JSON by default:

```bash
sudo /opt/bluetooth_2_usb/scripts/capture-device.sh
```

To capture live events from one device, first list devices:

```bash
bluetooth_2_usb --list_devices --output json
```

Then sample the matching event node while using the controls you care about:

```bash
sudo /opt/bluetooth_2_usb/scripts/capture-device.sh \
  --device /dev/input/event4 \
  --duration 15 \
  --output json
```

The output includes:

- current Bluetooth-2-USB inventory metadata
- event types such as `EV_KEY`, `EV_REL`, `EV_ABS`, and `EV_FF`
- input properties such as pointer/buttonpad hints
- absolute axis ranges, fuzz, flat, and resolution
- detected relay classes
- live evdev events grouped by `SYN_REPORT`

MAC-address-like values are redacted.

## Suggested Samples

For an Apple Magic Trackpad, capture:

- one-finger movement
- physical click
- two-finger vertical scroll
- two-finger horizontal scroll
- three or more fingers moving together

For a DualSense or Xbox controller, capture:

- every face button
- shoulders and triggers
- both sticks, including center release
- D-pad in each direction
- home/guide/share/options buttons where available
- a short host-side rumble test if possible

For a drawing tablet, capture:

- hover movement
- tip down/up
- pressure ramp
- tilt in both axes
- barrel buttons
- eraser, if present
- touch surface gestures, if the tablet exposes a separate touch node

For keyboard LED issues, capture inventory and then run a live relay session while
toggling Caps Lock, Num Lock, and Scroll Lock from the target host.
