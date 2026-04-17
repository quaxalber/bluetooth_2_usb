# Bluetooth-2-USB Agent Guide

This file is the fast-start contract for work in this repository. A fresh
thread should be able to start from here without guessing project standards.

Treat this file as living project documentation, not as a one-off setup note.
When workflows, validation commands, managed paths, service behavior,
release rules, hardware expectations, or project conventions change, update this
file in the same change to prevent drift.

## Scope

- Repository: `bluetooth_2_usb`
- Primary goal: turn a Raspberry Pi into a USB HID bridge for Bluetooth
  keyboards and mice
- Main risk areas: USB gadget setup, boot config mutation, managed install
  re-apply behavior, systemd service behavior, persistent read-only mode, and
  Pi-specific runtime validation

## First steps

Before making changes, read:

1. `README.md`
2. `CONTRIBUTING.md`
3. relevant files under `docs/`
4. the code or scripts you plan to modify

Use these repo-specific playbooks when they match the task:

- `docs/pi-cli-service-test-playbook.md`
- `docs/pi-host-relay-loopback-test-playbook.md`
- `docs/pi-manual-test-plan.md`
- `docs/doc-consistency-review-playbook.md`
- `docs/release-versioning-policy.md`

## Environment

Use the repository virtual environment for repo-local checks. Do not silently
fall back to system Python for validation when the venv workflow applies.

