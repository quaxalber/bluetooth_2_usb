<!-- omit in toc -->
# Bluetooth-2-USB

![Bluetooth-2-USB Overview](https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/assets/overview.png)

Turn a Raspberry Pi into a USB HID bridge for Bluetooth keyboards and mice.

To the target host, the Pi appears as a standard wired USB keyboard and mouse. That makes Bluetooth-2-USB useful in BIOS and boot menus, installers, KVM switches, kiosks, tablets, retro systems, consoles, and other environments where Bluetooth is unavailable, unsupported, or unreliable.

Bluetooth-2-USB is designed to be practical for both hobby setups and appliance-like deployments: install it, pair your devices, connect the Pi to the target host, and use your Bluetooth peripherals as if they were wired.

## Why people use it

- Use Bluetooth keyboards and mice on hosts that only accept wired USB HID
- Control BIOS, boot menus, recovery environments, and installers with the same wireless peripherals you already own
- Keep one small Pi attached to a target system instead of re-pairing each host
- Build durable read-mostly or read-only Raspberry Pi setups for embedded or unattended use

## Highlights

- Auto-discovery and auto-reconnect for supported input devices
- Optional input grabbing so the Pi does not also consume local keyboard/mouse events
- Multimedia keys and common consumer-control buttons relay alongside normal keyboard input
- Pause or resume relaying with a configurable shortcut so you can temporarily use the Pi locally
- HID compatibility profiles for hosts with stricter USB expectations
- Diagnostics and smoke tests designed for issue reports and field debugging
- Optional read-only modes for more appliance-like deployments

## Requirements

- A Raspberry Pi with:
  - Bluetooth support
  - USB OTG gadget support
- Recommended boards:
  - Raspberry Pi Zero W
  - Raspberry Pi Zero 2 W
  - Raspberry Pi 4B
  - Raspberry Pi 5
- Raspberry Pi OS Bookworm or newer
- Internet access during installation
- A Bluetooth keyboard, mouse, or both
- A USB cable that supports data, not power only

> [!NOTE]
> - Raspberry Pi 3 models include Bluetooth, but they do not expose a suitable USB device-mode port for this project.
> - On Pi 4B and Pi 5, the OTG-capable port is the USB-C power port.
> - On Pi Zero boards, the OTG-capable port is the USB data port, not the power-only port.

## Quick start

### 1. Prepare the Pi

Install Raspberry Pi OS Bookworm or newer, connect the Pi to the network, and optionally enable SSH if you plan to administer it remotely.

### 2. Install Bluetooth-2-USB

Fastest path:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh | sudo bash
```

> [!NOTE]
> As a general best practice, inspect `curl | sudo bash` installers before running them, especially on systems you care about. That advice applies here too.

### 3. Reboot

```bash
sudo reboot
```

### 4. Pair and trust your Bluetooth devices

You can pair devices through the desktop UI or with `bluetoothctl`.

Example CLI flow:

```bash
bluetoothctl
scan on
```

Wait for your device to appear, then trust, pair, and connect it:

```bash
trust A1:B2:C3:D4:E5:F6
pair A1:B2:C3:D4:E5:F6
connect A1:B2:C3:D4:E5:F6
exit
```

> [!NOTE]
> Replace `A1:B2:C3:D4:E5:F6` with your device's Bluetooth MAC address.

### 5. Verify the installation

Run the smoke test:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh
```

### 6. Connect the Pi to the target host

#### Raspberry Pi 4B / 5

Connect the Pi's **USB-C power port** to the target host. That is the OTG-capable port required for USB gadget mode.

Do **not** use the Pi's USB-A host ports for the connection to the target system.

#### Raspberry Pi Zero W / Zero 2 W

Connect the Pi's **USB data port** to the target host.

If possible, power the Pi from a separate stable power supply using the power-only port. That usually improves stability.

## Installation options

### Bootstrap installer

The bootstrap script downloads a repository archive and then runs the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh | sudo bash
```

Useful options:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh | sudo bash -s -- --branch main --no-reboot
```

### Clone-and-install

```bash
git clone https://github.com/quaxalber/bluetooth_2_usb.git
cd bluetooth_2_usb
sudo ./scripts/install.sh
```

### Install a specific branch or tag

