# Pi Remote-Wakeup Kernel

Use this guide when you need a Raspberry Pi USB HID gadget that can wake a
sleeping or suspended host by sending keyboard input.

This is an advanced workflow. It relies on a custom Raspberry Pi kernel and is
not part of the stock Bluetooth-2-USB install path.

## Scope and warnings

- this installs a custom Raspberry Pi kernel
- rollback should be prepared before the first reboot
- host suspend and remote wake behavior remain platform-specific even with the
  patch
- this guide documents only the setups that have been validated for this project

## Tested setups

- Raspberry Pi 4 Model B Rev 1.4:
  patched `rpi-6.12.y` kernel `6.12.81-b2u-wake+`, `/boot/config-$(uname -r)`
  installed, keyboard-only `wakeup_on_write`, and end-to-end wake from host
  suspend confirmed through normal Bluetooth-2-USB keyboard input
- Raspberry Pi Zero W:
  patched `rpi-6.12.y` kernel `6.12.81-b2u-wake`, validated ARM32 build and
  boot path, keyboard-only `wakeup_on_write`, and end-to-end wake from host
  suspend confirmed through normal Bluetooth-2-USB keyboard input

## Technical background

The wake path needs both of the following:

1. a patched Raspberry Pi kernel that adds remote wakeup support to the `dwc2`
   gadget driver and a `wakeup_on_write` configfs attribute to the HID gadget
   function
2. a Bluetooth-2-USB runtime that enables `wakeup_on_write=1` for the keyboard
   HID function when that attribute exists

Without the kernel patch, the runtime cannot wake suspended hosts.

## Patch source

- Raspberry Pi Linux issue `#3977`:
  https://github.com/raspberrypi/linux/issues/3977
- PiKVM reference patch:
  https://github.com/pikvm/packages/blob/6d1fe298d7ad13a82cf9c6d3645866a443cde8f0/packages/linux-rpi-pikvm/1001-pikvm-hid-remote-wakeup-support.patch

## Build dependencies

General build dependencies:

```bash
sudo apt install bc bison flex libssl-dev make libc6-dev libncurses5-dev
```

64-bit cross toolchain for Pi 4B:

```bash
sudo apt install crossbuild-essential-arm64
```

32-bit cross toolchain for Pi Zero W:

```bash
sudo apt install crossbuild-essential-armhf
```

If the ARM32 GCC toolchain is unavailable, the Zero W path can also be built
with a complete LLVM toolchain. That fallback is validated for this project but
is still a fallback, not the preferred default.

## Prepare a separate kernel checkout

```bash
mkdir -p ~/src
cd ~/src
git clone --depth=1 --branch rpi-6.12.y https://github.com/raspberrypi/linux.git rpi-linux-wakeup
cd rpi-linux-wakeup
git switch -c b2u/rpi-6.12.y-remote-wakeup
```

Apply the patch:

```bash
curl -L \
  https://raw.githubusercontent.com/pikvm/packages/6d1fe298d7ad13a82cf9c6d3645866a443cde8f0/packages/linux-rpi-pikvm/1001-pikvm-hid-remote-wakeup-support.patch \
  -o 1001-pikvm-hid-remote-wakeup-support.patch
patch -p1 < 1001-pikvm-hid-remote-wakeup-support.patch
```

Use a fixed local version suffix:

```text
-b2u-wake
```

## Validated build paths

### Raspberry Pi 4B

```bash
cd ~/src/rpi-linux-wakeup
export JOBS="$(nproc)"
export KERNEL=kernel8
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- bcm2711_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- Image modules dtbs
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- kernelrelease
```

### Raspberry Pi Zero W

Preferred GCC path:

```bash
cd ~/src/rpi-linux-wakeup
export JOBS="$(nproc)"
export KERNEL=kernel
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- bcmrpi_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- LOCALVERSION= zImage modules dtbs
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- LOCALVERSION= kernelrelease
```

Validated LLVM fallback:

```bash
cd ~/src/rpi-linux-wakeup
export JOBS="$(nproc)"
export KERNEL=kernel
make O=out/pi0w LLVM=1 ARCH=arm bcmrpi_defconfig
scripts/config --file out/pi0w/.config --set-str LOCALVERSION "-b2u-wake"
scripts/config --file out/pi0w/.config --disable BCM2835_FAST_MEMCPY
make O=out/pi0w LLVM=1 ARCH=arm syncconfig
make -j"${JOBS}" O=out/pi0w LLVM=1 ARCH=arm LOCALVERSION= zImage modules dtbs
make O=out/pi0w LLVM=1 ARCH=arm LOCALVERSION= kernelrelease
cp out/pi0w/.config "out/pi0w/config-$(make O=out/pi0w LLVM=1 ARCH=arm LOCALVERSION= kernelrelease)"
```

Notes for the LLVM fallback:

- disabling `CONFIG_BCM2835_FAST_MEMCPY` avoids the tested ARM32 LLVM build
  failure on Raspberry Pi specific assembly
- keep `-b2u-wake` in `.config`
- pass `LOCALVERSION=` on the build and `kernelrelease` commands so the final
  release string stays `...-b2u-wake` instead of `...-b2u-wake+`

## Deploy to the Pi

Copy the built kernel image, modules, DTBs, overlays, and matching
`config-<kernelrelease>` to the Pi. Then set the custom kernel image in
`config.txt`.

Typical image names:

- Pi 4B: `kernel8-b2u-wake.img`
- Pi Zero W: `kernel-b2u-wake.img`

With `auto_initramfs=1`, Raspberry Pi firmware derives the boot initramfs name
from the kernel image name. That means these image names map to these boot
initramfs targets:

- Pi 4B: `kernel8-b2u-wake.img` -> `initramfs8-b2u-wake`
- Pi Zero W: `kernel-b2u-wake.img` -> `initramfs-b2u-wake`

When you later enable persistent read-only mode, `readonly-enable.sh` rebuilds
the initramfs for the running kernel and installs the matching boot initramfs
file automatically.

Keep the stock kernel entry available so rollback is trivial.

## Verification

After reboot, confirm:

1. the custom kernel is running

```bash
uname -r
```

2. the wakeup attribute exists

```bash
find /sys/kernel/config/usb_gadget -path '*/functions/hid.*/*wakeup_on_write' -print
```

3. the gadget still advertises remote wakeup and the keyboard function has
   `wakeup_on_write=1`

4. the normal Bluetooth-2-USB checks still pass

```bash
sudo /opt/bluetooth_2_usb/scripts/smoketest.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
```

5. a real host suspend and wake test succeeds through normal keyboard input

If the first post-reboot smoketest fails on Bluetooth power, also inspect
persisted `systemd-rfkill` Bluetooth soft-block state under
`/var/lib/systemd/rfkill`.

## Rollback

Rollback should be simple:

- keep the stock kernel image and config in place
- restore `config.txt` to the stock kernel entry
- reboot

If the custom kernel fails to boot cleanly, use console or the boot medium from
another machine to restore the stock kernel selection.

## Known limitations

- this is still a custom-kernel workflow, not a stock-project feature
- host suspend and wake behavior depend on the host platform as well as the Pi
- only the validated Pi 4B and Pi Zero W paths are documented here on purpose
