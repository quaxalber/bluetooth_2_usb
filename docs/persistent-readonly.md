# Pi Persistent Read-Only

Use this guide when you want an appliance-style Raspberry Pi setup with a
read-only root filesystem while still keeping Bluetooth pairings and other
BlueZ state on separate writable ext4 storage.

## Scope

This workflow:

- enables Raspberry Pi OS OverlayFS for the root filesystem
- keeps Bluetooth state on a separate writable ext4 filesystem
- bind-mounts that Bluetooth state to `/var/lib/bluetooth`

This workflow does not:

- create extra partitions for you automatically
- repartition the root device for you
- make Bluetooth state persistent without separate writable storage

## Prerequisites

Before enabling read-only mode:

1. install Bluetooth-2-USB and confirm normal operation first
2. identify or prepare a writable ext4 partition for Bluetooth state
3. make sure you can still recover the Pi over SSH or local console if boot
   policy needs to be reverted
4. if you run a custom kernel, keep the running kernel fully installed on the
   Pi, including `/lib/modules/$(uname -r)` and either
   `/boot/config-$(uname -r)` or `/proc/config.gz`

## Prepare the writable filesystem

Identify the target device:

```bash
lsblk -f
```

If needed, create ext4 on the real spare partition:

```bash
sudo mkfs.ext4 -L B2U_PERSIST <persist-partition>
```

> [!IMPORTANT]
> Replace `<persist-partition>` with the real ext4 partition you intend to use.
> Double-check the target with `lsblk -f` before formatting or enabling
> persistent Bluetooth state.

In principle you can also take the writable space from the same physical
device that holds the root filesystem, for example by carving out a separate
ext4 partition on that SD card or SSD. That avoids extra physical media, but
it does not reduce SD-card wear the way moving that writable state to a USB
stick or other separate storage can. It also increases the risk of
partitioning mistakes and gives you less separation during maintenance or
recovery.

## Enable persistent read-only mode

Run:

```bash
sudo /opt/bluetooth_2_usb/scripts/readonly-setup.sh --device <persist-partition>
sudo /opt/bluetooth_2_usb/scripts/readonly-enable.sh
sudo reboot
```

After reboot:

```bash
sudo env SMOKETEST_POST_REBOOT=1 /opt/bluetooth_2_usb/scripts/smoketest.sh --verbose
findmnt -no FSTYPE,SOURCE /
sudo /opt/bluetooth_2_usb/venv/bin/python - <<'PY'
from bluetooth_2_usb.ops.boot_config import boot_initramfs_target_path

try:
    path = boot_initramfs_target_path()
except Exception as exc:
    print(f"boot initramfs: unavailable ({exc})")
else:
    print(f"boot initramfs: {path}")
PY
```

If `readonly-enable.sh` fails while `overlayroot` is being installed and the
log shows `mkinitramfs: failed to determine device for /`, repair the package
state before rebooting:

```bash
sudo sed -i 's/^MODULES=dep$/MODULES=most/' /etc/initramfs-tools/initramfs.conf
sudo dpkg --configure -a
sudo /opt/bluetooth_2_usb/scripts/readonly-enable.sh
```

That failure mode has been observed on current Raspberry Pi OS releases when
`initramfs-tools` cannot infer the root device during `overlayroot` setup.

When a custom kernel image is selected in `config.txt`, `readonly-enable.sh`
does not just toggle OverlayFS. Before it finalizes read-only mode, it:

- resolves the boot initramfs filename expected for the configured kernel image
- runs `update-initramfs` for the current `uname -r`
- installs the resulting image at the firmware-visible boot path

That is why custom kernels must stay fully installed on the Pi before you run
`readonly-enable.sh`. In practice this means the running kernel release needs
its module tree under `/lib/modules/$(uname -r)` and its config available as
`/boot/config-$(uname -r)` or `/proc/config.gz`, otherwise the script aborts
instead of leaving you with a half-configured read-only boot path.

## Disable read-only mode

```bash
sudo /opt/bluetooth_2_usb/scripts/readonly-disable.sh
sudo reboot
```

## Validation

For a repeatable validation flow, including post-reboot checks and teardown,
use the `Persistent read-only validation` section in
[`cli-service-test.md`](cli-service-test.md#persistent-read-only-validation).
