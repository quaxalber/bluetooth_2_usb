# Contributing to Bluetooth-2-USB

Thanks for your interest in contributing.

This guide focuses on the repo-specific workflow needed to make changes that are
easy to review and validate.

## Development environment

Meaningful runtime validation requires Linux, and changes that affect USB gadget
behavior should be tested on a real Raspberry Pi with an OTG-capable connection
to a target host.

### Basic setup

```bash
sudo apt update
sudo apt install -y git python3 python3-venv

git clone https://github.com/YOUR-ACCOUNT/bluetooth_2_usb.git
cd bluetooth_2_usb

python3 -m venv venv
source venv/bin/activate
pip install -U pip setuptools wheel
pip install -e . black ruff yamllint shfmt-py shellcheck-py build
```

Use this venv for repo-local validation. Do not silently fall back to system
Python when the venv workflow applies.

## Project layout

The files most contributors will touch are:

- `src/bluetooth_2_usb/`
  Python package for the CLI, runtime logic, argument parsing, logging, and
  relay behavior
- `scripts/`
  Install, uninstall, smoke-test, debug, and persistent read-only helper scripts
- `bluetooth_2_usb.service`
  systemd unit template used by the installer
- `.github/workflows/ci.yml`
  Baseline CI checks run on pull requests and on pushes to `staging` and `main`

## Managed deployment model

The supported deployment model is intentionally narrow:

- install root: `/opt/bluetooth_2_usb`
- service unit: `bluetooth_2_usb.service`
- runtime config: `/etc/default/bluetooth_2_usb`

The operational install flow is:

```bash
sudo apt update
sudo apt install -y git
sudo git clone https://github.com/quaxalber/bluetooth_2_usb.git /opt/bluetooth_2_usb
sudo /opt/bluetooth_2_usb/scripts/install.sh
```

The operational update flow is:

```bash
sudo /opt/bluetooth_2_usb/scripts/update.sh
```

If the checkout is already current, `update.sh` should complete successfully
without triggering a reinstall.

Keep code and docs aligned with that model.

## Quality expectations

### Python

- Python 3.11+
- Format with Black
- Lint with Ruff
- Prefer small, direct control flow over clever abstractions
- Keep CLI behavior and help text stable unless intentionally changed

### Shell

- Write for `bash`
- Quote variables consistently
- Fail early on invalid input
- Keep shared helpers in `scripts/lib/common.sh` genuinely generic
- Keep managed paths and service constants out of `common.sh`
- Move boot/install/read-only workflow helpers into dedicated shell libs instead
  of expanding `common.sh`
- Keep report-only helpers in `scripts/lib/report.sh`
- Treat install and readonly flows as production code, not convenience glue

### Documentation

- Prefer operational accuracy over marketing language
- Prefer simple example values or clearly marked placeholders over shell-heavy
  indirection when that makes docs easier to read
- Parameterize examples unless a fixed value is intentionally required
- Keep docs aligned with current script interfaces and managed paths

## Baseline local checks

Run these from the repo venv:

```bash
black --check src tests
ruff check src tests
python -m compileall src tests
python -m unittest discover -s tests -v
python -m bluetooth_2_usb --help
python -m bluetooth_2_usb --version
python -m bluetooth_2_usb --validate-env || test $? -eq 3
mapfile -d '' shell_scripts < <(find scripts -type f -name '*.sh' -print0 | sort -z)
shfmt -d -i 2 -ci -bn "${shell_scripts[@]}"
shellcheck -x "${shell_scripts[@]}"
bash -n "${shell_scripts[@]}"
yamllint .github/workflows/ci.yml
python -m build
```

> [!NOTE]
> Outside a properly configured Raspberry Pi gadget environment,
> `--validate-env` may exit with status `3`. That is expected on a normal
> workstation and should not be treated as a failure by itself.

## Hardware validation

If your change affects runtime behavior, installation, service startup, USB
gadget setup, or persistent read-only operation, validate it on a real Pi.

From an installed deployment:

```bash
sudo /opt/bluetooth_2_usb/scripts/diagnostics/smoke_test.sh
sudo /opt/bluetooth_2_usb/scripts/diagnostics/debug.sh --duration 10
sudo bluetoothctl show
sudo btmgmt info
```

