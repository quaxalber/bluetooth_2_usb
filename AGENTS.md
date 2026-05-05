# Bluetooth-2-USB Agent Guide

This file contains agent-specific deltas for this repository. Treat
[CONTRIBUTING.md](CONTRIBUTING.md) as the main contributor contract for setup,
checks, hardware validation, and PR workflow.

## Scope

- Repository: `bluetooth_2_usb`
- Primary goal: turn a Raspberry Pi into a USB HID bridge for Bluetooth
  keyboards and mice
- Main risk areas: USB gadget setup, boot config mutation, managed install
  re-apply behavior, systemd service behavior, read-only mode, and Pi-side
  runtime validation

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

- Follow [CONTRIBUTING.md](CONTRIBUTING.md) for contributor workflow, PR policy,
  review, CI, compatibility, checks, and hardware validation.
- Prefer the repo venv for checks. Do not silently fall back to system Python
  when the venv workflow applies.
- For remote Pi work, passwordless sudo is strongly recommended so `sudo -n`
  validation paths do not fail early.
- Keep changes focused. Update docs when behavior, commands, paths, defaults, or
  validation guidance change.
- Do not amend commits unless explicitly asked.
- Do not revert user changes you did not make.

## Validation expectations

Use the baseline checks and hardware-validation policy from
[CONTRIBUTING.md](CONTRIBUTING.md). Use the focused docs above for full
operational, read-only, remote-wakeup, or loopback validation flows.

## Review and CI

Follow the canonical review and CI policy in [CONTRIBUTING.md](CONTRIBUTING.md).
Do not duplicate or override CodeRabbit workflow rules here.

## Final Response Expectations

Keep final responses concise and decision-useful:

- state what changed and where, in one or two sentences
- report validation by outcome, not command transcript; mention only the checks
  that matter
- clearly name any skipped validation, especially real Pi, live loopback,
  destructive read-only, or release checks
- call out residual risk only when it affects the user's next decision
