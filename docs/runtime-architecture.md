# Runtime Architecture

The service runtime is intentionally centered on one asyncio event flow:

- `Runtime` owns startup, signal handling, and shutdown coordination.
- `RuntimeEventSource` converts UDC state polling and udev input hotplug into
  typed runtime events.
- `RelaySupervisor` consumes those events and owns all selected input relay
  tasks.
- `RelayGate` tracks why relaying is active or inactive: host cable state, user
  pause state, and HID write suspension are separate causes.
- `InputRelay` reads one evdev device, handles per-device grab state, applies
  the optional interrupt shortcut, and forwards events to HID dispatch.
- `HidDispatcher` owns HID translation, mouse frame coalescing, large mouse
  delta chunking, HID write retry, and write-failure suspension.
- `HidGadgets` owns the configured keyboard, mouse, and consumer-control HID
  handles created from `hid_gadget_config.py` and `hid_gadget_layout.py`.

Runtime events are plain value objects from `runtime_events.py`:

- `DeviceAdded`
- `DeviceRemoved`
- `UdcStateChanged`
- `ShutdownRequested`

This keeps service control in the event loop. Signal handlers, UDC polling,
udev hotplug, relay start, relay cancellation, and gadget release all converge
through the same queue instead of calling across thread or callback boundaries.

## Shutdown

Shutdown is requested by enqueueing `ShutdownRequested`. The supervisor stops
scheduling new work, cancels active relay tasks, marks the host side inactive in
`RelayGate`, and releases all HID gadget state once. The runtime also stops the
event source and applies a bounded graceful shutdown timeout so systemd stop
handling remains predictable.

## Cable State

`UdcStateChanged("configured")` marks the host side configured. Any other UDC
state marks the host side inactive and releases current HID gadget state. User
pause state is independent, so reconnecting the USB cable does not undo a manual
pause. A HID `BrokenPipeError` suspends writes until a fresh configured
transition arrives.

## Hotplug

`DeviceAdded` starts one probe task for the matching `/dev/input/event*` path
with a short bounded retry window because udev can report an input node before
all metadata is ready. `DeviceRemoved` cancels the probe and active relay for
that path.

Startup enumeration and later hotplug use the same filter path, so
auto-discovery and explicit device identifiers behave consistently.

## Operational Commands

Managed install, update, uninstall, smoketest, debug, read-only setup, and
loopback entrypoints are owned by `bluetooth_2_usb.ops`. The initial install
can run directly from the source tree with `PYTHONPATH=src`; after installation
the managed venv exposes `bluetooth_2_usb`.

Keeping operational behavior in Python removes the old shell-library boundary:
boot config parsing, rfkill cleanup, read-only state files, systemd unit
generation, diagnostics, and loopback handoff can now share constants,
validation helpers, formatters, linting, and focused unit tests.
