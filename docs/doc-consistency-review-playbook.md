# Documentation Consistency Review Playbook

Use this checklist when you want to verify that `README.md` and `CONTRIBUTING.md` still match the current repository state.

This is not a generic docs review. The goal is to catch drift between:

- documented commands
- actual script and CLI interfaces
- current managed paths and defaults
- current packaging and development workflow

## Scope

Review at least:

- `README.md`
- `CONTRIBUTING.md`
- `scripts/*.sh`
- `scripts/lib/common.sh`
- `src/bluetooth_2_usb/args.py`
- `pyproject.toml`

Check `docs/` too if the change touched testing, read-only mode, install/update flows, or review workflow.

## What to verify

### 1. Script interfaces

Compare the documentation against the current `--help` output of all managed scripts:

```bash
for s in \
  scripts/bootstrap.sh \
  scripts/install.sh \
  scripts/update.sh \
  scripts/uninstall.sh \
  scripts/debug.sh \
  scripts/smoke_test.sh \
  scripts/enable_readonly_overlayfs.sh \
  scripts/disable_readonly_overlayfs.sh \
  scripts/setup_persistent_bluetooth_state.sh
do
  echo "==== $s"
  bash "$s" --help
  echo
done
```

Confirm that the docs do not mention removed options such as old testing or path overrides.

### 2. Python CLI interface

Compare the documented CLI reference against the current package interface:

```bash
python -m bluetooth_2_usb --help
python -m bluetooth_2_usb --version
```

Also inspect the source of truth:

```bash
sed -n '1,220p' src/bluetooth_2_usb/args.py
```

Make sure option names, defaults, and descriptions in the docs still match.

### 3. Managed paths and service assumptions

Verify documented paths and service names against the current shared shell constants and service unit:

```bash
sed -n '1,220p' scripts/lib/common.sh
sed -n '1,120p' bluetooth_2_usb.service
```

Pay attention to:

- install root
- runtime config path
- read-only config path
- log directory
- persistent Bluetooth-state paths
- service unit name

### 4. Development workflow

Verify that the documented local development flow still works.

A good baseline check is:

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

This catches stale references to removed entrypoints or outdated install instructions.

### 5. Drift search for removed options or old paths

Search the docs for options and paths that were removed or renamed:

```bash
rg -n -e '--dir' \
      -e '--service' \
      -e '--venv' \
      -e '--skip-clone' \
      -e '--mount' \
      -e '--bluetooth-subdir' \
      -e '--bt-subdir' \
      -e '--format' \
      -e 'python3.11' \
      -e 'bluetooth_2_usb.py' \
      -e 'bluetooth_2_usb.sh' \
      README.md CONTRIBUTING.md docs
```

Interpret the results, do not blindly delete every match. Some hits may be legitimate prose or examples in historical test docs.

### 6. Syntax and basic code health

When doc changes include command examples or script interface descriptions, run the baseline checks too:

```bash
python -m compileall src
bash -n scripts/*.sh scripts/lib/common.sh
```

## Review heuristics

When checking `README.md` and `CONTRIBUTING.md`, pay special attention to:

- commands that no longer exist
- commands that still work but now have different defaults
- references to removed files or entrypoints
- branch/tag/install examples that no longer match script behavior
- issue-report guidance that duplicates information already present in `debug.sh`
- read-only mode claims that overstate persistence guarantees

## Expected outcome

At the end of the review, answer these questions explicitly:

1. Do `README.md` and `CONTRIBUTING.md` match the current script interfaces?
2. Do they match the current Python CLI surface?
3. Do the documented managed paths and runtime defaults still match `common.sh` and the systemd unit?
4. Are there any stale commands, removed flags, or outdated entrypoints left?
5. Did you make doc fixes, or is the current documentation already consistent?

If you do make changes, keep them narrow and traceable to specific mismatches.
