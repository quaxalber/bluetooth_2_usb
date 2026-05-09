# Testing Strategy

The test suite is split by behavior surface rather than by implementation
layer. Keep tests close to the user-visible command or runtime contract they
protect, and add lower-level tests only when a helper has meaningful branching
or is shared across surfaces.

## Default Checks

Run focused unit tests while editing, then run the full suite before pushing
changes that affect runtime behavior, diagnostics, installation, or docs that
describe commands.

```bash
venv/bin/python -m unittest discover -s tests -v
venv/bin/ruff check src tests
venv/bin/black --check src tests
```

## Hardware-Aware Changes

Use Pi validation when a change affects service startup, USB gadget setup, UDC
state handling, relay behavior, read-only mode, diagnostics, or operational
commands. The minimum Pi-side diagnostics remain:

```bash
sudo bluetooth_2_usb smoketest --verbose
sudo bluetooth_2_usb debug --duration 10
```

For relay-path changes, add host/Pi loopback validation from
[host-relay-loopback.md](host-relay-loopback.md). For read-only storage work,
use [persistent-readonly.md](persistent-readonly.md).

## Test Structure

Prefer constants for repeated patch module prefixes, especially in large suites.
Use grouped `with` statements or `ExitStack` for related patches so setup stays
flat and the behavior under test remains visible.
