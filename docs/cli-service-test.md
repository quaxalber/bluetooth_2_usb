# Pi CLI and Service Test

Use this guide when you want the full, repeatable Raspberry Pi validation flow
for the current codebase.

This is the authoritative Pi-side validation guide for:

- managed install validation
- service lifecycle validation
- smoketest and debug validation
- real device relay validation
- loopback inject/capture validation
- read-only validation
- pairing persistence validation
- uninstall validation

## Assumptions

- the workstation has `git` and SSH access to the Pi
- the Pi user has passwordless sudo
- workstation-specific SSH and network recovery is handled separately from this
  repo

Quick check:

```bash
ssh <pi-host> 'sudo -n true'
```

Replace `<pi-host>` with the real SSH host or alias.

> [!TIP]
> Take the baseline status snapshot below before mutating the Pi. It gives you
> the service, overlay, root filesystem, and kernel state to compare against
> after install, read-only, or reboot-sensitive validation.

## Prepare the checkout on the Pi

The supported deployment model is a normal Git checkout at
`/opt/bluetooth_2_usb`.

If the Pi image does not include `git`, install it first:

```bash
ssh <pi-host> 'sudo -n apt update && sudo -n apt install -y git'
```

For a test branch:

```bash
ssh <pi-host> '
  sudo -n rm -rf /opt/bluetooth_2_usb &&
  sudo -n git clone https://github.com/quaxalber/bluetooth_2_usb.git /opt/bluetooth_2_usb &&
  sudo -n git -C /opt/bluetooth_2_usb checkout <branch-name>
'
```

## Baseline status snapshot

Run this before mutating the system:

```bash
ssh <pi-host> '
  echo SERVICE=$(systemctl is-active bluetooth_2_usb.service || true)
  echo OVERLAY=$(sudo -n raspi-config nonint get_overlay_now 2>/dev/null || echo unknown)
  echo ROOT=$(findmnt -no FSTYPE,OPTIONS /)
  uname -a
'
```

## Operational CLI help surface

```bash
ssh <pi-host> '
  cd /opt/bluetooth_2_usb
  PYTHONPATH=src python3 -m bluetooth_2_usb install --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb update --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb uninstall --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb smoketest --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb debug --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb udev install --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb loopback inject --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb loopback capture --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb readonly status --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb readonly enable --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb readonly disable --help >/dev/null
  PYTHONPATH=src python3 -m bluetooth_2_usb readonly setup --help >/dev/null
'
```

## Install validation

```bash
ssh <pi-host> '
  cd /opt/bluetooth_2_usb
  sudo -n env PYTHONPATH=src python3 -m bluetooth_2_usb install
'
old_boot_id="$(ssh <pi-host> 'cat /proc/sys/kernel/random/boot_id')"
ssh <pi-host> 'sudo -n reboot' || true
deadline=$((SECONDS + 180))
until new_boot_id="$(ssh -o ConnectTimeout=5 <pi-host> 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null)" \
  && [[ "$new_boot_id" != "$old_boot_id" ]]; do
  if (( SECONDS >= deadline )); then
    echo "Pi did not come back after reboot within 180s with a new boot_id" >&2
    exit 1
  fi
  sleep 2
done
```

After reboot:

```bash
ssh <pi-host> '
  systemctl is-active bluetooth_2_usb.service
  sudo -n bluetooth_2_usb smoketest --verbose
  sudo -n bluetoothctl show
  sudo -n btmgmt info
'
```

`PASSED (with warnings)` is acceptable when no paired or relayable devices are
present yet, or when the OTG cable is not attached and the UDC state is not
`configured`.

## Update validation

```bash
ssh <pi-host> 'sudo -n bluetooth_2_usb update'
```

If no new commit is available on the checked-out branch, this should exit `0`
after reapplying the managed install and restarting the service.

Reboot and repeat the post-boot smoketest checks if the updated change touched boot
configuration or other reboot-sensitive behavior.

## Debug validation

Bounded run:

```bash
ssh <pi-host> 'sudo -n bluetooth_2_usb debug --duration 10'
```

Manual interrupt path:

```bash
ssh -t <pi-host> 'sudo -n bluetooth_2_usb debug'
```

Verify:

- the service is restored afterwards
- the live debug block contains real runtime output
- the report is redacted
- the report does not contradict actual service and mount state

## Real relay validation with a paired device

Use this when you want to prove the real user path, not just the loopback path.

Steps:

1. pair the target Bluetooth keyboard or mouse
2. connect the Pi to the target host over the OTG-capable port
3. verify normal typing or pointer movement
4. verify the interrupt shortcut if configured

Pass criteria:

- input reaches the target host reliably
- no unexpected local input leakage when devices are grabbed

## Relay loopback inject/capture validation

If the Pi is physically attached to a host through the gadget data path, run the
end-to-end loopback inject/capture validation from
[host-relay-loopback.md](host-relay-loopback.md).

## Read-only validation

> [!WARNING]
> This flow uses persistent storage, changes boot/read-only state, and reboots
> the Pi. Verify `<persist-partition>` with `lsblk -f` before running setup.

Prepare the writable ext4 partition:

Replace `<persist-partition>` with the actual writable ext4 partition after
verifying it with `lsblk -f`.

