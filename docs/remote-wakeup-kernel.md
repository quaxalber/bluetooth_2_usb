# Pi Remote-Wakeup Kernel

Use this guide when you need a Raspberry Pi USB HID gadget that can wake a
sleeping or suspended host by sending keyboard input.

> [!WARNING]
> This is an advanced workflow. It installs and runs a custom Raspberry Pi
> kernel and is not part of the stock Bluetooth-2-USB install path.

## Scope and warnings

- this installs a custom Raspberry Pi kernel
- rollback should be prepared before the first reboot
- host suspend and remote wake behavior remain platform-specific even with the
  patch
- the tested setups below are validated for this project
- the additional build paths below are provided for unvalidated targets that
  follow the same custom-kernel and read-only flow

## Tested setups

- Raspberry Pi 4 Model B Rev 1.4:
  patched `rpi-6.12.y` kernel `6.12.81-b2u-wake`, `/boot/config-$(uname -r)`
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

> [!IMPORTANT]
> Without the kernel patch, the runtime cannot wake suspended hosts.

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

64-bit cross toolchain for Pi 4B, Pi 5, and Zero 2 W:

```bash
sudo apt install crossbuild-essential-arm64
```

32-bit cross toolchain for Pi Zero W, Pi 4B 32-bit, and Zero 2 W 32-bit:

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

## Target matrix

Use this matrix as the source of truth for board-specific build targets, custom
kernel image names, and the boot initramfs name Raspberry Pi firmware expects
when `auto_initramfs=1` is enabled.

| Target | Status | Build target | Expected image | Boot initramfs target | Notes |
| --- | --- | --- | --- | --- | --- |
| Raspberry Pi 4B | validated | `ARCH=arm64`, `bcm2711_defconfig`, `KERNEL=kernel8`, `CROSS_COMPILE=aarch64-linux-gnu-` | `kernel8-b2u-wake.img` | `initramfs8-b2u-wake` | Tested on Raspberry Pi 4 Model B Rev 1.4 |
| Raspberry Pi Zero W | validated | `ARCH=arm`, `bcmrpi_defconfig`, `KERNEL=kernel`, `CROSS_COMPILE=arm-linux-gnueabihf-` | `kernel-b2u-wake.img` | `initramfs-b2u-wake` | GCC path validated; LLVM fallback also validated |
| Raspberry Pi 5 | unvalidated | `ARCH=arm64`, `bcm2712_defconfig`, `KERNEL=kernel_2712`, `CROSS_COMPILE=aarch64-linux-gnu-` | `kernel_2712-b2u-wake.img` | `initramfs_2712-b2u-wake` | USB-C gadget path shares the board's USB-C connectivity |
| Raspberry Pi 4B 32-bit | unvalidated | `ARCH=arm`, `bcm2711_defconfig`, `KERNEL=kernel7l`, `CROSS_COMPILE=arm-linux-gnueabihf-` | `kernel7l-b2u-wake.img` | `initramfs7l-b2u-wake` | Use only for 32-bit Pi OS on Pi 4 |
| Raspberry Pi Zero 2 W 64-bit | unvalidated | `ARCH=arm64`, `bcm2711_defconfig`, `KERNEL=kernel8`, `CROSS_COMPILE=aarch64-linux-gnu-` | `kernel8-b2u-wake.img` | `initramfs8-b2u-wake` | Shares the Pi 4B 64-bit image/initramfs naming |
| Raspberry Pi Zero 2 W 32-bit | unvalidated | `ARCH=arm`, `bcm2709_defconfig`, `KERNEL=kernel7`, `CROSS_COMPILE=arm-linux-gnueabihf-` | `kernel7-b2u-wake.img` | `initramfs7-b2u-wake` | 32-bit only |

## Validated build paths

### Raspberry Pi 4B

```bash
cd ~/src/rpi-linux-wakeup
export JOBS="$(nproc)"
export KERNEL=kernel8
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- bcm2711_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= Image modules dtbs
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= kernelrelease
```

