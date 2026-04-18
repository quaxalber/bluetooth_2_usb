# Pi Boot Optimization

Use this guide when the Pi is already provisioned and no longer needs
`cloud-init` on every boot.

The optimization flow can:

- trim boot work that is not needed for `bluetooth_2_usb`
- freeze the current DHCP IPv4 settings as a static `NetworkManager` profile
- persist generated `netplan-*.nmconnection` profiles into
  `/etc/NetworkManager/system-connections/`
- disable generated `/etc/netplan/90-NM-*.yaml` overrides
- rollback the captured host state later

On a tested Pi Zero W, this removed repeated `NetworkManager` reloads during
boot and cut userspace boot time by roughly 35 seconds.

## Preconditions

- the Pi is already reachable over SSH
- the Pi user has passwordless sudo
- the system is already provisioned and does not need `cloud-init` to keep
  shaping network config on future boots

## 1. Record the current baseline

```bash
ssh pi-host '
  cd /opt/bluetooth_2_usb &&
  sudo -n git -c safe.directory=/opt/bluetooth_2_usb rev-parse --abbrev-ref HEAD &&
  sudo -n git -c safe.directory=/opt/bluetooth_2_usb status --short &&
  sudo -n /opt/bluetooth_2_usb/scripts/diagnostics/smoke_test.sh --verbose &&
  systemd-analyze time &&
  systemd-analyze blame | head -n 20 &&
  systemd-analyze critical-chain bluetooth_2_usb.service
'
```

## 2. Preview the planned changes

```bash
ssh pi-host '
  sudo -n /opt/bluetooth_2_usb/scripts/maintenance/optimize_pi_boot.sh --dry-run --static-ip auto
'
```

## 3. Apply the optimization

Freeze the current DHCP lease as a static profile:

```bash
ssh pi-host '
  sudo -n /opt/bluetooth_2_usb/scripts/maintenance/optimize_pi_boot.sh --static-ip auto
' || true
until ssh -o ConnectTimeout=5 pi-host 'true' 2>/dev/null; do sleep 2; done
```

Or use explicit static IPv4 settings:

```bash
ssh pi-host '
  sudo -n /opt/bluetooth_2_usb/scripts/maintenance/optimize_pi_boot.sh \
    --static-ip 192.168.2.215/24 \
    --gateway 192.168.2.1 \
    --dns 1.1.1.1,9.9.9.9,192.168.2.1
'
```

## 4. Verify after reboot

```bash
ssh pi-host '
  systemctl is-active bluetooth.service
  systemctl is-active bluetooth_2_usb.service
  sudo -n /opt/bluetooth_2_usb/scripts/diagnostics/smoke_test.sh --verbose
  nmcli -g NAME,UUID,TYPE,FILENAME connection show
  nmcli -g ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns connection show "$(nmcli --get-values GENERAL.CONNECTION device show wlan0 | head -n 1)"
  sudo -n ls -l /etc/netplan /etc/NetworkManager/system-connections
  systemd-analyze time
  systemd-analyze blame | head -n 20
  systemd-analyze critical-chain bluetooth_2_usb.service
'
```

Explicitly test the shorter service stop timeout:

```bash
ssh pi-host '
  sudo -n systemctl restart bluetooth_2_usb.service
  sudo -n journalctl -u bluetooth_2_usb.service -n 50 --no-pager
'
```

## 5. Rollback if needed

```bash
ssh pi-host '
  sudo -n /opt/bluetooth_2_usb/scripts/maintenance/optimize_pi_boot.sh --rollback
' || true
until ssh -o ConnectTimeout=5 pi-host 'true' 2>/dev/null; do sleep 2; done
```

## 6. Return the checkout to `main`

If you optimized a test branch and want to leave the Pi on the normal repo
state afterwards:

```bash
ssh pi-host '
  cd /opt/bluetooth_2_usb &&
  sudo -n git -c safe.directory=/opt/bluetooth_2_usb checkout main &&
  sudo -n git -c safe.directory=/opt/bluetooth_2_usb pull --ff-only origin main &&
  sudo -n /opt/bluetooth_2_usb/scripts/install.sh &&
  sudo -n /opt/bluetooth_2_usb/scripts/diagnostics/smoke_test.sh --verbose
'
```
