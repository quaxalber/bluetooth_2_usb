# Pi CLI and Service Test Playbook

This playbook is the fast path for repeating the Raspberry Pi script, CLI, and service validation against the current codebase without rebuilding the process from scratch.

It is intentionally focused on:

- `scripts/` validation
- service lifecycle validation
- managed install/update/uninstall validation
- isolated test branches and test repos

The managed install root and service unit are fixed by design throughout this playbook:

- Install root: `/opt/bluetooth_2_usb`
- Service unit: `bluetooth_2_usb.service`

The mainline test flow should exercise the normal managed deployment against GitHub.
Use the Pi-local bare repository only when you explicitly need an isolated snapshot or a force-pushed test branch.

It does not try to cover:

- full OTG end-to-end host input validation
- persistent read-only mode with real external storage
- reboot or power-cycle behavior across physical hardware events

Those remain manual follow-up checks.

## Scope

Use this playbook when you need to validate any of these on a real Pi:

- `bootstrap.sh`
- `install.sh`
- `update.sh`
- `uninstall.sh`
- `smoke_test.sh`
- `debug.sh`
- `enable_readonly_overlayfs.sh`
- `disable_readonly_overlayfs.sh`
- `setup_persistent_bluetooth_state.sh`

## Assumptions

- Local workstation has:
  - `git`
  - `gh`
  - SSH access to the Pi via `ssh -4 pi4b`
- GitHub CLI is already authenticated:

```bash
gh auth status
```

- Pi user has passwordless sudo:

```bash
ssh -4 pi4b 'sudo -n true'
```

- Pi is reachable as `user@pi4b`
- The active Wi-Fi profile on the Pi has powersave disabled

## One-time local setup

These commands create an isolated test branch and a separate private test repository.

Replace the date suffix if needed.

```bash
cd /home/benfred/VS/quaxalber/bluetooth_2_usb

TEST_BRANCH="feat/main-hardening-test-2026-04-05"
TEST_REPO="bluetooth_2_usb_test_2026_04_05"

git switch feat/main-hardening-clean
git switch -c "$TEST_BRANCH"

gh repo create "quaxalber/${TEST_REPO}" --private --source=. --remote=test-origin --push
git push -u origin "$TEST_BRANCH"
git push -u test-origin "$TEST_BRANCH"
```

## Pi-side isolated test checkout

If the Pi cannot clone the private test repository directly over SSH, use the local archive path below. This keeps the productive checkout and the test checkout separate.

```bash
cd /home/benfred/VS/quaxalber/bluetooth_2_usb

git archive --format=tar "$TEST_BRANCH" | ssh -4 pi4b '
  mkdir -p /home/user/bluetooth_2_usb_test_2026_04_05 &&
  tar -xf - -C /home/user/bluetooth_2_usb_test_2026_04_05
'

ssh -4 pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05 &&
  git init -q &&
  git config user.name "b2u test" &&
  git config user.email "b2u-test@example.invalid" &&
  git add . &&
  git commit -q -m "initial test snapshot" || true &&
  git branch -M feat/main-hardening-test-2026-04-05 &&
  git init -q --bare /home/user/bluetooth_2_usb_test_2026_04_05_repo.git &&
  git push -f /home/user/bluetooth_2_usb_test_2026_04_05_repo.git HEAD:feat/main-hardening-test-2026-04-05
'
```

## Refreshing the Pi test checkout after local changes

Use this whenever the test branch changed locally and you want the Pi-side isolated checkout and its local bare repo to match.

```bash
cd /home/benfred/VS/quaxalber/bluetooth_2_usb

git archive --format=tar "$TEST_BRANCH" | ssh -4 pi4b '
  mkdir -p /home/user/bluetooth_2_usb_test_2026_04_05 &&
  tar -xf - -C /home/user/bluetooth_2_usb_test_2026_04_05
'

ssh -4 pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05 &&
  git add -A &&
  if ! git diff --cached --quiet; then
    git commit -m "sync test snapshot"
  fi &&
  git push -f /home/user/bluetooth_2_usb_test_2026_04_05_repo.git HEAD:feat/main-hardening-test-2026-04-05
'
```

## Baseline Pi status snapshot

Run this before mutating the system.

```bash
ssh -4 pi4b '
  wifi_conn=$(nmcli -t -f NAME connection show --active | head -n 1)
  echo BRANCH=$(cd /home/user/bluetooth_2_usb_test_2026_04_05 && git branch --show-current)
  echo SHA=$(cd /home/user/bluetooth_2_usb_test_2026_04_05 && git rev-parse --short HEAD)
  echo SERVICE=$(systemctl is-active bluetooth_2_usb.service)
  echo ROOT=$(findmnt -no FSTYPE,OPTIONS /)
  echo OVERLAY_NOW=$(sudo -n raspi-config nonint get_overlay_now)
  echo WIFI_CONN=$wifi_conn
  nmcli -g 802-11-wireless.powersave connection show "$wifi_conn"
'
```

