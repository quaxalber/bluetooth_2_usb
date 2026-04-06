# Contributing to Bluetooth-2-USB

Thanks for your interest in contributing.

Bug reports, documentation improvements, testing on real hardware, and code changes are all valuable contributions. First-time contributors are welcome.

This guide focuses on the project-specific details you need to make a contribution that is easy to review and verify.

## Ways to contribute

You do not need to submit code to help the project. Useful contributions include:

- Reporting bugs with enough detail to reproduce them
- Testing changes on Raspberry Pi hardware and target hosts
- Improving installation, troubleshooting, and read-only-mode documentation
- Fixing runtime, packaging, or service issues
- Reviewing pull requests and sharing hardware compatibility results

## Development environment

Meaningful runtime validation requires Linux, and changes that affect USB gadget behavior should be tested on a real Raspberry Pi with an OTG-capable connection to a target host.

### Basic setup

```bash
sudo apt update
sudo apt install -y git python3 python3-venv

git clone https://github.com/YOUR-ACCOUNT/bluetooth_2_usb.git
cd bluetooth_2_usb

python3 -m venv venv
source venv/bin/activate
pip install -U pip setuptools wheel
pip install -e .
```

## Project layout

The files most contributors will touch are:

- `src/bluetooth_2_usb/`  
  Python package for the CLI, runtime logic, argument parsing, logging, and relay behavior

- `scripts/`  
  Install, update, uninstall, smoke-test, debug, and read-only helper scripts

- `bluetooth_2_usb.service`  
  systemd unit template used by the installer

- `.github/workflows/ci.yml`  
  Baseline CI checks run on pull requests

## Before you start

For larger changes, open or reference an issue first so the approach can be discussed before significant work is done.

Please keep changes focused:

- Avoid mixing unrelated refactors with functional changes
- Avoid mixing runtime changes with installer or dependency changes unless there is a clear reason
- Update documentation when behavior, paths, commands, or defaults change
- Preserve the managed install model unless the change is intentionally redesigning it

Current managed paths include:

- Install root: `/opt/bluetooth_2_usb`
- Runtime config: `/etc/default/bluetooth_2_usb`
- Service unit: `bluetooth_2_usb.service`

## Quality expectations

Aim for changes that are easy to understand, maintain, and validate.

### For Python code

- Prefer readable, focused functions over clever shortcuts
- Keep public behavior and CLI semantics stable unless the change intentionally revises them
- Match the surrounding code style
- Add or update docstrings, comments, or help text when they materially improve clarity

### For shell scripts

- Write for `bash`
- Quote variables consistently
- Fail early on invalid input
- Avoid changing install or boot behavior casually
- Test installer, updater, uninstaller, and read-only flows on real hardware when you modify them

### For documentation

- Prefer accuracy over marketing language
- Keep commands copy-pasteable
- Explain when a step is optional, risky, or hardware-specific
- Call out important limitations, especially around power and read-only behavior

## Checks to run before opening a PR

Run the same baseline checks that CI runs:

```bash
python -m compileall src
python -m bluetooth_2_usb --help
python -m bluetooth_2_usb --version
python -m bluetooth_2_usb --validate-env || test $? -eq 3
python -m bluetooth_2_usb --dry-run || test $? -eq 3
bash -n scripts/*.sh scripts/lib/common.sh
```

> [!NOTE]
> Outside a properly configured Raspberry Pi gadget environment, `--validate-env` and `--dry-run` may exit with status `3`. That is expected and should not be treated as a failure in non-hardware CI or local development on a regular Linux workstation.

## Hardware validation

If your change affects runtime behavior, installation, service startup, USB gadget setup, or read-only operation, validate it on a real Pi.

From a repository checkout:

```bash
sudo ./scripts/smoke_test.sh
sudo ./scripts/debug.sh --duration 10 --redact
```

From an installed deployment:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact
```

`debug.sh` temporarily stops the service if it is running, captures a foreground Bluetooth-2-USB `--debug` session, and restores the service afterwards. Omit `--duration` if you want that live debug session to continue until you interrupt it manually.

Please also test against a real OTG target host when the change affects HID behavior or USB compatibility.

Documentation-only changes do not require hardware validation, but commands and paths should still be checked for accuracy.

## Pull request guidelines

When you open a pull request:

- Use a short, clear title
- Explain what changed and why
- Describe how you tested it
- Include the target host type used for validation when it matters
- Link the relevant issue if one exists
- Include redacted logs or debug output when the change affects installation, service behavior, runtime diagnostics, or read-only mode

Good pull requests are usually small enough to review in one pass and specific enough to test without guessing.

## Reporting issues

Please use the GitHub issue tracker and include as much of the following as you can:

- Target host type
- Whether you are using normal, easy, or persistent read-only mode
- Exact commands or scripts used
- Output from `smoke_test.sh --verbose`
- Output from `debug.sh --duration 10 --redact`
- Clear reproduction steps

## Community expectations

Please be respectful, constructive, and patient in all project interactions.

Assume good intent, focus feedback on the technical work, and help keep the project welcoming to people with different levels of experience.

Thanks for helping improve Bluetooth-2-USB.
