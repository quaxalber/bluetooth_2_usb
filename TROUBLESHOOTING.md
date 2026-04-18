# Troubleshooting

Start every troubleshooting pass with the two built-in diagnostics first:

```bash
sudo /opt/bluetooth_2_usb/scripts/diagnostics/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/diagnostics/debug.sh --duration 10
```

Use `smoke_test.sh` as the quick health gate and `debug.sh` as the fuller
redacted state snapshot. The sections below are for follow-up checks that go
beyond what those two tools already collect.

For a real end-to-end relay check without depending on a paired Bluetooth
device, use the host/Pi loopback harness in
[`docs/pi/host-relay-loopback.md`](docs/pi/host-relay-loopback.md).

If the problem is workstation-to-Pi reachability itself rather than the relay
service, start with
[`docs/pi/connectivity-troubleshooting.md`](docs/pi/connectivity-troubleshooting.md)
and then use
[`docs/pi/connectivity-recovery.md`](docs/pi/connectivity-recovery.md)
for the full recovery flow.

## The service does not start

```bash
bluetooth_2_usb --validate-env
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

If `--validate-env` reports `configfs: missing` or `udc: missing`, that
usually means you are either not on a Pi gadget-capable system or the Pi has
not yet booted with the expected gadget configuration.

## The Pi does not appear as a USB gadget

Check the boot overlay and modules:

```bash
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/firmware/config.txt 2>/dev/null || \
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/config.txt
cat /boot/firmware/cmdline.txt 2>/dev/null || cat /boot/cmdline.txt
```

Interpret those checks conservatively:

- `dtoverlay=dwc2` in `config.txt` should be present.
- `modules-load=` in `cmdline.txt` should still load `libcomposite`, and may
  also include `dwc2` on kernels where `dwc2` is built as a module.
- On newer 64-bit Bookworm and aarch64 kernels, `CONFIG_USB_DWC2=y` often
  means `dwc2` is built into the kernel. In that case, the absence of a
  separate loadable `dwc2` module is normal and not itself a failure.
- Treat missing USB gadget support as the problem, not merely the absence of a
  loadable module: if `CONFIG_USB_DWC2=y` is present, built-in `dwc2` is fine;
  otherwise make sure `dtoverlay=dwc2` is set and that `dwc2` is loaded on
  kernels that require it as a module.

## Specific devices are not being relayed

Check what the runtime can actually see:

```bash
bluetooth_2_usb -l
```

Then verify that `DEVICE_IDS` really matches what the runtime reports.
Matching is based on event path, Bluetooth MAC address, or case-insensitive
device-name fragment, so stale event numbers or slightly wrong name fragments
are common operator mistakes.

If the service looks healthy but the target host still does not react, also
check the physical path:

- make sure the Pi is connected through the OTG-capable port, not a normal
  host-only USB port
- make sure the USB cable carries data, not only power
- on Pi Zero boards, prefer separate stable power and use only the data port
  for the host connection
- on Pi 4B and Pi 5, try a different USB-C cable or a different host port
- confirm the service is actually active with
  `systemctl is-active bluetooth_2_usb.service`

If you need to isolate the relay path from Bluetooth pairing state, run the
host/Pi loopback harness from
[`docs/pi/host-relay-loopback.md`](docs/pi/host-relay-loopback.md).

## Bluetooth pairing or scanning is flaky even though `bluetooth.service` is active

Do not treat `systemctl status bluetooth` on its own as a health check. A
running `bluetooth.service` can still leave the controller powered off or
rfkill-blocked.

Check the real controller state first:

```bash
sudo bluetoothctl show
sudo btmgmt info
rfkill list
grep -H . /sys/class/rfkill/rfkill*/{soft,hard,state} 2>/dev/null
```

If `smoke_test.sh` or `debug.sh` already show the adapter as healthy, switch
to an interactive `bluetoothctl` session and complete the actual bonding flow
there. The common failure mode is not missing BlueZ, but an unanswered pairing
prompt or a bonding handshake that never completes.

If the block comes back specifically after a reboot, also inspect the
persisted `systemd-rfkill` state under `/var/lib/systemd/rfkill`. A saved
Bluetooth state of `1` there can re-apply the soft block on later boots even
when the runtime and BlueZ are otherwise healthy.

If you already know the adapter is soft-blocked, clear that first:

```bash
sudo sh -c 'echo 0 > /sys/class/rfkill/rfkill0/soft'
```

If you need that fix to survive reboot, also clear the persisted Bluetooth
state files:

```bash
sudo sh -c 'for f in /var/lib/systemd/rfkill/*:bluetooth; do [ -e "$f" ] || continue; printf "0\n" > "$f"; done'
sudo rfkill unblock bluetooth
sudo systemctl restart bluetooth
```

Then work interactively:

```bash
sudo bluetoothctl
```

Inside `bluetoothctl`, watch for agent prompts and answer them explicitly. Some
BLE devices connect briefly, then drop again unless the authorization prompt is
accepted in time. Repeated short `Connected: yes` / `Connected: no`
transitions without a durable bonded state usually mean the pairing handshake
is not completing, not that the device is already usable.

For stubborn bonding or connect/disconnect flip-flops, use a conservative
reset flow:

1. Start an interactive session:

```bash
sudo bluetoothctl
```

2. Reset the adapter state:

```text
power off
power on
```

3. Clear the stale device state and pair again:

```text
block A1:B2:C3:D4:E5:F6
remove A1:B2:C3:D4:E5:F6
scan on
trust A1:B2:C3:D4:E5:F6
pair A1:B2:C3:D4:E5:F6
connect A1:B2:C3:D4:E5:F6
```

`remove` clears the stored BlueZ device record for that device and is often
the right next step when you have a half-broken bonding state. This is a
recovery flow for hard failures, not the normal first pairing attempt.

If the BlueZ device cache itself looks stale, you can clear it more directly.
This is destructive for saved pairings:

```bash
sudo systemctl stop bluetooth
sudo find /var/lib/bluetooth -maxdepth 2 -type d
```

Remove only the affected device directory under the adapter first, then start
Bluetooth again:

```bash
sudo rm -rf '/var/lib/bluetooth/AA:BB:CC:DD:EE:FF/A1:B2:C3:D4:E5:F6'
sudo systemctl start bluetooth
```

Only remove larger parts of `/var/lib/bluetooth` if targeted cleanup does not
help and you are prepared to pair devices again from scratch.

## Persistent read-only mode does not keep Bluetooth pairings

Verify that the writable state is actually mounted where expected:

```bash
findmnt /var/lib/bluetooth
findmnt /mnt/b2u-persist
grep '^B2U_' /etc/default/bluetooth_2_usb_readonly
```

## SSH, ping, or DNS access to the Pi is flaky

If `ssh pi-host` times out, `ping pi-host` is misleading, or the Pi only works
through an IPv6 link-local address with `%interface`, do not keep debugging
the service blindly.

This has repeatedly turned out to be a workstation-to-Pi connectivity problem
rather than a `bluetooth_2_usb` runtime bug.

Start with the short classification guide in
[`docs/pi/connectivity-troubleshooting.md`](docs/pi/connectivity-troubleshooting.md),
then run the full recovery flow in
[`docs/pi/connectivity-recovery.md`](docs/pi/connectivity-recovery.md).