For Pi-side validation, use a reachable Raspberry Pi over SSH when feasible.

Use these repo-specific guides when they match the task:

- `TROUBLESHOOTING.md`
- `docs/pi/cli-service-test.md`
- `docs/pi/boot-optimization.md`
- `docs/pi/connectivity-troubleshooting.md`
- `docs/pi/connectivity-recovery.md`
- `docs/pi/host-relay-loopback.md`
- `docs/pi/manual-test-plan.md`
- `docs/pi/persistent-readonly.md`
- `docs/pi/remote-wakeup-kernel.md`
- `docs/process/doc-consistency-review.md`
- `docs/process/release-versioning-policy.md`

For relay-path changes, prefer running the host/Pi loopback harness in addition
to the standard smoke/debug checks. It validates that the host-visible gadget
HID device actually receives the relayed keyboard, mouse, or consumer reports.
On Linux hosts, the `hidapi` capture path also needs the host-side USB udev
rule and may temporarily claim the gadget HID interfaces while the capture is
running.

## Pull request guidelines

This repository uses `staging` as its integration branch.

When you open a pull request:

- keep the scope focused
- prefer one logical feature, fix, or documentation change per PR when the work
  can be separated cleanly
- explain what changed and why
- describe how you tested it
- include the target host type used for validation when it matters
- update docs when behavior, commands, paths, or defaults change
- target `staging` for normal feature, fix, refactor, test, and documentation
  PRs
- do not target `main` directly for normal project work

Merge policy:

- merge normal PRs into `staging` with squash merge
- validate the integrated `staging` result before promoting it
- merge `staging` into `main` with a normal merge commit so the tested batch is
  preserved as one promotion step
- use direct `main` PRs only for explicit exceptions such as user-requested
  release or hotfix flows

Use branch names that describe the change and start with the change type, for
example:

- `feat/...`
- `fix/...`
- `docs/...`
- `refactor/...`
- `test/...`
- `chore/...`

Do not push directly to `main`. Create a branch for the change and merge it
through a pull request.

Do not use `codex/...` branch prefixes for normal project work.

Start commit subjects with the same conventional type prefixes:

- `feat:`
- `fix:`
- `docs:`
- `refactor:`
- `test:`
- `chore:`

If you address review feedback, verify each point against the current code.
Do not assume an old resolved thread is still satisfied after later commits.
Also check grouped nitpicks and summary comments, not just unresolved inline
threads. If you intentionally decline a review suggestion, explain that
decision directly on the PR at the relevant thread or comment.
For CodeRabbit, use the first top-level CodeRabbit comment on the PR as the
live status indicator because CodeRabbit edits that comment in place. States
such as review in progress, paused, and rate limit exceeded mean the latest
review cycle is not finished yet. Only treat the latest CodeRabbit pass as
complete when that first comment says no actionable comments were generated for
the recent review.

CodeRabbit workflow:

- `.coderabbit.yaml` enables automatic review on new pushes and explicitly
  includes `staging` in `reviews.auto_review.base_branches`
- before manually triggering CodeRabbit, check the first top-level CodeRabbit
  comment on the PR and the `CodeRabbit` GitHub check on the PR head commit
- treat the first top-level CodeRabbit comment as the authoritative live status
  for `review in progress`, `paused`, `rate limited`, and `no actionable
  comments`
- do not treat a green `CodeRabbit` check by itself as proof that review is
  complete; the first CodeRabbit comment must explicitly show `no actionable
  comments` after the latest commit
- if the first CodeRabbit comment shows `review in progress`, `paused`, or
  `rate limited`, do not spam `@coderabbitai review`; wait, resume, or
  re-trigger only once the state justifies it

## Reporting issues

Please include as much of the following as you can:

- target host type
- whether persistent read-only mode is enabled
- exact commands or scripts used
- output from `smoke_test.sh --verbose`
- output from `debug.sh --duration 10`
- clear reproduction steps

## Community expectations

Please be respectful, constructive, and patient in all project interactions.

Assume good intent, focus feedback on the technical work, and help keep the
project welcoming to people with different levels of experience.