Useful when testing a feature branch or release candidate:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh | sudo bash -s -- --branch YOUR-BRANCH-OR-TAG
```

## Configuration

This section is the short operational overview. The complete CLI and script reference is further down in [Reference](#reference).

The service reads optional runtime flags from:

```bash
/etc/default/bluetooth_2_usb
```

Default value:

```bash
BLUETOOTH_2_USB_ARGS="--auto_discover --grab_devices --interrupt_shortcut CTRL+SHIFT+F12 --hid-profile compat"
```

After editing that file, restart the service:

```bash
sudo systemctl restart bluetooth_2_usb.service
```

### Common runtime options

- `--auto_discover`  
  Relay readable input devices automatically.

- `--grab_devices`  
  Prevent the Pi from also consuming local input events.

- `--interrupt_shortcut CTRL+SHIFT+F12`  
  Toggle relaying on or off so you can temporarily use the Pi locally.

- `--device_ids ...`  
  Restrict relaying to specific input devices by event path, MAC address, or partial name.

- `--hid-profile compat|extended`  
  Select the USB HID descriptor profile.

- `--validate-env`  
  Validate gadget runtime prerequisites and exit.

- `--dry-run`  
  Run environment validation without binding the USB gadgets.

- `--no-bind`  
  Skip gadget initialization and perform diagnostic validation only.

### HID profiles

- `compat`  
  Default. Prioritizes host compatibility and is the right first choice for most users.

- `extended`  
  Keeps the broader behavior used by earlier releases and may help when you specifically want the older profile behavior.

## Day-to-day usage

List available devices:

```bash
bluetooth_2_usb --list_devices
```

Validate the runtime environment:

```bash
bluetooth_2_usb --validate-env
```

Run a non-binding diagnostic pass:

```bash
bluetooth_2_usb --dry-run --debug
```

Inspect recent service logs:

```bash
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

Follow logs live:

```bash
journalctl -u bluetooth_2_usb.service -f
```

## Updating

Update the managed installation in `/opt/bluetooth_2_usb` and recreate the virtual environment:

```bash
sudo /opt/bluetooth_2_usb/scripts/update.sh
```

## Uninstalling

Remove the managed service and helper files:

```bash
sudo /opt/bluetooth_2_usb/scripts/uninstall.sh
```

Remove the installation directory as well:

```bash
sudo /opt/bluetooth_2_usb/scripts/uninstall.sh --purge
```

Also revert managed boot configuration changes:

```bash
sudo /opt/bluetooth_2_usb/scripts/uninstall.sh --purge --revert-boot
```

## Diagnostics

Generate a Markdown debug report:

```bash
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact
```

`debug.sh` temporarily stops the service if it is running, launches a foreground Bluetooth-2-USB `--debug` session, and restores the service afterwards.

`--duration` bounds that live debug session. If you omit it, the debug run continues until you stop it with `Ctrl+C`.

`--redact` masks host identifiers such as the hostname, `machine-id`, UUIDs, PARTUUIDs, and Bluetooth MAC addresses. It is the recommended mode for reports shared in public issues.

Run a health check:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

## Read-only modes

Bluetooth-2-USB supports one normal writable mode and two OverlayFS-based operating modes for users who want a more appliance-like Raspberry Pi deployment.

### Why use read-only mode?

Read-only mode is mainly useful when you want the Pi to behave more like an appliance:

- tolerate abrupt power loss better
- reduce accidental writes to the root filesystem
- make field deployments more predictable
- keep a small relay box stable over long unattended runtimes

### What OverlayFS does and does not do

Raspberry Pi OS OverlayFS makes the root filesystem effectively read-only and redirects later changes into an upper writable layer in RAM.

What that helps with:

- fewer persistent writes to the root filesystem
- less filesystem damage after unclean shutdowns
- easier recovery of appliance-like systems
- lower write pressure on the root filesystem of SD-card-based systems

What it does **not** do by itself:

- persist Bluetooth state across reboots
- preserve new pairings unless the Bluetooth state is stored on separate writable persistent storage
- prevent SD-card wear if your persistent storage is still another partition on the same SD card

### Easy mode

Easy mode enables Raspberry Pi OS OverlayFS and stores recovery snapshots on the boot partition.

Use it when you want a simpler read-only setup and understand that Bluetooth persistence is best effort only.

Recommended flow:

1. Install Bluetooth-2-USB
2. Pair and trust your Bluetooth devices
3. Confirm normal operation first
4. Enable easy mode
5. Reboot
6. Run the smoke test again

Enable it with:

```bash
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode easy
```

> [!IMPORTANT]
> Easy mode is convenient, but it does **not** make `/var/lib/bluetooth` persist on a dedicated writable mount. Treat it as best effort, not as a hard persistence guarantee.

### Persistent mode

Persistent mode is the right choice if you need stable Bluetooth identity, pairings, and reconnect behavior while the root filesystem is read-only.

It uses a separate writable ext4 filesystem for Bluetooth state and bind-mounts it to `/var/lib/bluetooth`.

