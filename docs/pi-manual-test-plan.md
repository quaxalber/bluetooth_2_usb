# Pi Manual Test Plan

Use this checklist for the manual follow-up validation that still matters on
real hardware after the script-level checks have passed.

## 1. Baseline managed install

Purpose:

- confirm the supported deployment model works end to end

Steps:

```bash
sudo apt update
sudo apt install -y git
sudo git clone https://github.com/quaxalber/bluetooth_2_usb.git /opt/bluetooth_2_usb
sudo /opt/bluetooth_2_usb/scripts/install.sh
sudo reboot
```

After reboot:

```bash
systemctl is-active bluetooth_2_usb.service
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
```

Pass criteria:

- service is active
- smoke test passes
- debug report is coherent and redacted

## 2. Basic relay behavior

Purpose:

- confirm that Bluetooth input reaches the target host

Steps:

- pair the target Bluetooth keyboard or mouse
- connect the Pi to the target host over the OTG-capable port
- verify normal typing and pointer movement
- verify the interrupt shortcut if configured

Pass criteria:

- input reaches the target host reliably
- no unexpected local input leakage when devices are grabbed

## 3. Re-apply install on an existing checkout

Purpose:

- confirm the supported update model stays idempotent

Steps:

```bash
sudo git -C /opt/bluetooth_2_usb pull --ff-only
sudo /opt/bluetooth_2_usb/scripts/install.sh
```

After reboot if boot settings changed:

```bash
systemctl is-active bluetooth_2_usb.service
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

Pass criteria:

- service still starts normally
- smoke test still passes

## 4. Persistent read-only mode

Purpose:

- confirm the persistent appliance-style mode works with real writable storage

Identify the target partition:

```bash
lsblk -f
```

If needed, create ext4 on the real spare partition. Double-check the target
before formatting it:

```bash
sudo mkfs.ext4 -L B2U_PERSIST /dev/YOUR-PARTITION
```

Prepare and enable persistent read-only mode:

```bash
sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/YOUR-PARTITION
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh
sudo reboot
```

After reboot:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
findmnt /var/lib/bluetooth
findmnt /mnt/b2u-persist
cat /etc/default/bluetooth_2_usb_readonly
```

Pass criteria:

- `/mnt/b2u-persist` is mounted from the intended ext4 storage
- `/var/lib/bluetooth` is a bind mount from that persistent location
- `bluetooth_2_usb.service` still starts normally

## 5. Pairing persistence across reboot

Purpose:

- confirm the real value of persistent read-only mode

Before reboot:

```bash
bluetoothctl devices Paired
sudo /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --list_devices --output json
```

Then:

- pair the target Bluetooth keyboard or mouse
- confirm it works on the target host
- reboot the Pi

After reboot:

```bash
bluetoothctl devices Paired
sudo /opt/bluetooth_2_usb/venv/bin/python -m bluetooth_2_usb --list_devices --output json
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

Pass criteria:

- the paired device remains known after reboot
- reconnect works without re-pairing
- input still reaches the target host

## 6. Hard power-loss follow-up

Purpose:

- confirm the persistent setup survives an appliance-style interruption

Before cutting power:

```bash
bluetoothctl devices Paired
systemctl is-active bluetooth_2_usb.service
```

Then:

- cut power to the Pi
- restore power
- wait for full boot

After boot:

```bash
systemctl is-active bluetooth_2_usb.service
bluetoothctl devices Paired
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

Pass criteria:

- no re-pairing required
- no broken persistent mount
- no service crash on startup

## 7. Long-running Wi-Fi / SSH stability

Purpose:

- confirm the device remains reachable during normal operation

Run these periodically from your workstation. Replace `<pi-host-or-ip>` with
the actual hostname or IP of the Pi under test:

```bash
ping -c 5 <pi-host-or-ip>
ssh -4 <pi-host-or-ip> 'hostname'
```

Pass criteria:

- no unexplained SSH timeouts during normal runtime
- no loss of reachability while the service is active

## 8. What to record for each manual run

Collect this block and paste it into your notes for each run:

```bash
uname -a
cat /etc/os-release
echo READONLY=$(grep '^B2U_READONLY_MODE=' /etc/default/bluetooth_2_usb_readonly 2>/dev/null || echo disabled)
echo SERVICE=$(systemctl is-active bluetooth_2_usb.service || true)
systemctl status bluetooth_2_usb.service --no-pager || true
journalctl -u bluetooth_2_usb.service -n 100 --no-pager || true
```
