# Bluetooth-2-USB Agent Guide

This file is the fast-start contract for work in this repository. A fresh thread
should be able to start from here without guessing project standards.

## Scope

- Repository: `bluetooth_2_usb`
- Primary goal: turn a Raspberry Pi into a USB HID bridge for Bluetooth keyboards
  and mice
- Main risk areas: USB gadget setup, boot config mutation, managed install/update
  flows, systemd service behavior, read-only OverlayFS modes, and Pi-specific
  runtime validation

## First Steps

Before making changes, read the local context that defines current behavior:

1. `README.md`
2. `CONTRIBUTING.md`
3. Relevant files under `docs/` for the task
4. The code or scripts you plan to modify

When the task matches one of these playbooks, use it:

- `docs/pi-cli-service-test-playbook.md`
  Agentic Pi-side validation of install/update/service/script flows
- `docs/pi-manual-test-plan.md`
  Manual hardware follow-up checks
- `docs/doc-consistency-review-playbook.md`
  Documentation consistency review
- `docs/release-versioning-policy.md`
  Versioning and release rules

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

## Repository Layout

Files and directories that matter most:

- `src/bluetooth_2_usb/`
  Python package for CLI, runtime, HID profiles, relay logic, logging, and
  version handling
- `scripts/`
  Managed install/update/uninstall flows, smoke/debug helpers, readonly helpers,
  persistent Bluetooth-state setup
- `scripts/lib/common.sh`
  Shared shell helpers and managed deployment conventions
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

- Install root: `/opt/bluetooth_2_usb`
- Managed venv: `/opt/bluetooth_2_usb/venv`
- Service unit: `bluetooth_2_usb.service`
- Runtime env file: `/etc/default/bluetooth_2_usb`
- Read-only env file: `/etc/default/bluetooth_2_usb_readonly`
- State dir: `/var/lib/bluetooth_2_usb`
- Managed source tracking: `/var/lib/bluetooth_2_usb/managed_source.env`

## Current Contracts

Preserve these unless the task explicitly redesigns them:

- Managed installs are rooted in `/opt/bluetooth_2_usb`.
- The service launches the module with the managed venv Python.
- Install/update flows must be safe for non-interactive use.
- Shell scripts should be idempotent where practical and should fail loudly on
  ambiguous or unsafe input.
- Release tracking is explicit:
  - branch installs stay on that branch
  - exact tag installs stay pinned
  - `--latest-release` / bootstrap default track the latest published release
- Boot mutation and rollback must be conservative and reversible.
- Read-only mode behavior must stay consistent across scripts, service behavior,
  documentation, and smoke/debug output.

## Editing Standards

### Python

- Python 3.11+
- Format with Black, line length 88
- Lint with Ruff
- Prefer clear, direct control flow over cleverness
- Keep CLI/help text and exit-code behavior stable unless intentionally changed
- Update docstrings/comments/help when behavior meaningfully changes

### Shell

- Target `bash`
- Quote variables consistently
- Use shared helpers from `scripts/lib/common.sh` only when they are truly
  generic and reused
- Put report/Markdown-specific helpers in `scripts/lib/report.sh`, not in
  `common.sh`
- Avoid masking failures with `|| true` unless the failure is truly non-fatal
  and documented
- Treat install/update/uninstall/readonly scripts as production code, not local
  glue

### Documentation

- Prefer operational accuracy over marketing language
- Keep commands copy-pasteable
- Parameterize examples when they are not intentionally repo- or environment-
  specific
- Call out dangerous steps explicitly, especially formatting, boot changes,
  uninstall/purge flows, and power-loss/read-only caveats
- Keep docs aligned with real script interfaces, defaults, and service behavior

## Validation

Run the baseline checks from the repo venv:

```bash
black --check src
ruff check src
python -m compileall src
python -m bluetooth_2_usb --help
python -m bluetooth_2_usb --version
python -m bluetooth_2_usb --validate-env || test $? -eq 3
python -m bluetooth_2_usb --dry-run || test $? -eq 3
shfmt -d -i 2 -ci -bn scripts/*.sh scripts/lib/common.sh scripts/lib/report.sh
shellcheck -x scripts/*.sh scripts/lib/common.sh scripts/lib/report.sh
bash -n scripts/*.sh scripts/lib/common.sh scripts/lib/report.sh
yamllint .github/workflows/ci.yml
python -m build
```

Interpretation note:

- Outside a real Pi gadget environment, `--validate-env` and `--dry-run` may
  exit with status `3`. That is expected on a normal workstation and should not
  be treated as a failure by itself.

If you change installer/update/uninstall/read-only logic, shell validation is
mandatory.

If you change packaging, entrypoints, versioning, or service wiring, run
`python -m build` and the CLI checks.

## Hardware Validation

For Pi-side validation, a local Pi with hostname `pi4b` should normally be
reachable over SSH and should be used when the task affects runtime or managed
deployment behavior.

Important caveat:

- `pi4b` is not always stable.
- If `pi4b` is unreachable, treat that first as an environment issue that may
  require a manual reboot by the user, not as an automatic project failure.

Use `docs/pi-cli-service-test-playbook.md` for repeatable Pi-side validation.

For runtime-affecting changes, validate on real hardware when feasible:

- `sudo ./scripts/smoke_test.sh`
- `sudo ./scripts/debug.sh --duration 10 --redact`
- installed-path equivalents under `/opt/bluetooth_2_usb/scripts/`

If destructive Pi flows were not executed, say so explicitly in the final
summary.

## Review and CI

- When addressing PR feedback, verify each comment against current code; do not
  assume a resolved thread is still satisfied after later commits.
- Findings should focus on behavioral regressions, release risk, shell/runtime
  contract drift, and maintainability with operational impact.
- If CI fails, inspect the actual failing GitHub Actions step and log before
  guessing.
- CodeRabbit comments are useful hints, not ground truth.

## Git and Change Scope

- Keep changes focused.
- Update docs when behavior, commands, paths, defaults, or validation guidance
  change.
- Do not amend commits unless explicitly asked.
- Do not revert user changes you did not make.
- Avoid touching unrelated repos or vendored code from this workspace.

## Final Response Expectations

When reporting work:

- Say which checks were actually run.
- Say which checks could not be run and why.
- Distinguish workstation validation from real Pi validation.
- Call out any residual risk, especially for install/update/readonly/release
  behavior.
