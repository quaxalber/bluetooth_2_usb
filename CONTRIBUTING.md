# Contributing to Bluetooth-2-USB

Thanks for your interest in contributing.

This guide covers the repo-specific workflow that keeps changes easy to review,
validate, and maintain.

## Development environment

Meaningful runtime validation requires Linux, and changes that affect USB
gadget behavior should be tested on a real Raspberry Pi with an OTG-capable
connection to a target host.

Basic setup:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv

git clone https://github.com/quaxalber/bluetooth_2_usb.git
cd bluetooth_2_usb

python3 -m venv venv
source venv/bin/activate
pip install -U pip setuptools wheel
pip install -e . black ruff yamllint shfmt-py shellcheck-py build
```

If you prefer to work from a fork, replace the clone URL with your fork.

Use this venv for repo-local validation.

## Supported deployment model

Please keep code and docs aligned with the supported deployment model:

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
sudo /opt/bluetooth_2_usb/scripts/smoketest.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
sudo bluetoothctl show
sudo btmgmt info
```

For relay-path changes, also use the host/Pi loopback inject/capture harness in
[docs/host-relay-loopback.md](docs/host-relay-loopback.md).

During fast iteration, maintainers may temporarily copy a working tree to a Pi
with `rsync`. Treat that copy as provisional until the managed install has been
rebuilt from the copied tree:

```bash
rsync -a --delete --exclude .git --exclude venv ./ <pi-host>:/tmp/bluetooth_2_usb/
ssh <pi-host> '
  sudo -n rsync -a --delete /tmp/bluetooth_2_usb/ /opt/bluetooth_2_usb/ &&
  sudo -n /opt/bluetooth_2_usb/scripts/install.sh &&
  /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --version
'
```

If the work is already pushed, prefer installing from the exact commit and
verifying the checkout SHA:

```bash
git rev-parse HEAD
ssh <pi-host> '
  sudo -n git -C /opt/bluetooth_2_usb fetch origin <branch-name> &&
  sudo -n git -C /opt/bluetooth_2_usb checkout <commit-sha> &&
  sudo -n /opt/bluetooth_2_usb/scripts/install.sh &&
  git -C /opt/bluetooth_2_usb rev-parse HEAD
'
```

For PR validation, also push the branch before reporting results so reviewers can
inspect the exact code. Results from an rsynced tree that has not been installed
with `install.sh` are useful debugging data, not final validation evidence.

## Pull request guidelines

This repository uses `staging` as its integration branch.

- keep scope focused
- prefer one logical feature, fix, refactor, or documentation change per PR
- explain what changed and why
- describe how you tested it
- update docs when behavior, commands, paths, or defaults change
- target `staging` for normal work
- use a normal PR into `staging` for features, fixes, refactors, and other
  non-trivial changes
- small follow-up review fixes may be pushed directly to `staging` when that is
  the least disruptive way to finish an in-flight review
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

## Review and CI

- verify review feedback against the current code, not just the historic thread
  state
- also check grouped nitpicks and summary comments
- if you intentionally decline a review suggestion, explain that on the PR
- if CI fails, inspect the actual failing step and log before guessing

CodeRabbit policy:

- `.coderabbit.yaml` disables automatic review; request CodeRabbit manually when
  needed, using `@coderabbitai full review` by default
- treat the first top-level CodeRabbit PR comment as the live status source of
  truth
- do not consider review complete until that comment says
  `no actionable comments` after the latest commit
- do not use a green `CodeRabbit` check alone as proof that review is finished
- for the actual findings, inspect the newest review comments and read the
  section `Prompt for all review comments with AI agents`
- treat that prompt section as the source of truth for actionable review
  findings, including nitpicks, outside-diff-range comments, summary comments,
  and other grouped review items
- if the first CodeRabbit comment says `review in progress`, wait for completion
- if it says `paused`, resume the review first (for example, click Resume or
  post `@coderabbitai resume`) before posting `@coderabbitai full review`
- if it says `rate limited`, wait and retry `@coderabbitai full review`

## Reporting issues

Thanks for taking the time to report a problem. If you can, please include:

- target host type
- whether persistent read-only mode is enabled
- exact commands or scripts used
- output from `smoketest.sh --verbose`
- output from `debug.sh --duration 10`
- clear reproduction steps

## Community expectations

Thanks for helping keep the project respectful, constructive, and patient for
everyone involved.