### Mode summary

| Mode       | Best for                                     | Setup effort | Bluetooth persistence                |
| ---------- | -------------------------------------------- | ------------ | ------------------------------------ |
| Normal     | Everyday use on a writable system            | Low          | Standard writable behavior           |
| Easy       | Simple read-mostly deployments               | Low          | Best effort only                     |
| Persistent | Embedded or production-like read-only setups | Medium       | Supported persistent Bluetooth state |

> [!NOTE]
> `Normal` is the default writable operating mode. It is included here for comparison, but it is not itself a read-only mode.

#### Choose the persistent storage device

There are two practical ways to provide the writable ext4 filesystem:

- A separate USB storage device: usually the simplest and lowest-risk option. It avoids repartitioning the system SD card and is easy to replace, reformat, or test.
- A dedicated extra partition on the system SD card: usually the cleanest fully self-contained option. It avoids extra external hardware, but you must plan or create the extra partition yourself.

Recommended rule of thumb:

- Use a separate USB ext4 device when your physical setup allows it and you want the least risky path
- Use a dedicated extra ext4 partition on the SD card when you prefer an all-in-one setup or external storage is awkward

Special note for Pi Zero W / Zero 2 W:

- These boards often end up using the SD-card partition approach more often because external USB storage typically needs extra adapters, hubs, or split power/data cabling

> [!NOTE]
> The Raspberry Pi Imager does not create this extra persistent ext4 partition for you. For persistent mode, you prepare the filesystem yourself and then point `setup_persistent_bluetooth_state.sh` at it.

Prepare persistent Bluetooth state:

```bash
sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/YOUR-DEVICE
```

> [!NOTE]
> Replace `/dev/YOUR-DEVICE` with the path to your writable ext4 filesystem, for example `/dev/sda1` or `/dev/mmcblk0p3`.

Enable persistent mode:

```bash
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode persistent
```

Default layout:

- Persistent mount: `/mnt/b2u-persist`
- Bluetooth state directory: `/mnt/b2u-persist/bluetooth`
- Bind mount target: `/var/lib/bluetooth`

> [!IMPORTANT]
> Persistent mode expects an ext4 filesystem that you provide. The project does not repartition your disk automatically.

#### Creating the persistent filesystem after Raspberry Pi OS is already installed

There are two common cases:

##### Option A: Use a separate USB storage device

This is usually the simplest option on any Pi where attaching extra storage is convenient.

1. Attach the device
2. Identify it:

```bash
lsblk -f
```

3. If needed, create an ext4 filesystem on the correct partition:

```bash
sudo mkfs.ext4 -L B2U_PERSIST /dev/YOUR-DEVICE
```

> [!NOTE]
> Replace `/dev/YOUR-DEVICE` with the partition you actually want to use.

4. Configure persistent Bluetooth state:

```bash
sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/YOUR-DEVICE
```

##### Option B: Use an extra partition on the SD card

This is the most integrated option across all Pi models and is often the most practical approach when you do not want an extra external storage device attached.

> [!IMPORTANT]
> This approach solves the Bluetooth persistence problem, but it does not reduce SD-card wear in the same way an external persistent device does. The persistent writes still land on the same physical SD card.

Typical target layout:

- `/dev/mmcblk0p1` boot
- `/dev/mmcblk0p2` root
- `/dev/mmcblk0p3` b2u persistent Bluetooth state

Important constraints:

- On an already-installed Raspberry Pi OS system, the root partition often already fills the remaining SD card space
- Creating a new third partition usually means shrinking the root filesystem first
- Do not casually shrink the live root partition while booted from it

Practical recommendation:

- Make a full SD-card backup first
- Power down the Pi
- Resize the card offline on another Linux system with a partitioning tool such as `gparted`
- Shrink the root filesystem and root partition
- Create a new ext4 partition for b2u persistent state
- Boot the Pi again and point b2u at the new partition

Example once the new partition exists:

```bash
sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/mmcblk0p3
```

If you are starting from scratch, it is often cleaner to plan this partition at the beginning of the build instead of retrofitting it later.

#### Full persistent-mode test flow

Once the ext4 filesystem exists, the simplest end-to-end test is:

```bash
sudo /opt/bluetooth_2_usb/scripts/setup_persistent_bluetooth_state.sh --device /dev/YOUR-DEVICE
sudo /opt/bluetooth_2_usb/scripts/enable_readonly_overlayfs.sh --mode persistent
sudo reboot
```

> [!NOTE]
> Replace `/dev/YOUR-DEVICE` with the ext4 partition or external device you prepared for persistent Bluetooth state.

