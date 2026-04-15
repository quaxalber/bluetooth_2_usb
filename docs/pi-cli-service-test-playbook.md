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

- workstation has `git` and SSH access to the Pi
- the Pi user has passwordless sudo:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" 'sudo -n true'
```

## Prepare the checkout on the Pi

The supported deployment model is a normal Git checkout at
`/opt/bluetooth_2_usb`.

If the Pi image does not include `git`, which is common on Raspberry Pi OS
Lite, install it first:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" 'sudo -n apt update && sudo -n apt install -y git'
```

For a test branch:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"
BRANCH="${BRANCH:-main}"

ssh -4 "$PI_HOST" "
  sudo -n rm -rf /opt/bluetooth_2_usb &&
  sudo -n git clone https://github.com/quaxalber/bluetooth_2_usb.git /opt/bluetooth_2_usb &&
  sudo -n git -C /opt/bluetooth_2_usb checkout \"${BRANCH}\"
"
```

## Baseline status snapshot

Run this before mutating the system:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  echo SERVICE=$(systemctl is-active bluetooth_2_usb.service || true)
  echo OVERLAY=$(sudo -n raspi-config nonint get_overlay_now 2>/dev/null || echo unknown)
  echo ROOT=$(findmnt -no FSTYPE,OPTIONS /)
  uname -a
'
```

## Script help surface

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  bash /opt/bluetooth_2_usb/scripts/install.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/update.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/uninstall.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/smoke_test.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/debug.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/pi_relay_test_inject.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/disable_readonly_overlayfs.sh --help >/dev/null
  bash /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --help >/dev/null
'
```

## Install validation

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  sudo -n /opt/bluetooth_2_usb/scripts/install.sh
'
```

Reboot and wait for SSH:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" 'sudo -n reboot' || true
until ssh -4 -o ConnectTimeout=5 "$PI_HOST" 'true' 2>/dev/null; do sleep 2; done
```

After reboot, verify:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  systemctl is-active bluetooth_2_usb.service
  sudo -n /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
  sudo -n bluetoothctl show
  sudo -n btmgmt info
'
```

Interpret the smoke result conservatively:

- `PASSED` is ideal
- `PASSED (with warnings)` is still acceptable if no paired or relayable
  devices are present yet, or if the OTG cable is not attached and the UDC
  state is therefore not `configured`

## Update validation

The supported update model is the managed update wrapper:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  sudo -n /opt/bluetooth_2_usb/scripts/update.sh
'
```

If no new commit is available on the checked-out branch, this should exit `0`
without rebuilding the managed virtual environment or restarting the service.

Reboot and wait for SSH so the update path is validated against the next boot:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" 'sudo -n reboot' || true
until ssh -4 -o ConnectTimeout=5 "$PI_HOST" 'true' 2>/dev/null; do sleep 2; done
```

After reboot, verify:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  systemctl is-active bluetooth_2_usb.service
  sudo -n /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
  sudo -n bluetoothctl show
  sudo -n btmgmt info
'
```

Interpret the smoke result conservatively:

- `PASSED` is ideal
- `PASSED (with warnings)` is still acceptable if no paired or relayable
  devices are present yet, or if the OTG cable is not attached and the UDC
  state is therefore not `configured`

## Debug validation

Bounded run:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  sudo -n /opt/bluetooth_2_usb/scripts/debug.sh --duration 5
'
```

Manual interrupt path:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 -t "$PI_HOST" '
  sudo -n /opt/bluetooth_2_usb/scripts/debug.sh
'
```

Inspect the resulting report and verify:

- the service was restored afterwards
- the live debug section contains real runtime output
- the report is redacted
- the report does not contradict the actual service and mount state
- the reported UDC state matches the real cable/host situation

## Relay loopback validation

If the Pi is physically attached to a Linux host through the gadget data path,
run the end-to-end relay loopback harness from
`docs/pi-host-relay-loopback-test-playbook.md`.

This is the most direct way to verify that relayed input events actually arrive
at the host without depending on a paired Bluetooth device.

## Persistent read-only validation

Prepare the writable ext4 partition:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  sudo -n /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/YOUR-PARTITION
  sudo -n /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh
'
```

Reboot and wait for SSH after `enable_readonly_overlayfs.sh`:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" 'sudo -n reboot' || true
until ssh -4 -o ConnectTimeout=5 "$PI_HOST" 'true' 2>/dev/null; do sleep 2; done
```

After reboot:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  sudo -n /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
  findmnt /var/lib/bluetooth
  findmnt /mnt/b2u-persist
'
```

Disable read-only mode again:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  sudo -n /opt/bluetooth_2_usb/scripts/disable_readonly_overlayfs.sh
'
```

Reboot and wait for SSH after `disable_readonly_overlayfs.sh`:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" 'sudo -n reboot' || true
until ssh -4 -o ConnectTimeout=5 "$PI_HOST" 'true' 2>/dev/null; do sleep 2; done
```

## Uninstall validation

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  sudo -n /opt/bluetooth_2_usb/scripts/uninstall.sh
  systemctl is-active bluetooth_2_usb.service || true
  systemctl show -P LoadState bluetooth_2_usb.service
  systemctl is-enabled var-lib-bluetooth.mount >/dev/null 2>&1 && echo mount-enabled || echo mount-disabled
  systemctl is-active var-lib-bluetooth.mount >/dev/null 2>&1 && echo mount-active || echo mount-inactive
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
PI_HOST="${PI_HOST:-your-pi-host}"

ssh -4 "$PI_HOST" '
  uname -a
  cat /etc/os-release
  echo SERVICE=$(systemctl is-active bluetooth_2_usb.service || true)
  echo READONLY=$(grep "^B2U_READONLY_MODE=" /etc/default/bluetooth_2_usb_readonly 2>/dev/null || echo disabled)
  sudo -n journalctl -u bluetooth_2_usb.service -n 100 --no-pager || true
'
```