Pass `LOCALVERSION=` on the build and `kernelrelease` commands so the final
release string stays `...-b2u-wake` instead of `...-b2u-wake+`.

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

## Additional unvalidated targets

> [!WARNING]
> These build paths are unvalidated for this project. They are included so you
> can build and deploy the matching custom kernel and let
> `bluetooth_2_usb readonly enable` install the corresponding boot initramfs
> automatically when you later enable read-only mode. Use the target
> matrix above for the expected image and initramfs filenames.

### Raspberry Pi 5

```bash
cd ~/src/rpi-linux-wakeup
export JOBS="$(nproc)"
export KERNEL=kernel_2712
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- bcm2712_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= Image modules dtbs
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= kernelrelease
```

### Raspberry Pi 4B 32-bit

```bash
cd ~/src/rpi-linux-wakeup
export JOBS="$(nproc)"
export KERNEL=kernel7l
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- bcm2711_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- LOCALVERSION= zImage modules dtbs
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- LOCALVERSION= kernelrelease
```

### Raspberry Pi Zero 2 W 64-bit

```bash
cd ~/src/rpi-linux-wakeup
export JOBS="$(nproc)"
export KERNEL=kernel8
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- bcm2711_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= Image modules dtbs
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION= kernelrelease
```

### Raspberry Pi Zero 2 W 32-bit

```bash
cd ~/src/rpi-linux-wakeup
export JOBS="$(nproc)"
export KERNEL=kernel7
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- bcm2709_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- LOCALVERSION= zImage modules dtbs
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- LOCALVERSION= kernelrelease
```

## Deploy to the Pi

Copy the built kernel image, modules, DTBs, overlays, and matching
`config-<kernelrelease>` to the Pi. Then set the custom kernel image in
`config.txt` using the image name from the target matrix above.

With `auto_initramfs=1`, Raspberry Pi firmware derives the boot initramfs name
from the kernel image name. Use the matching boot initramfs target from the
same matrix when checking or troubleshooting boot artifacts.

> [!IMPORTANT]
> Do not treat `config-<kernelrelease>` or the matching module tree as optional
> when you plan to enable read-only mode with a custom kernel.

When you later enable read-only mode,
`bluetooth_2_usb readonly enable` ensures a bootable initramfs exists for the
running kernel and installs or reuses the matching boot initramfs file
automatically. That path depends on the running kernel being fully installed on
the Pi:

- install `/lib/modules/<kernelrelease>`
- install `/boot/config-<kernelrelease>` or otherwise keep `/proc/config.gz`
  available
- keep the custom kernel image selected in `config.txt` consistent with the
  running release

If those artifacts are missing, `bluetooth_2_usb readonly enable` aborts
instead of trying to guess a bootable initramfs layout from documentation alone.

> [!IMPORTANT]
> Keep the stock kernel entry available so rollback is trivial.

## Verification

After reboot, confirm:

1. the custom kernel is running

```bash
uname -r
```

2. the wakeup attribute exists

```bash
sudo -n find /sys/kernel/config/usb_gadget -path '*/functions/hid.*/*wakeup_on_write' -print
```

3. the gadget still advertises remote wakeup and the keyboard function has
   `wakeup_on_write=1`

```bash
sudo -n grep -H . /sys/kernel/config/usb_gadget/*/functions/hid.*/wakeup_on_write
```

4. the normal Bluetooth-2-USB checks still pass

```bash
sudo bluetooth_2_usb smoketest --verbose
sudo bluetooth_2_usb debug --duration 10
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

> [!WARNING]
> If the custom kernel fails to boot cleanly, use console or the boot medium
> from another machine to restore the stock kernel selection.

## Known limitations

- this is still a custom-kernel workflow, not a stock-project feature
- host suspend and wake behavior depend on the host platform as well as the Pi
- Pi 5, Pi 4B 32-bit, and Zero 2 W 32/64-bit are unvalidated build paths