After reboot:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact
findmnt /var/lib/bluetooth
findmnt /mnt/b2u-persist
```

What you want to confirm:

- `/var/lib/bluetooth` is a bind mount
- `/mnt/b2u-persist` is your writable ext4 filesystem
- `smoke_test.sh --verbose` reports persistent Bluetooth state
- previously paired devices reconnect after reboot
- reconnect behavior also survives an unclean power cut if that is part of your real deployment model

### Disable read-only mode

```bash
sudo /opt/bluetooth_2_usb/scripts/disable_readonly_overlayfs.sh
```

## Troubleshooting

### The Pi reboots, crashes, or behaves unstably

This is often a power issue.

Try the following:

- Use a stable external power supply where possible
- Prefer Raspberry Pi OS Lite for lower overhead
- Remove unnecessary peripherals from the Pi
- On Pi 4B/5, consider a USB-C data/power splitter if the host cannot supply enough power
- On Pi Zero boards, power the board separately and use the data port only for the host connection

### The service is running, but the target host does not react

Check the basics first:

```bash
sudo systemctl status bluetooth_2_usb.service
bluetooth_2_usb --validate-env
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

Then verify:

- You are connected to the correct OTG-capable port
- The USB cable supports data
- The Bluetooth devices are paired, trusted, connected, and not blocked
- The target host is seeing a new USB device
- Restarting the service or reconnecting the cable changes anything

Useful command:

```bash
journalctl -u bluetooth_2_usb.service -n 100 --no-pager
```

### A Bluetooth device keeps disconnecting or flapping

This can happen when the same peripheral has stale pairings or cache entries across multiple hosts.

A common recovery flow is:

```bash
bluetoothctl
power off
power on
block A1:B2:C3:D4:E5:F6
remove A1:B2:C3:D4:E5:F6
scan on
trust A1:B2:C3:D4:E5:F6
pair A1:B2:C3:D4:E5:F6
connect A1:B2:C3:D4:E5:F6
exit
```

If the issue persists, run `sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10 --redact` and open an issue with the output.

### Read-only mode is enabled, but reconnect behavior is unreliable

