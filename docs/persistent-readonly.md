# Pi Read-Only Mode

Use this guide when you want an appliance-style Raspberry Pi setup with a
read-only root filesystem while still keeping Bluetooth pairings and other
BlueZ state on separate persistent ext4 storage.

## Scope

This workflow:

- enables Raspberry Pi OS OverlayFS for the root filesystem
- keeps Bluetooth state on a separate persistent ext4 filesystem
- bind-mounts that Bluetooth state to `/var/lib/bluetooth`

This workflow does not:

- create extra partitions for you automatically
- repartition the root device for you
- keep Bluetooth state across reboot without separate persistent storage

## Prerequisites

Before enabling read-only mode:

1. install Bluetooth-2-USB and confirm normal operation first
2. identify or prepare a persistent ext4 partition for Bluetooth state
3. make sure you can still recover the Pi over SSH or local console if boot
   policy needs to be reverted
4. if you run a custom kernel, keep the running kernel fully installed on the
   Pi, including `/lib/modules/$(uname -r)` and either
   `/boot/config-$(uname -r)` or `/proc/config.gz`

## Prepare the persistent filesystem

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
> persistent Bluetooth state storage.

> [!WARNING]
> You can take the persistent space from the same physical device that holds the
> root filesystem, for example by carving out a separate ext4 partition on that
> SD card or SSD. That avoids extra physical media, but it does not reduce
> SD-card wear the way moving that persistent state to a USB stick or other
> separate storage can. It also increases the risk of partitioning mistakes and
> gives you less separation during maintenance or recovery.

## Enable read-only mode

The setup step installs the OverlayFS and initramfs prerequisites, configures
initramfs-tools for read-only operation, and prepares persistent Bluetooth
state storage.

Run:

```bash
sudo bluetooth_2_usb readonly setup --device <persist-partition>
sudo bluetooth_2_usb readonly enable
sudo reboot
```

After reboot:

```bash
bluetooth_2_usb readonly status
sudo env SMOKETEST_POST_REBOOT=1 bluetooth_2_usb smoketest --verbose
findmnt -no FSTYPE,SOURCE /
cd /opt/bluetooth_2_usb
sudo env PYTHONPATH=src python3 - <<'PY'
from bluetooth_2_usb.ops.boot_config import boot_initramfs_target_path

try:
    path = boot_initramfs_target_path()
except Exception as exc:
    print(f"boot initramfs: unavailable ({exc})")
else:
    print(f"boot initramfs: {path}")
PY
```

After any failed `readonly enable`, inspect the current state before rebooting:

```bash
bluetooth_2_usb readonly status
```

If you explicitly want to back out the requested OverlayFS state, disable it
before rebooting:

```bash
sudo bluetooth_2_usb readonly disable
```

> [!IMPORTANT]
> Custom kernels must stay fully installed on the Pi before you run
> `readonly enable`.

When a custom kernel image is selected in `config.txt`, `readonly enable`
does not just toggle OverlayFS. Before it finalizes read-only mode, it:

- resolves the boot initramfs filename expected for the configured kernel image
- runs `update-initramfs` for the current `uname -r`
- installs the resulting image at the firmware-visible boot path

In practice this means the running kernel release needs its module tree under
`/lib/modules/$(uname -r)` and its config available as
`/boot/config-$(uname -r)` or `/proc/config.gz`, otherwise the command aborts
instead of leaving you with a half-configured read-only boot path.

## Arguments

| Command | Argument | Meaning |
| --- | --- | --- |
| `readonly setup` | `--device DEVICE` | Persistent ext4 storage block device to mount for Bluetooth state. Required. |
| `readonly status` | n/a | This command has no command-specific arguments. |
| `readonly enable` | n/a | This command has no command-specific arguments. |
| `readonly disable` | n/a | This command has no command-specific arguments. |
| `readonly migrate` | n/a | This command has no command-specific arguments. |

## Disable read-only mode

```bash
bluetooth_2_usb readonly status
sudo bluetooth_2_usb readonly disable
sudo reboot
```

`readonly disable` leaves Bluetooth state on the persistent storage mount. If
you want to move Bluetooth state back to the root filesystem, reboot first so
the root filesystem is writable, then run:

```bash
sudo bluetooth_2_usb readonly migrate
```

`readonly migrate` refuses to run while the root filesystem is still
overlay-backed, because writes to rootfs would be discarded on the next reboot.
When migration succeeds, the managed persistent-state mounts are disabled and
unmounted. The old Bluetooth state on the persistent device is preserved; wipe
or reformat that device manually only if you intentionally want to reuse it for
something else.

## Validation

For a repeatable validation flow, including post-reboot checks and teardown,
use the `Read-only validation` section in
[`cli-service-test.md`](cli-service-test.md#read-only-validation).
