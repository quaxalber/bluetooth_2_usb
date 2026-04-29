# Documentation Consistency Review

Use this checklist when you want to verify that the remaining repo-owned docs
still match the current repository state.

The goal is to catch drift between:

- documented commands
- actual CLI interfaces
- current managed paths and defaults
- the supported development workflow

## Scope

Review at least:

- `README.md`
- `CONTRIBUTING.md`
- `TROUBLESHOOTING.md`
- every remaining `docs/*.md` file
- `src/bluetooth_2_usb/args.py`
- `pyproject.toml`

## What to verify

### 1. Full Markdown doc set

```bash
find docs -maxdepth 1 -type f -name '*.md' -print | sort
sed -n '1,240p' README.md
sed -n '1,240p' CONTRIBUTING.md
sed -n '1,240p' TROUBLESHOOTING.md
```

For each Markdown file, verify that:

- commands still exist
- argument names still exist
- path examples still match the current managed deployment
- placeholders are clearly marked as placeholders
- examples favor readability over unnecessary shell indirection

### 2. Operational CLI interface

Compare the docs against the current `--help` output of the supported
operational commands:

```bash
./venv/bin/python -m bluetooth_2_usb.ops --help
for command in install update uninstall smoketest debug \
  readonly-setup readonly-enable readonly-disable \
  install-hid-udev-rule loopback-inject loopback-capture; do
  echo "==== $command"
  ./venv/bin/python -m bluetooth_2_usb.ops "$command" --help
  echo
done

if [[ -f scripts/loopback-capture.ps1 ]] && command -v powershell >/dev/null 2>&1; then
  echo "==== scripts/loopback-capture.ps1"
  powershell -ExecutionPolicy Bypass -File ./scripts/loopback-capture.ps1 --help
  echo
fi
```

### 3. Runtime CLI interface

```bash
./venv/bin/python -m bluetooth_2_usb --help
./venv/bin/python -m bluetooth_2_usb --version
sed -n '1,220p' src/bluetooth_2_usb/args.py
```

### 4. Managed paths and service assumptions

```bash
sed -n '1,220p' src/bluetooth_2_usb/ops/paths.py
sed -n '1,260p' src/bluetooth_2_usb/ops/deployment.py
sed -n '1,260p' src/bluetooth_2_usb/ops/readonly.py
sed -n '1,120p' bluetooth_2_usb.service
```

Pay attention to:

- install root
- runtime settings path
- read-only config path
- log directory
- persistent Bluetooth-state paths
- service unit name

### 5. Development workflow

Verify that the documented local development flow still works:

```bash
tmpdir="$(mktemp -d)"
python3 -m venv "$tmpdir/venv"
source "$tmpdir/venv/bin/activate"
pip install -U pip setuptools wheel
pip install -e . black ruff yamllint build
python -m bluetooth_2_usb --help
deactivate
rm -rf "$tmpdir"
```

### 6. Drift search for commands, flags, and paths

```bash
rg -n '(bluetooth_2_usb_ops|python -m bluetooth_2_usb.ops|--[a-z0-9][a-z0-9_-]*)' README.md CONTRIBUTING.md TROUBLESHOOTING.md docs
```

Flag anything that is documented but no longer present, or anything that exists
in code but is not explained where an operator would reasonably expect it.

### 7. Syntax and basic code health

```bash
./venv/bin/python -m compileall src tests
./venv/bin/python -m unittest discover -s tests -v
```

## Expected outcome

At the end of the review, answer these questions explicitly:

1. Do the remaining repo docs match the current operational CLI interfaces?
2. Do they match the current Python CLI surface?
3. Do the documented managed paths and defaults still match
   `bluetooth_2_usb.ops.paths` and the service unit?
4. Are there any stale commands, removed flags, outdated entrypoints, or
   unnecessary lab-specific assumptions left?
5. Did you make doc fixes, or is the current documentation already consistent?
