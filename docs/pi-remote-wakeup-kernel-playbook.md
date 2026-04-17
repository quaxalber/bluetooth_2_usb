# Pi Remote-Wakeup Kernel Playbook

Use this playbook when you need a Raspberry Pi USB HID gadget that can wake a
sleeping or suspended host by sending keyboard input.

This is not supported by the stock Raspberry Pi kernel used by Bluetooth-2-USB.
It requires a patched Raspberry Pi Linux kernel plus the existing Bluetooth-2-USB
gadget runtime.

## Scope and warnings

- this is an advanced workflow
- the stock Raspberry Pi kernel does not currently provide the required wake path
- the workflow patches and installs a custom kernel
- rollback must be prepared before the first reboot
- host suspend and remote wake behavior remain platform-specific even with the patch

This playbook covers:

- Raspberry Pi 4B
- Raspberry Pi Zero W
- Raspberry Pi Zero 2 W
- Raspberry Pi 5

## Technical background

The wake path needs both of the following:

1. A patched Raspberry Pi kernel that adds remote wakeup support to the `dwc2`
   gadget driver and a `wakeup_on_write` configfs attribute to the HID gadget
   function.
2. A Bluetooth-2-USB runtime that enables `wakeup_on_write=1` for the keyboard
   HID function when that attribute exists.

Without the kernel patch, the runtime cannot wake suspended hosts.

## Patch source

Primary reference issue:

- Raspberry Pi Linux issue `#3977`:
  https://github.com/raspberrypi/linux/issues/3977

Reference patch:

- PiKVM patch:
  https://github.com/pikvm/packages/blob/master/packages/linux-rpi-pikvm/1001-pikvm-hid-remote-wakeup-support.patch

PiKVM is relevant here only as a technical reference. Its Bluetooth HID support
is a different operating model from relaying external Bluetooth input devices
through Bluetooth-2-USB.

## Target matrix

| Target | Architecture | Defconfig | `KERNEL` | Recommended custom image |
| --- | --- | --- | --- | --- |
| Raspberry Pi 4B | `arm64` | `bcm2711_defconfig` | `kernel8` | `kernel8-b2u-wake.img` |
| Raspberry Pi Zero W | `arm` | `bcmrpi_defconfig` | `kernel` | `kernel-b2u-wake.img` |
| Raspberry Pi Zero 2 W | `arm64` | `bcm2711_defconfig` | `kernel8` | `kernel8-b2u-wake.img` |
| Raspberry Pi Zero 2 W (optional 32-bit) | `arm` | `bcm2709_defconfig` | `kernel7` | `kernel7-b2u-wake.img` |
| Raspberry Pi 5 | `arm64` | `bcm2712_defconfig` | `kernel_2712` | `kernel_2712-b2u-wake.img` |

The main path for Zero 2 W is 64-bit. The 32-bit variant is optional.

## Build strategy

Recommended:

- cross-compile on a Linux workstation

Not recommended as the default:

- native build on the Pi

Cross-compilation is faster, easier to repeat, and cleaner across multiple
target architectures.

Use parallel builds unless you have a reason not to:

```bash
export JOBS="$(nproc)"
```

## Required build dependencies

Install the general build dependencies:

```bash
sudo apt install bc bison flex libssl-dev make libc6-dev libncurses5-dev
```

Install the toolchain for the architecture you want to build:

- 64-bit:

```bash
sudo apt install crossbuild-essential-arm64
```

- 32-bit:

```bash
sudo apt install crossbuild-essential-armhf
```

If you do not have an `arm-linux-gnueabihf-` toolchain but do have a complete
LLVM toolchain, the 32-bit Raspberry Pi Zero W path can also be built with:

```bash
make LLVM=1 ARCH=arm ...
```

That fallback is workable, but it is not the default documented path because
the Raspberry Pi ARM32 tree is usually exercised more heavily with GCC-style
toolchains.

## Prepare a separate kernel checkout

Do not build the kernel inside the `bluetooth_2_usb` repository.

Recommended layout:

```bash
mkdir -p ~/src
cd ~/src
git clone --depth=1 --branch rpi-6.12.y https://github.com/raspberrypi/linux.git rpi-linux-wakeup
cd rpi-linux-wakeup
git switch -c b2u/rpi-6.12.y-remote-wakeup
```

## Apply the wakeup patch

Download and apply the patch:

```bash
curl -L \
  https://raw.githubusercontent.com/pikvm/packages/master/packages/linux-rpi-pikvm/1001-pikvm-hid-remote-wakeup-support.patch \
  -o 1001-pikvm-hid-remote-wakeup-support.patch

patch -p1 < 1001-pikvm-hid-remote-wakeup-support.patch
```

If the patch does not apply cleanly:

- stop
- verify that you are really on `rpi-6.12.y`
- inspect whether Raspberry Pi changed the target files enough to require a new
  forward-port

## Set a custom local version

Use a fixed local version suffix:

```text
-b2u-wake
```

This keeps:

- `uname -r` clearly custom
- `/lib/modules` separate from the stock kernel
- rollback simpler

You can set this in `.config` after loading the defconfig, or with `menuconfig`.

## Build commands by target

### Raspberry Pi 4B and Zero 2 W, 64-bit

```bash
cd ~/src/rpi-linux-wakeup
export KERNEL=kernel8
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- bcm2711_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- Image modules dtbs
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- kernelrelease
```

### Raspberry Pi 5, 64-bit

```bash
cd ~/src/rpi-linux-wakeup
export KERNEL=kernel_2712
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- bcm2712_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- Image modules dtbs
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- kernelrelease
```

### Raspberry Pi Zero W, 32-bit

```bash
cd ~/src/rpi-linux-wakeup
export KERNEL=kernel
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- bcmrpi_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- zImage modules dtbs
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- kernelrelease
```

### Raspberry Pi Zero W, 32-bit, LLVM fallback

Use this only when you intentionally want the LLVM path or do not have the
`arm-linux-gnueabihf-` toolchain available.

```bash
cd ~/src/rpi-linux-wakeup
export KERNEL=kernel
make O=out/pi0w LLVM=1 ARCH=arm bcmrpi_defconfig
scripts/config --file out/pi0w/.config --set-str LOCALVERSION "-b2u-wake"
scripts/config --file out/pi0w/.config --disable BCM2835_FAST_MEMCPY
make O=out/pi0w LLVM=1 ARCH=arm syncconfig
make -j"${JOBS}" O=out/pi0w LLVM=1 ARCH=arm LOCALVERSION= zImage modules dtbs
make O=out/pi0w LLVM=1 ARCH=arm LOCALVERSION= kernelrelease
cp out/pi0w/.config "out/pi0w/config-$(make O=out/pi0w LLVM=1 ARCH=arm LOCALVERSION= kernelrelease)"
```

Why disable `CONFIG_BCM2835_FAST_MEMCPY` here:

- on the Zero W ARM32 path, Clang's integrated assembler can choke on the
  Raspberry Pi specific `memcmp_rpi.S` implementation
- disabling `CONFIG_BCM2835_FAST_MEMCPY` switches back to the generic memcpy
  and memcmp implementations, which allowed the build to complete cleanly in
  a tested LLVM build

Important details for this LLVM path:

- keep using the `-b2u-wake` local version in `.config`
- pass `LOCALVERSION=` on the `make ... kernelrelease` and build commands so
  the final kernel release is `...-b2u-wake` instead of `...-b2u-wake+`
- if you use an out-of-tree build directory, copy `config-<kernelrelease>`
  from that build directory, not from the source tree

### Raspberry Pi Zero 2 W, optional 32-bit

```bash
cd ~/src/rpi-linux-wakeup
export KERNEL=kernel7
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- bcm2709_defconfig
scripts/config --set-str LOCALVERSION "-b2u-wake"
make -j"${JOBS}" ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- zImage modules dtbs
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- kernelrelease
```

Record the exact output of `make ... kernelrelease`. That string controls the
module install path and is part of your validation.

Keep the built kernel config as well:

```bash
KR="$(make ARCH="${ARCH}" CROSS_COMPILE="${CROSS_COMPILE}" kernelrelease)"
cp .config "config-${KR}"
```

