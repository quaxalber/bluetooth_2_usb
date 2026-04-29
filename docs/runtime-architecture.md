# Runtime Architecture

The service runtime is intentionally centered on one asyncio event flow:

- `Runtime` owns startup, signal handling, and shutdown coordination.
- `RuntimeEventSource` converts UDC state polling and udev input hotplug into
  typed runtime events.
- `RelaySupervisor` consumes those events and owns all selected input relay
  tasks.
- `InputRelay` reads one evdev device and writes HID reports to the shared USB
  gadget objects.
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
scheduling new work, cancels active relay tasks, clears relay-active state, and
releases all HID gadget state once. The runtime also stops the event source and
applies a bounded graceful shutdown timeout so systemd stop handling remains
predictable.

## Cable State

`UdcStateChanged("configured")` enables relaying. Any other UDC state disables
relaying and releases current HID gadget state. This prevents stuck keys or
buttons from surviving a cable disconnect, suspend transition, or host-side USB
reset.

## Hotplug

`DeviceAdded` probes a matching `/dev/input/event*` path with a short bounded
retry window because udev can report an input node before all metadata is ready.
`DeviceRemoved` cancels any pending probe and active relay for that path.

Startup enumeration and later hotplug use the same filter path, so
auto-discovery and explicit device identifiers behave consistently.

## Operational Commands

Managed install, update, uninstall, smoketest, debug, read-only setup, and
loopback entrypoints are owned by `bluetooth_2_usb.ops`. The files in
`scripts/` only locate the checkout Python environment, set `PYTHONPATH` for
source-tree execution, and dispatch to `python -m bluetooth_2_usb.ops`.

Keeping operational behavior in Python removes the old shell-library boundary:
boot config parsing, rfkill cleanup, read-only state files, systemd unit
generation, diagnostics, and loopback handoff can now share constants,
validation helpers, formatters, linting, and focused unit tests.
