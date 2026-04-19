# Contributing to Bluetooth-2-USB

This document is the main contributor contract for this repository.

## Development environment

Meaningful runtime validation requires Linux, and changes that affect USB
gadget behavior should be tested on a real Raspberry Pi with an OTG-capable
connection to a target host.

Basic setup:

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

Use this venv for repo-local validation.

## Repository shape

The supported product surface is intentionally small:

- `scripts/install.sh`, `scripts/update.sh`, `scripts/uninstall.sh`
- `scripts/smoke.sh`, `scripts/debug.sh`
- `scripts/inject.sh`
- `scripts/capture.{sh,ps1}`
- `scripts/install-hid-udev-rule.sh`
- `scripts/readonly-setup.sh`
- `scripts/readonly-enable.sh`
- `scripts/readonly-disable.sh`
- `README.md`
- `TROUBLESHOOTING.md`
- `docs/cli-service-test.md`
- `docs/host-relay-loopback.md`
- `docs/persistent-readonly.md`
- `docs/remote-wakeup-kernel.md`
- `docs/doc-consistency-review.md`
- `docs/release-versioning-policy.md`

Keep code and docs aligned with the supported deployment model:

- install root: `/opt/bluetooth_2_usb`
- service unit: `bluetooth_2_usb.service`
- runtime config: `/etc/default/bluetooth_2_usb`

## Quality expectations

### Python

- Python 3.11+
- format with Black
- lint with Ruff
- prefer small, direct control flow over clever abstractions
- keep CLI behavior and help text stable unless intentionally changed

### Shell

- write for `bash`
- quote variables consistently
- fail early on invalid input
- keep shared helpers in `scripts/lib/common.sh` genuinely generic
- keep managed paths and service constants out of `common.sh`
- keep workflow-specific logic in dedicated shell libs
- treat install, diagnostics, and read-only flows as production code

### Documentation

- prefer operational accuracy over marketing language
- prefer readable examples over shell-heavy indirection
- keep docs aligned with current script interfaces and managed paths
- avoid documenting lab-specific host policy as product behavior

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

Outside a real Pi gadget environment, `--validate-env` may exit with status `3`.

## Hardware validation

If your change affects runtime behavior, installation, service startup, USB
gadget setup, diagnostics, relay behavior, or persistent read-only operation,
validate it on a real Pi.

Use these repo-owned guides when they match the task:

- [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- [docs/cli-service-test.md](docs/cli-service-test.md)
- [docs/host-relay-loopback.md](docs/host-relay-loopback.md)
- [docs/persistent-readonly.md](docs/persistent-readonly.md)
- [docs/remote-wakeup-kernel.md](docs/remote-wakeup-kernel.md)

Minimum Pi-side validation after runtime-affecting changes:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
sudo bluetoothctl show
sudo btmgmt info
```

For relay-path changes, also use the host/Pi loopback harness.

## Pull request guidelines

This repository uses `staging` as its integration branch.

- keep scope focused
- prefer one logical feature, fix, refactor, or documentation change per PR
- explain what changed and why
- describe how you tested it
- update docs when behavior, commands, paths, or defaults change
- target `staging` for normal work
- do not target `main` directly for normal project work

Merge policy:

- squash-merge normal PRs into `staging`
- validate the integrated `staging` result before promotion
- merge `staging` into `main` with a normal merge commit

Branch and commit naming:

- use descriptive branch prefixes such as `feat/`, `fix/`, `docs/`, `refactor/`,
  `test/`, `chore/`
- use matching conventional commit prefixes such as `feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, `chore:`
- do not push directly to `main`
- do not use `codex/...` branch prefixes for normal project work

## Review and CI

- verify review feedback against the current code, not just the historic thread
  state
- also check grouped nitpicks and summary comments
- if you intentionally decline a review suggestion, explain that on the PR
- if CI fails, inspect the actual failing step and log before guessing

CodeRabbit policy:

- `.coderabbit.yaml` enables automatic review on new pushes and includes
  `staging`
- treat the first top-level CodeRabbit PR comment as the live status source of
  truth
- do not consider review complete until that comment says
  `no actionable comments` after the latest commit
- do not use a green `CodeRabbit` check alone as proof that review is finished
- if the first CodeRabbit comment says `review in progress`, `paused`, or
  `rate limited`, wait or resume before posting `@coderabbitai review`

## Reporting issues

Please include:

- target host type
- whether persistent read-only mode is enabled
- exact commands or scripts used
- output from `smoke.sh --verbose`
- output from `debug.sh --duration 10`
- clear reproduction steps

## Community expectations

Be respectful, constructive, and patient in project interactions.