Setup:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -U pip setuptools wheel
pip install -e . black ruff yamllint shfmt-py shellcheck-py build
```

Important:

- `black`, `ruff`, `yamllint`, `shfmt`, and `shellcheck` are expected to be run
  from this venv.
- If a fresh shell cannot find `shfmt` or `shellcheck`, activate the venv first.
- For one-off commands in automation, prefer `source venv/bin/activate && ...`
  or `venv/bin/<tool>`.
- For remote Pi work, passwordless sudo is strongly recommended so SSH-driven
  validation and agentic workflows can use `sudo -n ...` safely.

## Repository layout

Files and directories that matter most:

- `src/bluetooth_2_usb/`
  Python package for CLI, runtime, HID layout, relay logic, logging, and
  version handling
- `scripts/`
  Managed install, uninstall, smoke/debug, and persistent read-only helpers
- `scripts/lib/paths.sh`
  Shared managed-path and service constants
- `scripts/lib/common.sh`
  Generic shell helpers only
- `scripts/lib/boot.sh`
  Raspberry Pi boot and `dwc2` helpers
- `scripts/lib/install.sh`
  Managed install, service, and virtualenv helpers
- `scripts/lib/readonly.sh`
  Persistent read-only and Bluetooth-state mount helpers
- `scripts/lib/report.sh`
  Markdown/report-only shell helpers
- `bluetooth_2_usb.service`
  Installed systemd unit template
- `pyproject.toml`
  Packaging, entrypoints, versioning, formatter/linter config
- `README.md`
  User-facing operational documentation
- `CONTRIBUTING.md`
  Contributor workflow and baseline checks

Managed deployment paths:

- install root: `/opt/bluetooth_2_usb`
- managed venv: `/opt/bluetooth_2_usb/venv`
- service unit: `bluetooth_2_usb.service`
- runtime env file: `/etc/default/bluetooth_2_usb`
- read-only env file: `/etc/default/bluetooth_2_usb_readonly`
- log dir: `/var/log/bluetooth_2_usb`
- persistent mount: `/mnt/b2u-persist`

## Current contracts

Preserve these unless the task explicitly redesigns them:

- Managed installs are rooted in `/opt/bluetooth_2_usb`.
- The service launches the module with the managed venv Python.
- The service loads `/etc/default/bluetooth_2_usb` as structured `B2U_*`
  configuration and starts `python -m bluetooth_2_usb.service_runner`.
- Supported install flow:
  - on minimal Raspberry Pi OS Lite images, install `git` first if needed:
    `sudo apt update && sudo apt install -y git`
  - clone to `/opt/bluetooth_2_usb`
  - run `sudo /opt/bluetooth_2_usb/scripts/install.sh`
- Supported update flow:
  - `sudo /opt/bluetooth_2_usb/scripts/update.sh`
  - when the checkout is already current, `update.sh` must exit successfully
    without rebuilding the managed venv or restarting the service
- Shell scripts should fail loudly on ambiguous or unsafe input.
- Boot changes should be conservative and leave timestamped backups.
- `scripts/optimize_pi_boot.sh` is the exception that may perform automatic
  rollback restores, but only for the host state it captured itself in
  `${B2U_OPTIMIZE_STATE_FILE}`.
- Read-only operation is either:
  - normal writable mode
  - persistent read-only mode with writable Bluetooth state on ext4 storage

## Editing standards

### Python

- Python 3.11+
- Format with Black, line length 88
- Lint with Ruff
- Prefer clear, direct control flow over cleverness
- Keep CLI/help text and exit-code behavior stable unless intentionally changed

### Shell

- Target `bash`
- Quote variables consistently
- Use shared helpers from `scripts/lib/common.sh` only when they are genuinely
  generic and reused
- Keep managed paths and service constants out of `common.sh`; they belong in a
  dedicated path/config layer
- Move boot/install/read-only workflow logic into dedicated shell libs rather
  than growing `common.sh`
- Put report-only helpers in `scripts/lib/report.sh`, not in `common.sh`
- Avoid masking failures with `|| true` unless they are truly non-fatal
- Treat install/uninstall/read-only flows as production code

### Documentation

- Prefer operational accuracy over marketing language
- Keep commands copy-pasteable
- Parameterize examples unless a fixed value is intentionally required
- Keep docs aligned with real script interfaces, defaults, and managed paths

## Validation

Run the baseline checks from the repo venv:

```bash
black --check src tests
ruff check src tests
python -m compileall src tests
python -m unittest discover -s tests -v
python -m bluetooth_2_usb --help
python -m bluetooth_2_usb --version
python -m bluetooth_2_usb --validate-env || test $? -eq 3
shfmt -d -i 2 -ci -bn scripts/*.sh scripts/lib/*.sh
shellcheck -x scripts/*.sh scripts/lib/*.sh
bash -n scripts/*.sh scripts/lib/*.sh
yamllint .github/workflows/ci.yml
python -m build
```

Interpretation note:

- Outside a real Pi gadget environment, `--validate-env` may exit with status
  `3`. That is expected on a normal workstation and should not be treated as a
  failure by itself.

If you change installer/uninstaller/read-only logic, shell validation is
mandatory.

## Hardware validation

For Pi-side validation, use a reachable Raspberry Pi over SSH when the task
affects runtime or managed deployment behavior.

Use `docs/pi-cli-service-test-playbook.md` for repeatable Pi-side validation.

For runtime-affecting changes, validate on real hardware when feasible:

- `sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh`
- `sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10`
- `python -m bluetooth_2_usb --list_devices --output json`
- the host/Pi loopback harness from
  `docs/pi-host-relay-loopback-test-playbook.md` when the relay path itself
  changed
- for host-side loopback capture, the host Python environment needs `hidapi`
  for gadget discovery; on Windows the strict event-capture backend is Raw
  Input for keyboard, mouse, consumer, and combo scenarios
- do not assume the full repo venv is available or desirable on macOS/Windows
- on Linux hosts, the `hidapi` path also needs the USB-device udev rule from
  `scripts/install_host_hidapi_udev_rule.sh`
- host capture can temporarily claim the gadget HID interfaces while the test
  runs; do not assume normal local desktop handling remains active during the
  capture window
- before each new Windows validation run for a changed gadget descriptor
  layout or USB identity:
  1. set the Pi to the intended software revision
  2. reboot the Pi
  3. ask the user for a Windows PnP admin reset
  4. wait for explicit confirmation before starting host capture
- the loopback harness uses a single lock file and does not support parallel
  inject/capture runs
- if a harness run looks wedged, check stale lock files on both sides:
  `%TEMP%/bluetooth_2_usb_test_harness.lock` on the host and
  `/tmp/bluetooth_2_usb_test_harness.lock` on the Pi

For Bluetooth-adapter or pairing issues, do not stop at
`systemctl status bluetooth`. Also check the real controller and rfkill state:

- `sudo bluetoothctl show`
- `sudo btmgmt info`
- `/sys/class/rfkill/rfkill*/soft`, `hard`, and `state`

Treat `bluetooth.service active` as necessary but not sufficient. A live BlueZ
service can still leave the controller `Powered: no`, `PowerState:
off-blocked`, or `DOWN` because of a persisted software rfkill block.

When validating flaky BLE pairings on the Pi:

- prefer a live `bluetoothctl` session over one-shot commands
- watch for `[agent] Accept pairing (yes/no):` and answer it explicitly
- distinguish short transient connects from a real bonded state; repeated
  `Connected: yes` / `Connected: no` cycles with `Paired: no` mean the bonding
  handshake is still failing

If destructive Pi flows were not executed, say so explicitly in the final
summary.

## Review and CI

- When addressing PR feedback, verify each comment against current code; do not
  assume a resolved thread is still satisfied after later commits.
- Also verify grouped nitpicks, summary comments, and other non-threaded review
  notes against the current code before deciding they are irrelevant.
- If you intentionally disagree with review feedback, document the technical
  reason directly on the PR at the relevant thread or comment location.
- For CodeRabbit specifically, treat the first top-level CodeRabbit comment on
  the PR as the live review-status source of truth. That comment is updated in
  place and may show states such as review in progress, paused, or rate limit
  exceeded.
- Do not treat a CodeRabbit review as complete after the latest commit until
  that first top-level CodeRabbit comment explicitly says no actionable comments
  were generated for the recent review.
- If that first CodeRabbit comment shows a rate-limit state, wait for the
  window to expire before retriggering review, and avoid claiming the PR is
  fully reviewed in the meantime.
- Findings should focus on behavioral regressions, release risk, shell/runtime
  contract drift, and maintainability with operational impact.
- If CI fails, inspect the actual failing GitHub Actions step and log before
  guessing.
- CodeRabbit comments are useful hints, not ground truth.

## Git and change scope

- Keep changes focused.
- Update docs when behavior, commands, paths, defaults, or validation guidance
  change.
- Do not push directly to `main`; do the work on a branch and merge through a
  pull request.
- Do not amend commits unless explicitly asked.
- Do not revert user changes you did not make.

## Final response expectations

When reporting work:

- say which checks were actually run
- say which checks could not be run and why
- distinguish workstation validation from real Pi validation
- call out any residual risk, especially for install/read-only/release behavior
