# Pi CLI and Service Test Playbook

This playbook is the fast path for repeating Raspberry Pi validation against the
current codebase without rebuilding the process from scratch.

It is intentionally focused on:

- managed install validation
- service lifecycle validation
- smoke and debug validation
- persistent read-only validation
- uninstall validation

## Assumptions

- local workstation has `git`, `gh`, and SSH access to the Pi
- the Pi is normally reachable as `pi4b`
- the Pi user has passwordless sudo:

```bash
ssh -4 pi4b 'sudo -n true'
```

If `pi4b` is unreachable, treat that first as an environment problem. It may
need a manual reboot before retrying.

## Prepare the checkout on the Pi

The supported deployment model is a normal Git checkout at
`/opt/bluetooth_2_usb`.

If the Pi image does not include `git`, which is common on Raspberry Pi OS
Lite, install it first:

```bash
ssh -4 pi4b 'sudo -n apt update && sudo -n apt install -y git'
```

For a test branch:

```bash
BRANCH="${BRANCH:-main}"

ssh -4 pi4b "
  sudo -n rm -rf /opt/bluetooth_2_usb &&
  sudo -n git clone https://github.com/quaxalber/bluetooth_2_usb.git /opt/bluetooth_2_usb &&
  sudo -n git -C /opt/bluetooth_2_usb checkout \"${BRANCH}\"
"
```

## Baseline status snapshot

Run this before mutating the system:

```bash
ssh -4 pi4b '
  echo SERVICE=$(systemctl is-active bluetooth_2_usb.service || true)
  echo OVERLAY=$(sudo -n raspi-config nonint get_overlay_now 2>/dev/null || echo unknown)
  echo ROOT=$(findmnt -no FSTYPE,OPTIONS /)
  uname -a
'
```

## Script help surface

```bash
ssh -4 pi4b '
  bash /opt/bluetooth_2_usb/scripts/install.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/uninstall.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/smoke_test.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/debug.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/disable_readonly_overlayfs.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --help >/dev/null
'
```

## Install validation

```bash
ssh -4 pi4b '
  sudo -n /opt/bluetooth_2_usb/scripts/install.sh
'
```

Reboot and wait for SSH:

```bash
ssh -4 pi4b 'sudo -n reboot' || true
until ssh -4 -o ConnectTimeout=5 pi4b 'true' 2>/dev/null; do sleep 2; done
```

After reboot, verify:

```bash
ssh -4 pi4b '
  systemctl is-active bluetooth_2_usb.service
  sudo -n /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
  sudo -n bluetoothctl show
  sudo -n btmgmt info
'
```

## Update validation

The supported update model is Git plus reinstall:

```bash
ssh -4 pi4b '
  sudo -n git -C /opt/bluetooth_2_usb pull --ff-only
  sudo -n /opt/bluetooth_2_usb/scripts/install.sh
'
```

Reboot and wait for SSH so the update path is validated against the next boot:

```bash
ssh -4 pi4b 'sudo -n reboot' || true
until ssh -4 -o ConnectTimeout=5 pi4b 'true' 2>/dev/null; do sleep 2; done
```

After reboot, verify:

```bash
ssh -4 pi4b '
  systemctl is-active bluetooth_2_usb.service
  sudo -n /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
  sudo -n bluetoothctl show
  sudo -n btmgmt info
'
```

## Debug validation

Bounded run:

```bash
ssh -4 pi4b '
  sudo -n /opt/bluetooth_2_usb/scripts/debug.sh --duration 5
'
```

Manual interrupt path:

```bash
ssh -4 -t pi4b '
  sudo -n /opt/bluetooth_2_usb/scripts/debug.sh
'
```

Inspect the resulting report and verify:

- the service was restored afterwards
- the live debug section contains real runtime output
- the report is redacted
- the report does not contradict the actual service and mount state

## Persistent read-only validation

Prepare the writable ext4 partition:

```bash
ssh -4 pi4b '
  sudo -n /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/YOUR-PARTITION
  sudo -n /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh
'
```

Reboot and wait for SSH after `enable_readonly_overlayfs.sh`:

```bash
ssh -4 pi4b 'sudo -n reboot' || true
until ssh -4 -o ConnectTimeout=5 pi4b 'true' 2>/dev/null; do sleep 2; done
```

After reboot:

```bash
ssh -4 pi4b '
  sudo -n /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
  findmnt /var/lib/bluetooth
  findmnt /mnt/b2u-persist
'
```

Disable read-only mode again:

```bash
ssh -4 pi4b '
  sudo -n /opt/bluetooth_2_usb/scripts/disable_readonly_overlayfs.sh
'
```

Reboot and wait for SSH after `disable_readonly_overlayfs.sh`:

```bash
ssh -4 pi4b 'sudo -n reboot' || true
until ssh -4 -o ConnectTimeout=5 pi4b 'true' 2>/dev/null; do sleep 2; done
```

## Uninstall validation

```bash
ssh -4 pi4b '
  sudo -n /opt/bluetooth_2_usb/scripts/uninstall.sh
  systemctl is-active bluetooth_2_usb.service || true
  systemctl show -P LoadState bluetooth_2_usb.service
  test -d /opt/bluetooth_2_usb && echo checkout-present || echo checkout-missing
'
```

Expected outcome:

- service integration is removed
- checkout remains present
- persistent mount units are disabled
- runtime env files and wrapper are removed

## What to record

For each run, record:

```bash
ssh -4 pi4b '
  uname -a
  cat /etc/os-release
  echo SERVICE=$(systemctl is-active bluetooth_2_usb.service || true)
  echo READONLY=$(grep "^B2U_READONLY_MODE=" /etc/default/bluetooth_2_usb_readonly 2>/dev/null || echo disabled)
  sudo -n journalctl -u bluetooth_2_usb.service -n 100 --no-pager || true
'
```