Use the same `ARCH` and `CROSS_COMPILE` values as the build command you ran.

## Deploy to the Pi

Use a separate custom kernel filename instead of overwriting the stock image.

This playbook recommends an online deploy directly to the running Pi over SSH.
The general flow is:

1. copy the kernel source tree or build tree to the Pi
2. install modules into the live root filesystem on the Pi
3. copy the custom kernel image, DTBs, and overlays into `/boot/firmware`
4. point `config.txt` at the custom kernel image

For a live system, the cleanest practical approach is:

```bash
rsync -a --delete ~/src/rpi-linux-wakeup/ pi@TARGET:~/rpi-linux-wakeup/
ssh pi@TARGET
cd ~/rpi-linux-wakeup
```

Then install the modules on the Pi itself, using the same target-specific
`ARCH` and `CROSS_COMPILE` values you used for the build:

- 64-bit:

```bash
sudo env PATH="$PATH" make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- modules_install
```

- 32-bit:

```bash
sudo env PATH="$PATH" make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- modules_install
```

- 32-bit LLVM out-of-tree build:

```bash
sudo env PATH="$PATH" make O=out/pi0w LLVM=1 ARCH=arm LOCALVERSION= modules_install
```

Then copy the kernel, DTBs, and overlays into `/boot/firmware`:

- 64-bit:

```bash
sudo cp arch/arm64/boot/Image "/boot/firmware/${KERNEL}-b2u-wake.img"
sudo cp arch/arm64/boot/dts/broadcom/*.dtb /boot/firmware/
sudo cp arch/arm/boot/dts/overlays/*.dtb* /boot/firmware/overlays/
sudo cp arch/arm/boot/dts/overlays/README /boot/firmware/overlays/
sudo cp "config-$(make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- kernelrelease)" "/boot/config-$(make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- kernelrelease)"
```

- 32-bit:

```bash
sudo cp arch/arm/boot/zImage "/boot/firmware/${KERNEL}-b2u-wake.img"
sudo cp arch/arm/boot/dts/broadcom/*.dtb /boot/firmware/
sudo cp arch/arm/boot/dts/overlays/*.dtb* /boot/firmware/overlays/
sudo cp arch/arm/boot/dts/overlays/README /boot/firmware/overlays/
sudo cp "config-$(make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- kernelrelease)" "/boot/config-$(make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- kernelrelease)"
```

- 32-bit LLVM out-of-tree build:

```bash
sudo cp out/pi0w/arch/arm/boot/zImage "/boot/firmware/${KERNEL}-b2u-wake.img"
sudo cp out/pi0w/arch/arm/boot/dts/broadcom/*.dtb /boot/firmware/
sudo cp arch/arm/boot/dts/overlays/*.dtb* /boot/firmware/overlays/
sudo cp arch/arm/boot/dts/overlays/README /boot/firmware/overlays/
sudo cp "out/pi0w/config-$(make O=out/pi0w LLVM=1 ARCH=arm LOCALVERSION= kernelrelease)" "/boot/config-$(make O=out/pi0w LLVM=1 ARCH=arm LOCALVERSION= kernelrelease)"
```

Required boot-side safeguards:

- back up `/boot/firmware/config.txt`
- back up the current stock kernel image
- keep the stock kernel image intact
- install the custom image under a new name
- install `/boot/config-<kernelrelease>` for the custom kernel so built-in
  gadget drivers can still be detected correctly by runtime checks

Example kernel names and matching `kernel=` values:

- Pi 4B / Zero 2 W 64-bit:
  - `/boot/firmware/kernel8-b2u-wake.img`
  - `kernel=kernel8-b2u-wake.img`
- Zero W 32-bit:
  - `/boot/firmware/kernel-b2u-wake.img`
  - `kernel=kernel-b2u-wake.img`
- Zero 2 W 32-bit:
  - `/boot/firmware/kernel7-b2u-wake.img`
  - `kernel=kernel7-b2u-wake.img`
- Pi 5:
  - `/boot/firmware/kernel_2712-b2u-wake.img`
  - `kernel=kernel_2712-b2u-wake.img`