> Replace nothing in that block manually; it resolves the currently active Wi-Fi connection name on the Pi before querying the powersave setting.

## CLI matrix

This covers the safe argument-surface checks:

- `--help`
- unknown option handling
- missing-value handling for every option that requires a value

Run from the Pi test checkout:

```bash
ssh -4 pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05

  bash scripts/bootstrap.sh --help >/dev/null
  bash scripts/install.sh --help >/dev/null
  bash scripts/update.sh --help >/dev/null
  bash scripts/uninstall.sh --help >/dev/null
  bash scripts/smoke_test.sh --help >/dev/null
  bash scripts/debug.sh --help >/dev/null
  bash scripts/enable_readonly_overlayfs.sh --help >/dev/null
  bash scripts/disable_readonly_overlayfs.sh --help >/dev/null
  bash scripts/setup_persistent_bluetooth_state.sh --help >/dev/null
'
```

Then explicitly sample the missing-value paths:

```bash
ssh -4 pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05
  for cmd in \
    "bash scripts/bootstrap.sh --repo" \
    "bash scripts/bootstrap.sh --branch" \
    "bash scripts/install.sh --repo" \
    "bash scripts/install.sh --branch" \
    "bash scripts/update.sh --repo" \
    "bash scripts/update.sh --branch" \
    "bash scripts/debug.sh --duration" \
    "bash scripts/enable_readonly_overlayfs.sh --mode" \
    "bash scripts/enable_readonly_overlayfs.sh --persist-device" \
    "bash scripts/setup_persistent_bluetooth_state.sh --device" \
    "bash scripts/setup_persistent_bluetooth_state.sh --no-enable --device"
  do
    eval "$cmd" >/dev/null 2>&1 || true
  done
'
```

## Safe runtime tests

Run these from the Pi test checkout first:

```bash
ssh -4 pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05
  sudo -n bash scripts/smoke_test.sh --verbose
  sudo -n bash scripts/debug.sh --duration 5 --redact
'
```

For the unbounded debug flow:

```bash
ssh -4 -t pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05
  sudo -n bash scripts/debug.sh --redact
'
```

Interrupt it with `Ctrl+C`.

Expected behavior:

- `debug.sh` stops the service if needed
- runs a foreground `--debug` session
- streams the live debug output to stdout
- writes the live output into the Markdown report
- restores the service when the script exits

## Update tests

Preferred update test against GitHub:

```bash
ssh -4 pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05
  sudo -n bash scripts/update.sh \
    --repo https://github.com/quaxalber/bluetooth_2_usb.git \
    --branch feat/main-hardening-test-2026-04-05
'
```

Use the Pi-local bare repo only when you need a fully isolated snapshot:

```bash
ssh -4 pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05
  sudo -n bash scripts/update.sh \
    --repo /home/user/bluetooth_2_usb_test_2026_04_05_repo.git \
    --branch feat/main-hardening-test-2026-04-05
'
```

No-restart path:

```bash
ssh -4 pi4b '
  BEFORE=$(systemctl show -P ActiveEnterTimestampMonotonic bluetooth_2_usb.service)
  cd /home/user/bluetooth_2_usb_test_2026_04_05
  sudo -n bash scripts/update.sh \
    --repo https://github.com/quaxalber/bluetooth_2_usb.git \
    --branch feat/main-hardening-test-2026-04-05 \
    --no-restart
  AFTER=$(systemctl show -P ActiveEnterTimestampMonotonic bluetooth_2_usb.service)
  printf "BEFORE=%s\nAFTER=%s\n" "$BEFORE" "$AFTER"
'
```

## Install tests

Preferred install test against GitHub:

```bash
ssh -4 pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05
  sudo -n bash scripts/install.sh \
    --repo https://github.com/quaxalber/bluetooth_2_usb.git \
    --branch feat/main-hardening-test-2026-04-05 \
    --no-reboot
'
```

Use the Pi-local bare repo only when you want the install to come from an isolated snapshot:

```bash
ssh -4 pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05
  sudo -n bash scripts/install.sh \
    --repo /home/user/bluetooth_2_usb_test_2026_04_05_repo.git \
    --branch feat/main-hardening-test-2026-04-05 \
    --no-reboot
'
```

After either install:

```bash
ssh -4 pi4b '
  systemctl is-active bluetooth_2_usb.service
  sudo -n /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --version
  sudo -n bash /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
'
```

## Bootstrap tests

For the private test repository, use HTTPS with a GitHub token so both archive download and git clone can succeed on the Pi:

This replaces the active managed install in `/opt/bluetooth_2_usb`.

```bash
TOKEN=$(gh auth token)

ssh -4 pi4b "
  curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/${TEST_BRANCH}/scripts/bootstrap.sh |
    sudo -n bash -s -- \
      --repo https://x-access-token:${TOKEN}@github.com/quaxalber/${TEST_REPO}.git \
      --branch ${TEST_BRANCH} \
      --no-reboot
"
```