Confirm which mode you are using:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
```

Things to verify:

- `easy` mode is only best effort
- `persistent` mode should show Bluetooth state as persistent
- `/var/lib/bluetooth` should be a bind mount in persistent mode
- `/etc/machine-id` should remain stable

### Need help?

Please open an issue and include:

- Target host type
- Exact commands or scripts used
- Output from `smoke_test.sh --verbose`
- Output from `debug.sh --duration 10 --redact`

The debug report already includes the Pi model, OS version, kernel, service state, and boot/runtime diagnostics.

To copy the newest debug report off the Pi:

On the Pi:

```bash
ls -t /var/log/bluetooth_2_usb/debug_*.md | head -n 1
```

On your workstation:

```bash
scp YOUR-PI-HOST:/var/log/bluetooth_2_usb/debug_YYYYMMDD_HHMMSS.md .
```

> [!NOTE]
> Replace `YOUR-PI-HOST` with your Pi hostname or IP address, for example `pi4b` or `192.168.2.215`.

## Reference

The sections above focus on the common user flow. This section is the full command reference for contributors, power users, and anyone automating deployments.

### CLI reference: `bluetooth_2_usb`

| Option | Meaning |
| --- | --- |
| `--device_ids`, `-i` | Comma-separated device selectors. Each selector can be an event path, Bluetooth MAC address, or case-insensitive substring of the device name. |
| `--auto_discover`, `-a` | Relay all readable input devices automatically. |
| `--grab_devices`, `-g` | Grab the source input devices so the Pi does not also consume the local events. |
| `--interrupt_shortcut`, `-s` | Plus-separated key chord used to pause or resume relaying, for example `CTRL+SHIFT+F12`. |
| `--list_devices`, `-l` | List all visible input devices and exit. |
| `--log_to_file`, `-f` | Log to the default log file in addition to stdout. |
| `--log_path`, `-p` | Override the log path. Default: `/var/log/bluetooth_2_usb/bluetooth_2_usb.log` |
| `--debug`, `-d` | Enable more verbose logging. |
| `--version`, `-v` | Print the current version and exit. |
| `--dry-run` | Validate the environment without binding USB gadgets. |
| `--no-bind` | Skip gadget binding and only perform diagnostic validation. |
| `--validate-env` | Validate gadget prerequisites and exit with status information. |
| `--hid-profile compat\|extended` | Select the HID descriptor profile. `compat` is the default and should be the first choice for most hosts. |
| `--help`, `-h` | Show the CLI help text. |

### Script reference

All managed deployment scripts live in `/opt/bluetooth_2_usb/scripts/` after installation.

| Script | Purpose | Arguments |
| --- | --- | --- |
| `bootstrap.sh` | Download a repository archive from GitHub and run the managed installer without cloning first. | `--repo <url>` repository URL for the archive download<br>`--branch <name>` branch or tag to install<br>`--no-reboot` skip the immediate reboot prompt |
| `install.sh` | Install or refresh the managed checkout in `/opt/bluetooth_2_usb`, patch boot files, recreate the virtual environment, and install the systemd unit and wrapper. | `--repo <url\|path>` repository source<br>`--branch <name>` branch or tag to check out<br>`--no-reboot` skip the reboot prompt |
| `update.sh` | Update an existing managed installation, refresh the checkout and virtual environment, and optionally restart the service. | `--repo <url\|path>` override the update source<br>`--branch <name>` override the branch or tag<br>`--no-restart` update files without restarting the service |
| `uninstall.sh` | Stop and disable the managed service, remove units and helper files, and optionally restore the boot configuration captured during install. | `--purge` remove the installation directory<br>`--revert-boot` restore the managed boot snapshot<br>`--no-reboot` skip the reboot prompt |
| `debug.sh` | Collect a Markdown debug report with service state, mount state, boot config, dmesg, CLI diagnostics, and a live foreground debug run. | `--duration <sec>` bound the live debug session; omit to run until interrupted<br>`--redact` redact hostname, machine-id, UUIDs, PARTUUIDs, and Bluetooth MAC addresses |
| `smoke_test.sh` | Perform a quick installation and runtime health check for boot config, UDC, service state, environment validation, and read-only status. | `--verbose` print mount details, validate-env output, dry-run output, service status, and `journalctl` output |
| `enable_readonly_overlayfs.sh` | Enable Raspberry Pi OS OverlayFS mode and optionally prepare persistent Bluetooth state. | `--mode <easy\|persistent>` choose best-effort or persistent mode<br>`--persist-device <path>` device to use for persistent Bluetooth state in persistent mode |
| `disable_readonly_overlayfs.sh` | Disable Raspberry Pi OS OverlayFS root mode while keeping persistent Bluetooth-state configuration in place. | none |
| `setup_persistent_bluetooth_state.sh` | Create or validate the persistent Bluetooth-state mount, write the mount units and bind mount, and seed `/var/lib/bluetooth` into the persistent location. | `--device <path>` block device backing the persistent filesystem<br>`--no-enable` prepare configuration and units without activating them immediately |

Typical `bootstrap.sh` usage:

```bash
curl -fsSL https://raw.githubusercontent.com/quaxalber/bluetooth_2_usb/main/scripts/bootstrap.sh | sudo bash
```

### Managed paths and files

| Path | Purpose |
| --- | --- |
| `/opt/bluetooth_2_usb` | Managed installation root |
| `/opt/bluetooth_2_usb/venv` | Managed virtual environment |
| `/etc/default/bluetooth_2_usb` | Runtime config |
| `/etc/default/bluetooth_2_usb_readonly` | Read-only mode config |
| `/etc/systemd/system/bluetooth_2_usb.service` | Installed service unit |
| `/usr/local/bin/bluetooth_2_usb` | CLI wrapper |
| `/var/log/bluetooth_2_usb` | Logs |
| `/mnt/b2u-persist` | Persistent storage mount |
| `/mnt/b2u-persist/bluetooth` | Persistent Bluetooth-state directory |

## Contributing

Contributions are welcome, including documentation improvements, bug reports, hardware validation, and code changes.

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR or an issue.
Release tagging and versioning rules are documented in [docs/release-versioning-policy.md](docs/release-versioning-policy.md).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

The overview image is by Laura T. and is licensed under [CC BY-NC 4.0](http://creativecommons.org/licenses/by-nc/4.0/).

## Acknowledgments

- [Mike Redrobe](https://github.com/mikerr/pihidproxy) for the original Pi HID proxy idea
- [HeuristicPerson](https://github.com/HeuristicPerson/bluetooth_2_hid) for related prior art
- [Georgi Valkov](https://github.com/gvalkov) for [`python-evdev`](https://github.com/gvalkov/python-evdev)
- [Adafruit](https://www.adafruit.com/) for CircuitPython HID and Blinka, which helped make USB gadget access much smoother
- Everyone who tests the project on real hardware and reports what works, what fails, and how to improve it

---

<div align="center">

👀 Written by Eyes  
🤖 Assisted by Technology and AI  
☕ Powered by Coffee  
🫶 Developed with Love

</div>
