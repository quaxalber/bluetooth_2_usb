# Documentation Consistency Review

Use this checklist when you want to verify that the remaining repo-owned docs
still match the current repository state.

The goal is to catch drift between:

- documented commands
- actual script and CLI interfaces
- current managed paths and defaults
- the supported development workflow

## Scope

Review at least:

- `README.md`
- `CONTRIBUTING.md`
- `TROUBLESHOOTING.md`
- every remaining `docs/**/*.md` file
- supported public shell entrypoints under `scripts/`
- `src/bluetooth_2_usb/args.py`
- `pyproject.toml`

## What to verify

### 1. Full Markdown doc set

```bash
find docs -type f -name '*.md' -print | sort
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

### 2. Script interfaces

Compare the docs against the current `--help` output of the supported public
scripts:

```bash
mapfile -d '' shell_scripts < <(
  find scripts -maxdepth 2 -type f -name '*.sh' ! -path 'scripts/lib/*' -print0 | sort -z
)
for s in "${shell_scripts[@]}"; do
  echo "==== $s"
  bash "$s" --help
  echo
done

if [[ -f scripts/host/host_relay_test_capture.ps1 ]]; then
  echo "==== scripts/host/host_relay_test_capture.ps1"
  powershell -ExecutionPolicy Bypass -File .\\scripts\\host\\host_relay_test_capture.ps1 --help
  echo
fi
```

### 3. Python CLI interface

```bash
python -m bluetooth_2_usb --help
python -m bluetooth_2_usb --version
sed -n '1,220p' src/bluetooth_2_usb/args.py
```

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

### 5. Development workflow

Verify that the documented local development flow still works:

```bash
tmpdir="$(mktemp -d)"
python3 -m venv "$tmpdir/venv"
source "$tmpdir/venv/bin/activate"
pip install -U pip setuptools wheel
pip install -e . black ruff yamllint shfmt-py shellcheck-py build
python -m bluetooth_2_usb --help
deactivate
rm -rf "$tmpdir"
```

### 6. Drift search for commands, flags, and paths

```bash
rg -n '(scripts/[a-z0-9_./-]+\.sh|--[a-z0-9][a-z0-9_-]*)' README.md CONTRIBUTING.md TROUBLESHOOTING.md docs
```

Flag anything that is documented but no longer present, or anything that exists
in code but is not explained where an operator would reasonably expect it.

### 7. Syntax and basic code health

```bash
python -m compileall src tests
python -m unittest discover -s tests -v
mapfile -d '' shell_scripts < <(find scripts -type f -name '*.sh' -print0 | sort -z)
bash -n "${shell_scripts[@]}"
```

## Expected outcome

At the end of the review, answer these questions explicitly:

1. Do the remaining repo docs match the current script interfaces?
2. Do they match the current Python CLI surface?
3. Do the documented managed paths and defaults still match
   `scripts/lib/paths.sh` and the service unit?
4. Are there any stale commands, removed flags, outdated entrypoints, or
   unnecessary lab-specific assumptions left?
5. Did you make doc fixes, or is the current documentation already consistent?