Adjust the filename to match your target before rebooting.

Before rebooting, confirm that `config.txt` contains only the intended custom
kernel line for this workflow:

```bash
grep -n '^kernel=' /boot/firmware/config.txt
```

For a Zero W test run, the expected line is:

```text
kernel=kernel-b2u-wake.img
```

## Rollback

Rollback must be possible before the first reboot.

Rollback path:

1. edit `/boot/firmware/config.txt`
2. remove or change the `kernel=` line back to the stock kernel choice
3. reboot

If you backed up the stock image under a distinct name, you can also point
`kernel=` to that known-good image explicitly.

## Bluetooth-2-USB integration

With the patched kernel installed, Bluetooth-2-USB should set
`wakeup_on_write=1` for the keyboard HID function when available.

Expected behavior:

- patched kernel:
  - keyboard HID may wake the host
- stock kernel:
  - Bluetooth-2-USB ignores the missing attribute and continues normally

Mouse and consumer-control functions should keep `wakeup_on_write=0`.

## Verification

### 1. Confirm the custom kernel is running

```bash
uname -r
```

You should see the custom local version suffix, for example `-b2u-wake`.

### 2. Confirm the wakeup attribute exists

```bash
find /sys/kernel/config/usb_gadget -path '*/functions/hid.usb*/wakeup_on_write'
```

### 3. Confirm the gadget still advertises remote wakeup

```bash
cat /sys/kernel/config/usb_gadget/adafruit-blinka/configs/c.1/bmAttributes
```

Expected:

```text
0xa0
```

### 4. Confirm Bluetooth-2-USB enables wake on the keyboard function

```bash
cat /sys/kernel/config/usb_gadget/adafruit-blinka/functions/hid.usb0/wakeup_on_write
```

Expected:

```text
1
```

Mouse and consumer-control should remain disabled:

```bash
cat /sys/kernel/config/usb_gadget/adafruit-blinka/functions/hid.usb1/wakeup_on_write
cat /sys/kernel/config/usb_gadget/adafruit-blinka/functions/hid.usb2/wakeup_on_write
```

Expected:

```text
0
0
```

### 5. Functional wake test

1. connect the Pi to the host as usual
2. let the host suspend
3. send keyboard input through Bluetooth-2-USB
4. verify that:
   - the host wakes
   - the HID path still works after wake

### 6. Regression check

Also verify:

- normal typing while the host is already awake still works
- mouse input does not unintentionally wake the host in the default setup
- consumer-control input does not unintentionally wake the host in the default setup

### 7. If the first post-reboot smoke test fails on Bluetooth power

Do not immediately treat that as a wake-kernel regression.

On at least one tested Zero W boot after switching to the custom kernel, the
first failing smoke test was caused by a persisted Bluetooth rfkill soft block,
not by the wake patch:

- `bluetoothctl show` reported `Powered: no`
- `PowerState: off-blocked`
- `rfkill` showed `soft=1`

Check that state explicitly:

```bash
sudo rfkill list bluetooth
sudo bluetoothctl show
```

If Bluetooth is soft-blocked again after reboot, inspect the persisted
`systemd-rfkill` state:

```bash
sudo ls -l /var/lib/systemd/rfkill
sudo od -An -t u1 /var/lib/systemd/rfkill/*:bluetooth 2>/dev/null
```

If the active Bluetooth state file contains `49 10`, that is the saved value
`1\n`, which will be re-applied as a soft block on later boots.

Clear the live block and the saved state before re-testing:

```bash
sudo sh -c 'for f in /var/lib/systemd/rfkill/*:bluetooth; do printf "0\n" > "$f"; done'
sudo rfkill unblock bluetooth
sudo systemctl restart bluetooth
```

Then repeat the smoke test and one more reboot to verify that the controller
stays unblocked across boot.

## Known limitations

- even with the patch, suspend/wake behavior still depends on host behavior
- the documented path is based on `rpi-6.12.y`
- future Raspberry Pi kernel changes may require re-porting the patch
- Zero 2 W 32-bit is documented as an optional path, not the primary target
