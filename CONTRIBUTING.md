# Contributing to Bluetooth 2 USB

This guide assumes you already know the usual GitHub fork/branch/PR workflow and want the project-specific details only.

## Setup

Use Linux. Raspberry Pi hardware is required for meaningful runtime validation.

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

## Expectations

- Keep changes focused. Do not mix installer, runtime and vendored dependency changes without a reason.
- Prefer changes inside `bluetooth_2_usb/`. Touch vendored forks only when you are intentionally syncing or patching upstream behavior.
- Preserve the managed install model:
  - install root: `/opt/bluetooth_2_usb`
  - service: `bluetooth_2_usb.service`
  - config: `/etc/default/bluetooth_2_usb`
- If you change install, update or uninstall behavior, test those scripts on a real Pi.

## Required checks before a PR

Run the same baseline checks locally that CI runs:

```bash
python -m compileall src
python -m bluetooth_2_usb --help
python -m bluetooth_2_usb --version
python -m bluetooth_2_usb --validate-env || true
bash -n scripts/*.sh scripts/lib/common.sh
```

On Raspberry Pi hardware, also run:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact
```

If your change touches HID/runtime behavior, validate against a real OTG host, not just CLI checks.

## Pull requests

- Use a short imperative commit title.
- Explain what changed, how you tested it, and what hardware/host setup you used.
- Link the relevant issue.
- Include redacted logs or debug output when service or install behavior changed.

## Reporting issues

Use the GitHub issue tracker and include:

- Pi model
- Raspberry Pi OS / kernel version
- OTG host type
- exact command or script used
- `smoke_test.sh` result
- `debug.sh --redact` output
