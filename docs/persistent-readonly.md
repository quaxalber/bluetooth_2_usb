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

## Prepare the writable filesystem

Identify the target device:

```bash
lsblk -f
```

If needed, create ext4 on the real spare partition:

```bash
sudo mkfs.ext4 -L B2U_PERSIST /dev/mmcblk0p3
```

> [!IMPORTANT]
> Replace `/dev/mmcblk0p3` with the real ext4 partition you intend to use.
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
sudo /opt/bluetooth_2_usb/scripts/readonly-setup.sh --device /dev/mmcblk0p3
sudo /opt/bluetooth_2_usb/scripts/readonly-enable.sh
sudo reboot
```

After reboot:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoketest.sh --verbose
```

## Disable read-only mode

```bash
sudo /opt/bluetooth_2_usb/scripts/readonly-disable.sh
sudo reboot
```

## Validation

For a repeatable validation flow, including post-reboot checks and teardown,
use the `Persistent read-only validation` section in
[`cli-service-test.md`](cli-service-test.md#persistent-read-only-validation).
