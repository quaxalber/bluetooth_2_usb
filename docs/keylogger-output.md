# Key Event FIFO

The key event FIFO exposes a copy of keyboard input events to other programs while `bluetooth_2_usb` continues its normal HID relay. A separate process can read those events and recognize shortcuts without adding application-specific shortcut handling to the relay.

## Why This Exists

Some integrations need to react to key combinations, not change how keys are forwarded. For example, a KVM controller can watch for a shortcut and switch its active target. Keeping that policy in the controller avoids extensive modifications to `bluetooth_2_usb` for each new shortcut or integration. The FIFO is an observation channel; it is not a command channel and its reader does not control which events reach the USB host.

## Reading Events

The FIFO emits one `InputEvent(...)` record per line, with the event's timestamp, type, code, and value. Consumers should parse the fields they need, track key press and release state, and ignore unrelated event types. For example:

```text
InputEvent(1790353030, 940110, 1, 46, 1)
InputEvent(1790353030, 960000, 1, 46, 0)
```

The first line represents a press and the second a release for the same key code. These are input event codes, not characters; interpreting a shortcut is the consumer's responsibility.

Read the FIFO from a separate process using the path configured for the service. A FIFO reader must be running to receive events; it is not a durable log and events are not replayed when a reader reconnects. If a reader cannot keep up, the relay should continue rather than block on the integration.

## Security

Keyboard events can contain sensitive input. Restrict access to the FIFO and avoid writing its contents to persistent logs. Only run consumers that you trust with keyboard input.
