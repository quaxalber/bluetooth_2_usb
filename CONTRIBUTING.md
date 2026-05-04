# Contributing to Bluetooth-2-USB

Thanks for your interest in contributing.

This guide covers the repo-specific workflow that keeps issues actionable,
changes easy to review, and validation grounded.

## Reporting Issues

Thanks for taking the time to report a problem. If you can, please include:

- target host type
- output from `bluetooth_2_usb smoketest --verbose`
- output from `bluetooth_2_usb debug --duration 10`
- clear reproduction steps

If the problem involves pairing, relay behavior, suspend/wake, service startup,
or persistent read-only mode, also mention what changed recently and whether the
Pi is connected to the target host through the OTG-capable data port.

## Pull Requests

This repository uses `staging` as its integration branch.

> [!IMPORTANT]
> Normal project work targets `staging`, not `main`.

Please:

- keep scope focused
- prefer one logical feature, fix, refactor, or documentation change per PR
- explain what changed and why
- describe how you tested it
- update docs when behavior, commands, paths, or defaults change

Use a normal PR into `staging` for features, fixes, refactors, and other
non-trivial changes.

Branch and commit naming:

> [!IMPORTANT]
> Do not use agent- or tool-branded names such as `codex/...` branch prefixes
> or `[codex] ...` PR titles. Prefer the change type and intent, for example
> `refactor/simplify-v3-cleanup` and
> `refactor: simplify v3 cleanup paths`.

- use descriptive branch prefixes such as `feat/`, `fix/`, `docs/`, `refactor/`,
  `test/`, `chore/`
- use matching conventional commit prefixes such as `feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, `chore:`
- do not push directly to `main`

Merge policy:

- squash-merge normal PRs into `staging`
- validate the integrated `staging` result before promotion
- merge `staging` into `main` with a normal merge commit

## Review and CI

- verify review feedback against the current code, not just the historic thread
  state
- also check grouped nitpicks and summary comments
- if you intentionally decline a review suggestion, explain that on the PR
- if CI fails, inspect the actual failing step and log before guessing

## Development Environment

> [!NOTE]
> Meaningful runtime validation requires Linux, and changes that affect USB
> gadget behavior should be tested on a real Raspberry Pi with an OTG-capable
> connection to a target host.

Basic setup:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv

git clone https://github.com/quaxalber/bluetooth_2_usb.git
cd bluetooth_2_usb

python3 -m venv venv
source venv/bin/activate
pip install -U pip setuptools wheel
pip install -e . black ruff yamllint build
```

If you prefer to work from a fork, replace the clone URL with your fork.

Use this venv for repo-local validation.

## Quality Expectations

### Python

- Python 3.11+
- format Python with Black at the repository line length (`120`)
- lint with Ruff
- use positional formatting for logger calls so disabled log levels avoid
  formatting work and log aggregators can group stable message templates
- prefer small, direct control flow over clever abstractions
- keep CLI behavior and help text stable unless intentionally changed

### Operational Commands

- keep install, diagnostics, read-only, managed path, and loopback logic in
  Python under `bluetooth_2_usb.ops`
- expose operator workflows through Python CLIs, not shell wrappers
- fail early on invalid input
- keep CLI behavior and help text stable unless intentionally changed

### Compatibility Policy

> [!IMPORTANT]
> Keep docs, tests, and code aligned with the current supported product surface.
> Do not keep legacy aliases, shell wrappers, removed config keys, deprecated
> entrypoints, or compatibility shims.

- when an interface changes, update callers and docs to the new interface
  directly instead of preserving old paths

### Documentation

- prefer operational accuracy over marketing language
- prefer readable examples over shell-heavy indirection
- keep docs aligned with current CLI interfaces and managed paths
- do not enforce Python line-length rules on Markdown, TOML, requirements, or
  shell snippets; keep tables, direct dependency pins, commands, and URLs intact
  when wrapping would make them harder to copy, validate, or parse
- avoid documenting lab-specific host policy as product behavior

## Local Checks

Run these from the repo venv:

```bash
black --check src tests
ruff check src tests
python -m compileall src tests
python -m unittest discover -s tests -v
bluetooth_2_usb --help
bluetooth_2_usb --version
bluetooth_2_usb --validate-env || test $? -eq 3
yamllint .github/workflows/ci.yml
python -m build
```

Outside a real Pi gadget environment, `--validate-env` may exit with status `3`.

For broad Python formatting churn, also scan for accidental adjacent string
literals:

```bash
python - <<'PY'
from pathlib import Path
import io
import subprocess
import tokenize

for raw_path in subprocess.check_output(["git", "ls-files", "*.py"], text=True).splitlines():
    path = Path(raw_path)
    if path.parts and path.parts[0] in {"build", "dist", "venv"}:
        continue
    text = path.read_text(encoding="utf-8")
    tokens = [
        token
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type
        not in {
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.COMMENT,
            tokenize.ENCODING,
        }
    ]
    for previous, current in zip(tokens, tokens[1:]):
        if previous.type == tokenize.STRING and current.type == tokenize.STRING:
            print(f"{path}:{previous.start[0]}-{current.start[0]}")
PY
```

## Hardware Validation

If your change affects runtime behavior, installation, service startup, USB
gadget setup, diagnostics, relay behavior, or persistent read-only operation,
validate it on a real Pi.

Use these repo-owned guides when they match the task:

- [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- [docs/cli-service-test.md](docs/cli-service-test.md)
- [docs/host-relay-loopback.md](docs/host-relay-loopback.md)
- [docs/persistent-readonly.md](docs/persistent-readonly.md)
- [docs/remote-wakeup-kernel.md](docs/remote-wakeup-kernel.md)
- [docs/runtime-architecture.md](docs/runtime-architecture.md)

Minimum Pi-side validation after runtime-affecting changes:

```bash
sudo bluetooth_2_usb smoketest --verbose
sudo bluetooth_2_usb debug --duration 10
sudo bluetoothctl show
sudo btmgmt info
```

For relay-path changes, also use the host/Pi loopback inject/capture validation in
[docs/host-relay-loopback.md](docs/host-relay-loopback.md).

## Community Expectations

Thanks for helping keep the project respectful, constructive, and patient for
everyone involved.
