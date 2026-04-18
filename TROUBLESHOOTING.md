# Troubleshooting

Start every troubleshooting pass with the two built-in diagnostics first:

```bash
sudo /opt/bluetooth_2_usb/scripts/diagnostics/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/diagnostics/debug.sh --duration 10
```

Use `smoke_test.sh` as the quick health gate and `debug.sh` as the fuller
redacted state snapshot.

For an end-to-end relay check without depending on a paired Bluetooth device,
use [docs/pi/host-relay-loopback.md](docs/pi/host-relay-loopback.md).

## The service does not start

```bash
bluetooth_2_usb --validate-env
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

If `--validate-env` reports `configfs: missing` or `udc: missing`, you are
either not on a gadget-capable Pi or the Pi has not booted with the expected
gadget configuration.

## The Pi does not appear as a USB gadget

Check the boot overlay and modules:

```bash
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/firmware/config.txt 2>/dev/null || \
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/config.txt
cat /boot/firmware/cmdline.txt 2>/dev/null || cat /boot/cmdline.txt
```

Interpretation:

- `dtoverlay=dwc2` should be present in `config.txt`
- `modules-load=` should still load `libcomposite`
- `dwc2` may be built in on newer kernels; missing a separate loadable module is
  not automatically a failure

## Specific devices are not being relayed

Check what the runtime sees:

```bash
bluetooth_2_usb -l
```

Then verify that `DEVICE_IDS` really matches the reported paths, Bluetooth MAC
addresses, or case-insensitive device-name fragments.

If the service looks healthy but the target host still does not react, also
check the physical path:

- use the OTG-capable port
- use a data cable, not a power-only cable
- on Pi Zero boards, prefer separate stable power and use only the data port
  for the host connection
- confirm the service is active with
  `systemctl is-active bluetooth_2_usb.service`

## Bluetooth pairing or scanning is flaky even though `bluetooth.service` is active

Do not treat `systemctl status bluetooth` on its own as a health check. A
running `bluetooth.service` can still leave the controller powered off or
rfkill-blocked.

Check the real controller state:

```bash
sudo bluetoothctl show
sudo btmgmt info
rfkill list
grep -H . /sys/class/rfkill/rfkill*/{soft,hard,state} 2>/dev/null
```

If the adapter is soft-blocked and the block comes back after reboot, also
inspect persisted `systemd-rfkill` state under `/var/lib/systemd/rfkill`.

If the controller itself looks healthy, switch to an interactive
`bluetoothctl` session and complete the actual bonding flow there. Common
failure modes are unanswered agent prompts or incomplete bonding handshakes.

## Persistent read-only mode does not keep Bluetooth pairings

Verify that the writable state is mounted where expected:

```bash
findmnt /var/lib/bluetooth
findmnt /mnt/b2u-persist
grep '^B2U_' /etc/default/bluetooth_2_usb_readonly
```

For the full supported flow, use
[docs/pi/persistent-readonly.md](docs/pi/persistent-readonly.md).

## SSH, ping, or DNS access to the Pi is flaky

Treat this as a separate class of problem from the Bluetooth-2-USB runtime.

Typical symptoms:

- `ssh pi-host` times out even though the Pi is probably still online
- `ping pi-host` fails but `ping pi-host.local` or a direct IPv6 link-local
  address works
- package downloads fail with DNS errors even though the Pi is otherwise online

In practice this has usually been a lab-specific network, hostname, mDNS,
link-local IPv6, DNS, or Wi-Fi power-management issue rather than a
Bluetooth-2-USB product bug.

Site-specific connectivity recovery and host-policy tuning are intentionally out
of scope for the product docs. Diagnose and fix those with your local ops
material, then return to the product checks above.