Immediately verify that the running process still matches the standard managed path:

```bash
ssh -4 pi4b '
  systemctl show -P ExecStart bluetooth_2_usb.service
  ps -o args= -p $(systemctl show -P MainPID bluetooth_2_usb.service)
  sudo -n /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --version
'
```

The running process and `ExecStart` should both point to `/opt/bluetooth_2_usb/...`.

## Tag tests

Create or update a test tag on the current branch:

```bash
cd /home/benfred/VS/quaxalber/bluetooth_2_usb

TAG=hardening-test-install-2026-04-05
git tag -f -a "$TAG" -m "Test tag for Pi install validation" "$TEST_BRANCH"
git push -f test-origin "refs/tags/$TAG"
```

Use a non-release-like tag name here on purpose. Official package releases are reserved for `vMAJOR.MINOR.PATCH` tags only.

Push the same tag into the Pi-local bare repo if you are using that path:

```bash
ssh -4 pi4b '
  cd /home/user/bluetooth_2_usb_test_2026_04_05 &&
  git tag -f hardening-test-install-2026-04-05 HEAD >/dev/null 2>&1 &&
  git push -f /home/user/bluetooth_2_usb_test_2026_04_05_repo.git refs/tags/hardening-test-install-2026-04-05
'
```

Install from the tag:

This also replaces the active managed install in `/opt/bluetooth_2_usb`.

```bash
TOKEN=$(gh auth token)

ssh -4 pi4b "
  cd /home/user/bluetooth_2_usb_test_2026_04_05 &&
  sudo -n bash scripts/install.sh \
    --repo https://x-access-token:${TOKEN}@github.com/quaxalber/${TEST_REPO}.git \
    --branch ${TAG} \
    --no-reboot
"
```

Validate:

```bash
ssh -4 pi4b '
  systemctl show -P ExecStart bluetooth_2_usb.service
  ps -o args= -p $(systemctl show -P MainPID bluetooth_2_usb.service)
  sudo -n /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --version
'
```

The version string should remain a normal package version derived from the real release lineage. It should not collapse to a meaningless `v5`-style value.

## Uninstall tests

Non-purge:

```bash
ssh -4 pi4b '
  sudo -n bash /opt/bluetooth_2_usb/scripts/uninstall.sh \
    --no-reboot
'
```

Purge:

```bash
ssh -4 pi4b '
  sudo -n bash /opt/bluetooth_2_usb/scripts/uninstall.sh \
    --purge \
    --no-reboot
'
```

Purge and boot revert:

```bash
ssh -4 pi4b '
  sudo -n bash /opt/bluetooth_2_usb/scripts/uninstall.sh \
    --purge \
    --revert-boot \
    --no-reboot
'
```

After uninstall, verify:

```bash
ssh -4 pi4b '
  systemctl is-active bluetooth_2_usb.service || true
  systemctl show -P LoadState bluetooth_2_usb.service
  test -d /opt/bluetooth_2_usb && echo exists || echo missing
'
```

## Read-only tests

### Easy mode

This tests configuration and reporting, not post-reboot behavior.

```bash
ssh -4 pi4b '
  cd /opt/bluetooth_2_usb
  sudo -n bash scripts/enable_readonly_overlayfs.sh --mode easy
  sudo -n raspi-config nonint get_overlay_now
  sudo -n cat /etc/default/bluetooth_2_usb_readonly
  ls -l /boot/firmware/bluetooth_2_usb/readonly_snapshot
  sudo -n bash scripts/smoke_test.sh --verbose
  sudo -n bash scripts/debug.sh --duration 3 --redact
  sudo -n bash scripts/disable_readonly_overlayfs.sh
'
```

### Persistent mode

Without a real spare ext4 device, restrict this to error-path validation:

```bash
ssh -4 pi4b '
  cd /opt/bluetooth_2_usb
  sudo -n bash scripts/setup_persistent_bluetooth_state.sh --device /dev/doesnotexist || true
  sudo -n bash scripts/setup_persistent_bluetooth_state.sh --no-enable || true
  sudo -n bash scripts/enable_readonly_overlayfs.sh --mode persistent || true
'
```

## Result categories

When you repeat the playbook, classify results as:

- `passed`
- `failed`
- `blocked`
- `open for user`

Suggested summary format:

```text
bootstrap.sh: passed
install.sh: passed
update.sh: passed
uninstall.sh: passed
smoke_test.sh: passed
debug.sh: passed
enable_readonly_overlayfs.sh easy mode: passed
enable_readonly_overlayfs.sh persistent happy path: open for user
setup_persistent_bluetooth_state.sh happy path: open for user
OTG host end-to-end input: open for user
```

## Still manual

Even after this playbook, these remain manual hardware validations:

- persistent mode with real ext4 storage
- post-reboot persistent mode behavior
- power-cycle behavior
- OTG host end-to-end input
- Windows, BIOS, and pre-OS host validation
- long-running Wi-Fi stability