```bash
ssh <pi-host> '
  sudo -n bluetooth_2_usb readonly setup --device <persist-partition>
  bluetooth_2_usb readonly status
  sudo -n bluetooth_2_usb readonly enable
'
old_boot_id="$(ssh <pi-host> 'cat /proc/sys/kernel/random/boot_id')"
ssh <pi-host> 'sudo -n reboot' || true
deadline=$((SECONDS + 180))
until new_boot_id="$(ssh -o ConnectTimeout=5 <pi-host> 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null)" \
  && [[ "$new_boot_id" != "$old_boot_id" ]]; do
  if (( SECONDS >= deadline )); then
    echo "Pi did not come back after reboot within 180s with a new boot_id" >&2
    exit 1
  fi
  sleep 2
done
```

> [!TIP]
> If the enable step fails with `mkinitramfs: failed to determine device for /`,
> follow the repair step in
> [persistent-readonly.md](persistent-readonly.md#enable-read-only-mode),
> then rerun `readonly enable` and resume validation here before rebooting.

After reboot:

```bash
ssh <pi-host> 'bash -s' <<'EOF'
bluetooth_2_usb readonly status
sudo -n env SMOKETEST_POST_REBOOT=1 bluetooth_2_usb smoketest --verbose
findmnt -no FSTYPE,SOURCE /
findmnt /var/lib/bluetooth
findmnt /mnt/b2u-persist
cd /opt/bluetooth_2_usb
sudo -n env PYTHONPATH=src python3 - <<'PY'
from bluetooth_2_usb.ops.boot_config import boot_initramfs_target_path

try:
    path = boot_initramfs_target_path()
except Exception as exc:
    print(f"boot-initramfs unavailable: {exc}")
else:
    print(f"boot-initramfs {path}")
PY
grep '^B2U_' /etc/default/bluetooth_2_usb_readonly
EOF
```

## Pairing persistence across reboot

Before reboot:

```bash
ssh <pi-host> '
  bluetoothctl devices Paired
  sudo -n bluetooth_2_usb --list_devices --output json
'
```

Then:

1. pair the target Bluetooth keyboard or mouse
2. confirm it works on the target host
3. reboot the Pi

After reboot:

```bash
ssh <pi-host> '
  bluetoothctl devices Paired
  sudo -n bluetooth_2_usb --list_devices --output json
  sudo -n journalctl -u bluetooth_2_usb.service -n 100 --no-pager
'
```

Pass criteria:

- the paired device remains known after reboot
- reconnect works without re-pairing
- input still reaches the target host

## Hard power-loss follow-up

> [!WARNING]
> This intentionally cuts power. Run it only after read-only mode and
> persistent Bluetooth storage has already been validated.

Before cutting power:

```bash
ssh <pi-host> '
  bluetoothctl devices Paired
  systemctl is-active bluetooth_2_usb.service
'
```

Then:

1. cut power to the Pi
2. restore power
3. wait for full boot

After boot:

```bash
ssh <pi-host> '
  systemctl is-active bluetooth_2_usb.service
  bluetoothctl devices Paired
  sudo -n journalctl -u bluetooth_2_usb.service -n 100 --no-pager
'
```

Pass criteria:

- no re-pairing required
- no broken persistent mount
- no service crash on startup

## Disable read-only mode again

```bash
ssh <pi-host> 'sudo -n bluetooth_2_usb readonly disable'
old_boot_id="$(ssh <pi-host> 'cat /proc/sys/kernel/random/boot_id')"
ssh <pi-host> 'sudo -n reboot' || true
deadline=$((SECONDS + 180))
until new_boot_id="$(ssh -o ConnectTimeout=5 <pi-host> 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null)" \
  && [[ "$new_boot_id" != "$old_boot_id" ]]; do
  if (( SECONDS >= deadline )); then
    echo "Pi did not come back after reboot within 180s with a new boot_id" >&2
    exit 1
  fi
  sleep 2
done
```

> [!WARNING]
> Only run destructive read-only rollback checks after disabling read-only mode
> and rebooting, once `findmnt -no FSTYPE,SOURCE /` no longer shows `overlay`
> for the live root filesystem.

## Uninstall validation

```bash
ssh <pi-host> '
  sudo -n bluetooth_2_usb uninstall
  systemctl is-active bluetooth_2_usb.service || true
  systemctl show -P LoadState bluetooth_2_usb.service
  systemctl is-enabled var-lib-bluetooth.mount >/dev/null 2>&1 && echo mount-enabled || echo mount-disabled
  test -d /opt/bluetooth_2_usb && echo checkout-present || echo checkout-missing
'
```

Expected outcome:

- service integration is removed
- checkout remains present
- persistent mount units are disabled
- runtime env files and CLI links are removed

## What to record

For each run:

```bash
ssh <pi-host> '
  uname -a
  cat /etc/os-release
  echo SERVICE=$(systemctl is-active bluetooth_2_usb.service || true)
  echo READONLY=$(grep "^B2U_READONLY_MODE=" /etc/default/bluetooth_2_usb_readonly 2>/dev/null || echo disabled)
  sudo -n journalctl -u bluetooth_2_usb.service -n 100 --no-pager || true
'
```
