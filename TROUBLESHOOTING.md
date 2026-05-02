# Troubleshooting

Most troubleshooting sessions should start with the two built-in diagnostics:

```bash
sudo bluetooth_2_usb smoketest --verbose
sudo bluetooth_2_usb debug --duration 10
```

The `smoketest` is the quick health gate. `debug` gives you the fuller redacted
snapshot when you need to understand what the runtime actually sees.

If you want an end-to-end relay check without depending on a paired Bluetooth
device, use the loopback inject/capture validation in
[docs/host-relay-loopback.md](docs/host-relay-loopback.md).

## The service does not start

Symptom: `bluetooth_2_usb.service` fails to start or exits immediately.

Check:

```bash
bluetooth_2_usb --validate-env
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

Interpretation:
- if `--validate-env` reports `configfs: missing` or `udc: missing`, you are
  either not on a gadget-capable Pi or the Pi has not booted with the expected
  gadget configuration
- if the environment looks fine, the journal usually shows whether the problem
  is configuration, permissions, or an unexpected runtime failure

## The Pi does not appear as a USB gadget

Symptom: the target host does not see a USB keyboard or mouse from the Pi.

Check:

```bash
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/firmware/config.txt 2>/dev/null || \
grep -nE '^\[all\]|dtoverlay=dwc2.*' /boot/config.txt
cat /boot/firmware/cmdline.txt 2>/dev/null || cat /boot/cmdline.txt
```

Interpretation:
- `dtoverlay=dwc2` should still be present in `config.txt`
- `modules-load=` should still load `libcomposite`
- `dwc2` may be built into newer kernels, so the absence of a separate module
  is not automatically a failure

Also check the physical path:
- use the OTG-capable port
- use a data cable, not a power-only cable
- on Pi Zero boards, prefer separate stable power and use the data port for the
  host connection

## Specific devices are not being relayed

Symptom: the service is up, but the keyboard or mouse you care about is not
being relayed.

Check:

```bash
bluetooth_2_usb -l
systemctl is-active bluetooth_2_usb.service
```

Interpretation:
- verify that your `B2U_DEVICE_IDS` or `--device_ids` values really match the
  paths, Bluetooth MACs, or case-insensitive name fragments that the runtime
  reports
- if the service looks healthy but the host still does not react, confirm the
  physical OTG/data-cable path before assuming the problem is device matching

For a pure relay-path check, use the loopback inject/capture validation in
[docs/host-relay-loopback.md](docs/host-relay-loopback.md).

## Bluetooth pairing or scanning is flaky even though `bluetooth.service` is active

Symptom: BlueZ is running, but the controller still looks unavailable,
unpowered, or unreliable.

Check:

```bash
sudo bluetoothctl show
sudo btmgmt info
rfkill list
grep -H . /sys/class/rfkill/rfkill*/{soft,hard,state} 2>/dev/null
```

Interpretation:
- a running `bluetooth.service` alone is not enough; the controller can still
  be powered off or rfkill-blocked
- if the adapter is soft-blocked and the block returns after reboot, inspect
  persisted `systemd-rfkill` state under `/var/lib/systemd/rfkill`
- if the controller looks healthy, switch to an interactive `bluetoothctl`
  session and complete the actual bonding flow there

## Persistent read-only mode does not keep Bluetooth pairings

Symptom: pairings disappear after reboot or read-only mode does not behave as
expected.

Check:

```bash
findmnt /var/lib/bluetooth
findmnt /mnt/b2u-persist
grep '^B2U_' /etc/default/bluetooth_2_usb_readonly
```

Interpretation:
- the writable Bluetooth state must be mounted where the read-only workflow
  expects it
- if the paths or config do not match, the system may be booting read-only
  without the persistent BlueZ state mounted correctly

For the full setup and validation flow, use
[docs/persistent-readonly.md](docs/persistent-readonly.md).

## SSH, ping, or DNS access to the Pi is flaky

Symptom: the Pi looks online enough to suspect it is reachable, but `ssh`,
`ping`, or package downloads behave inconsistently.

Typical examples:
- `ssh <pi-host>` times out even though the Pi is probably still running
- `ping <pi-host>` fails while `ping <pi-host>.local` or a direct IPv6 link-local
  address works
- package downloads fail with DNS errors even though the Pi is otherwise online

Interpretation:
- this is usually a separate class of problem from the Bluetooth-2-USB runtime
- in practice these failures are often tied to local hostname resolution, mDNS,
  link-local IPv6, DNS, or Wi-Fi power-management policy rather than a product
  bug

Site-specific connectivity recovery and host-policy tuning are intentionally not
part of the product docs. Resolve the local access issue first, then return to
the product checks above.
