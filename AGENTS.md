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
- `docs/doc-consistency-review.md`
- `docs/release-versioning-policy.md`

## Agent deltas

- Prefer the repo venv for checks. Do not silently fall back to system Python
  when the venv workflow applies.
- For remote Pi work, passwordless sudo is strongly recommended so `sudo -n`
  validation paths do not fail early.
- Keep changes focused. Update docs when behavior, commands, paths, defaults, or
  validation guidance change.
- Do not push directly to `main`. Use `staging` as the integration branch for
  normal work.
- Open normal PRs against `staging`, squash-merge them there, and promote
  validated batches from `staging` to `main` with a normal merge commit.
- Do not amend commits unless explicitly asked.
- Do not revert user changes you did not make.

## Validation expectations

Use the baseline checks from [CONTRIBUTING.md](CONTRIBUTING.md).

If you change installer, diagnostics, or read-only logic, recursive shell
validation is mandatory.

For runtime-affecting changes, validate on real Pi hardware when feasible.
Minimum Pi-side checks:

- `sudo /opt/bluetooth_2_usb/scripts/smoketest.sh --verbose`
- `sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10`
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

- Treat the first top-level CodeRabbit PR comment as the authoritative live
  state.
- Do not consider CodeRabbit complete until that comment says
  `no actionable comments` after the latest commit.
- Before manually pinging CodeRabbit, inspect both that first comment and the
  `CodeRabbit` GitHub check on the PR head commit.
- If the first comment shows `review in progress`, `paused`, or `rate limited`,
  wait, resume, or re-trigger only when that state justifies it.

## Final response expectations

When reporting work:

- summarize the relevant checks that were actually run; do not feel obligated to
  list every single command when a shorter summary is clearer
- say which checks could not be run and why
- distinguish workstation validation from real Pi validation
- call out residual risk, especially for install, diagnostics, read-only mode,
  and release behavior
