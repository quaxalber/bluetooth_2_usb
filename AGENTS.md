# Bluetooth-2-USB Agent Guide

This file contains agent-specific deltas for this repository. Treat
[CONTRIBUTING.md](CONTRIBUTING.md) as the main contributor contract for setup,
checks, hardware validation, and PR workflow.

## Scope

- Repository: `bluetooth_2_usb`
- Primary goal: turn a Raspberry Pi into a USB HID bridge for Bluetooth
  keyboards and mice
- Main risk areas: USB gadget setup, boot config mutation, managed install
  re-apply behavior, systemd service behavior, persistent read-only mode, and
  Pi-side runtime validation

## Read first

Before making changes, read:

1. `README.md`
2. `CONTRIBUTING.md`
3. the relevant code or scripts
4. the focused guide that matches the task, if any

Repo-owned focused guides:

- `TROUBLESHOOTING.md`
- `docs/cli-service-test.md`
- `docs/host-relay-loopback.md`
- `docs/persistent-readonly.md`
- `docs/remote-wakeup-kernel.md`
- `docs/runtime-architecture.md`
- `docs/doc-consistency-review.md`
- `docs/release-versioning-policy.md`

## Agent deltas

- Prefer the repo venv for checks. Do not silently fall back to system Python
  when the venv workflow applies.
- For remote Pi work, passwordless sudo is strongly recommended so `sudo -n`
  validation paths do not fail early.
- Keep changes focused. Update docs when behavior, commands, paths, defaults, or
  validation guidance change.
- Follow the compatibility policy in `CONTRIBUTING.md`.
- Do not push directly to `main`. Use `staging` as the integration branch for
  normal work.
- Open normal PRs against `staging` and squash-merge them there. Small
  follow-up review fixes may be pushed directly to `staging` when that is the
  least disruptive path.
- Promote validated batches from `staging` to `main` with a normal merge
  commit.
- Do not amend commits unless explicitly asked.
- Do not revert user changes you did not make.

## Validation expectations

Use the baseline checks from [CONTRIBUTING.md](CONTRIBUTING.md).

If you change installer, diagnostics, or read-only logic, run the full
operational CLI validation path.

For runtime-affecting changes, validate on real Pi hardware when feasible.
Minimum Pi-side checks:

- `sudo /opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb smoketest --verbose`
- `sudo /opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb debug --duration 10`
- `sudo bluetoothctl show`
- `sudo btmgmt info`

For relay-path changes, also use the host/Pi loopback inject/capture harness from
`docs/host-relay-loopback.md`.

If destructive Pi flows were not executed, say so explicitly in the final
summary.

## Review and CI

- Verify each review point against the current code; do not trust old thread
  state blindly.
- Also verify grouped nitpicks, summary comments, and non-threaded feedback.
- If you intentionally disagree with review feedback, document the reason on the
  PR.
- If CI fails, inspect the actual failing GitHub Actions step and log before
  guessing.

CodeRabbit:

- Follow the canonical CodeRabbit review policy in `CONTRIBUTING.md`.
- Do not duplicate or override that policy here.

## Final response expectations

When reporting work:

- summarize the relevant checks that were actually run; do not feel obligated to
  list every single command when a shorter summary is clearer
- say which checks could not be run and why
- distinguish workstation validation from real Pi validation
- call out residual risk, especially for install, diagnostics, read-only mode,
  and release behavior
