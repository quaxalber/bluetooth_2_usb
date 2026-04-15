# Documentation Consistency Review Playbook

Use this checklist when you want to verify that `README.md`,
`CONTRIBUTING.md`, and the Markdown playbooks under `docs/` still match the
current repository state.

The goal is to catch drift between:

- documented commands
- actual script and CLI interfaces
- current managed paths and defaults
- current packaging and development workflow

## Scope

Review at least:

- `README.md`
- `CONTRIBUTING.md`
- every `docs/*.md` file
- `scripts/*.sh`
- `scripts/lib/*.sh`
- `src/bluetooth_2_usb/args.py`
- `pyproject.toml`

## What to verify

### 1. Full Markdown doc set

```bash
find docs -maxdepth 1 -name '*.md' -print | sort
sed -n '1,240p' README.md
sed -n '1,240p' CONTRIBUTING.md
```

For each file under `docs/`, verify that:

- commands still exist
- argument names still exist
- path examples still match the current managed deployment
- placeholders are still clearly marked as placeholders
- Pi-specific examples still match the current workflow

### 2. Script interfaces

Compare the docs against the current `--help` output of all managed scripts and
wrapper entrypoints:

```bash
for s in \
  scripts/install.sh \
  scripts/update.sh \
  scripts/uninstall.sh \
  scripts/debug.sh \
  scripts/smoke_test.sh \
  scripts/pi_relay_test_inject.sh \
  scripts/host_relay_test_capture.sh \
  scripts/install_host_hidapi_udev_rule.sh \
  scripts/enable_readonly_overlayfs.sh \
  scripts/disable_readonly_overlayfs.sh \
  scripts/setup_persistent_bluetooth_state.sh
do
  echo "==== $s"
  bash "$s" --help
  echo
done

echo "==== scripts/host_relay_test_capture.ps1"
powershell -ExecutionPolicy Bypass -File .\\scripts\\host_relay_test_capture.ps1 --help
echo
```

### 3. Python CLI interface

```bash
python -m bluetooth_2_usb --help
python -m bluetooth_2_usb --version
sed -n '1,220p' src/bluetooth_2_usb/args.py
```

Confirm that the docs match the current option names, defaults, and behavior.

### 4. Managed paths and service assumptions

```bash
for f in scripts/lib/*.sh; do
  echo "==== $f"
  sed -n '1,220p' "$f"
done
sed -n '1,120p' bluetooth_2_usb.service
```

Pay attention to:

- install root
- runtime config path
- read-only config path
- log directory
- persistent Bluetooth-state paths
- service unit name
- whether generic helpers, path constants, and workflow-specific shell logic are
  still separated cleanly across the shell libs

### 5. Development workflow

Verify that the documented local development flow still works:

```bash
tmpdir="$(mktemp -d)"
python3 -m venv "$tmpdir/venv"
source "$tmpdir/venv/bin/activate"
pip install -U pip setuptools wheel
pip install -e .
python -m bluetooth_2_usb --help
deactivate
rm -rf "$tmpdir"
```

### 6. Drift search for commands, flags, and paths

Search the docs for the public surface they describe:

```bash
rg -n '(scripts/[a-z_]+\.sh|--[a-z0-9][a-z0-9_-]*)' README.md CONTRIBUTING.md docs
```

Use the matches as an inventory, then compare each script path and option
against the current `--help` output and the runtime code. Flag anything that is
documented but no longer present, or anything that exists in code but is not
explained where an operator would reasonably expect it.

### 7. Syntax and basic code health

```bash
python -m compileall src tests
python -m unittest discover -s tests -v
bash -n scripts/*.sh scripts/lib/*.sh
```

## Expected outcome

At the end of the review, answer these questions explicitly:

1. Do `README.md`, `CONTRIBUTING.md`, and all relevant `docs/*.md` files match
   the current script interfaces?
2. Do they match the current Python CLI surface?
3. Do the documented managed paths and defaults still match
   `scripts/lib/paths.sh` and the service unit? `scripts/lib/paths.sh` is the
   authoritative source for managed path constants.
4. Are there any stale commands, removed flags, outdated entrypoints, or
   hard-coded environment values left?
5. Did you make doc fixes, or is the current documentation already consistent?
