from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from . import boot_config
from .bluetooth import (
    bluetooth_controller_powered_from_text,
    bluetooth_paired_count,
    bluetooth_rfkill_blocked,
    bluetooth_rfkill_entries,
    rfkill_list_bluetooth,
)
from .commands import OpsError, fail, ok, output, run, timestamp, warn
from .paths import PATHS
from .readonly import bluetooth_state_persistent, load_readonly_config, overlay_status, readonly_mode


class SmokeTest:
    def __init__(self, *, verbose: bool, allow_non_pi: bool) -> None:
        self.verbose = verbose
        self.allow_non_pi = allow_non_pi
        self.exit_code = 0
        self.soft_warnings = 0
        self.summary: dict[str, str] = {}

    def run(self) -> int:
        config_txt = boot_config.boot_config_path()
        cmdline_txt = boot_config.boot_cmdline_path()
        readonly = readonly_mode()
        overlay = overlay_status()
        post_reboot = os.environ.get("SMOKETEST_POST_REBOOT", "0") == "1"
        modules_load_value = _first_modules_load(cmdline_txt)
        required_modules = boot_config.required_boot_modules_csv().split(",")
        expected_overlay = _try(boot_config.expected_dwc2_overlay_line)
        root_filesystem_type = _try(boot_config.current_root_filesystem_type, "unknown")
        root_overlay_active = "yes" if root_filesystem_type == "overlay" else "no"
        if root_filesystem_type == "unknown":
            root_overlay_active = "unknown"
        bluetooth_persistent = bluetooth_state_persistent()
        expected_initramfs_file = boot_config.expected_boot_initramfs_file()
        expected_initramfs_path = (
            str(boot_config.boot_initramfs_target_path(expected_initramfs_file)) if expected_initramfs_file else ""
        )

        self._check_boot_overlay(config_txt, expected_overlay)
        self._check_modules(modules_load_value, required_modules)
        if boot_config.dwc2_mode() == "unknown":
            self.soft_warn(
                "Could not determine whether dwc2 is built-in or modular; boot module validation is heuristic"
            )
        self._path_exists(
            Path("/sys/kernel/config/usb_gadget"), "configfs gadget path is present", "configfs gadget path is missing"
        )
        udc_list = " ".join(path.name for path in Path("/sys/class/udc").glob("*"))
        self._bool(bool(udc_list), f"UDC is present ({udc_list})", "No UDC detected")
        self._command_ok(
            ["systemctl", "is-enabled", PATHS.service_unit],
            f"{PATHS.service_unit} is enabled",
            f"{PATHS.service_unit} is not enabled",
        )
        self._command_ok(
            ["systemctl", "is-active", PATHS.service_unit],
            f"{PATHS.service_unit} is active",
            f"{PATHS.service_unit} is not active",
        )
        venv_present = PATHS.venv_python.is_file()
        self._path_exists(PATHS.venv_python, "Virtualenv interpreter is present", "Virtualenv interpreter is missing")
        if venv_present:
            validate_log = self._capture([PATHS.venv_python, "-m", "bluetooth_2_usb", "--validate-env"])
            self._bool(
                validate_log[0] == 0,
                "CLI environment validation passed",
                "CLI environment validation failed",
                validate_log[1],
            )
            service_settings_log = self._capture(
                [PATHS.venv_python, "-m", "bluetooth_2_usb.service_settings", "--check"]
            )
            self._bool(
                service_settings_log[0] == 0,
                "Runtime settings are valid",
                "Runtime settings validation failed",
                service_settings_log[1],
            )
        else:
            missing_venv = f"Virtualenv interpreter is missing: {PATHS.venv_python}"
            validate_log = (127, missing_venv)
            service_settings_log = (127, missing_venv)
        self._command_ok(
            ["systemctl", "is-active", "bluetooth.service"],
            "bluetooth.service is active",
            "bluetooth.service is not active",
        )
        bt_show = self._capture(["bluetoothctl", "show"])
        self._bool(
            bt_show[0] == 0 and bluetooth_controller_powered_from_text(bt_show[1]),
            "Bluetooth controller is powered",
            "bluetoothctl show failed or controller is not powered",
            bt_show[1],
        )
        btmgmt = self._capture(["btmgmt", "info"])
        self._bool(btmgmt[0] == 0, "btmgmt info succeeded", "btmgmt info failed", btmgmt[1])
        entries = bluetooth_rfkill_entries()
        if entries:
            if bluetooth_rfkill_blocked():
                self.warn_fail("Bluetooth rfkill is blocking the controller")
                print("\n".join(entry.line() for entry in entries))
            else:
                ok("Bluetooth rfkill state is not blocked")
        else:
            self.soft_warn("No bluetooth rfkill entries found")
        inventory = (
            self._capture([PATHS.venv_python, "-m", "bluetooth_2_usb", "--list_devices", "--output", "json"])
            if venv_present
            else (127, missing_venv)
        )
        relayable_count = self._relayable_count(inventory)
        paired_count = self._paired_count()
        self._path_exists(
            Path("/var/lib/bluetooth"), "Bluetooth state directory exists", "Bluetooth state directory is missing"
        )
        self._check_overlay_runtime(overlay, root_overlay_active, post_reboot)
        self._check_initramfs(overlay, root_overlay_active, readonly, expected_initramfs_path)
        self._check_readonly(readonly, overlay, root_overlay_active, bluetooth_persistent, post_reboot)

        self.summary = {
            "Boot config": str(config_txt),
            "Cmdline": str(cmdline_txt),
            "modules-load token": modules_load_value or "<missing>",
            "required modules": ",".join(required_modules),
            "expected overlay line": expected_overlay or "<unknown>",
            "configured kernel image": boot_config.configured_kernel_image(),
            "configured initramfs file": boot_config.configured_initramfs_file() or "<none>",
            "expected boot initramfs file": expected_initramfs_file or "<none>",
            "expected boot initramfs path": expected_initramfs_path or "<none>",
            "UDC controllers": udc_list or "<none>",
            "Readonly mode": readonly,
            "OverlayFS configured": overlay,
            "Root filesystem type": root_filesystem_type,
            "Root overlay active": root_overlay_active,
            "Bluetooth state persistent": "yes" if bluetooth_persistent else "no",
            "Relayable device count": str(relayable_count),
            "Paired Bluetooth device count": str(paired_count),
            "Non-fatal warning count": str(self.soft_warnings),
        }
        if self.verbose:
            self._print_verbose(validate_log, service_settings_log, bt_show, btmgmt, inventory)
        if self.exit_code == 0:
            ok("Smoke test PASSED (with warnings)" if self.soft_warnings else "Smoke test PASSED")
        else:
            fail("Smoke test FAILED")
        return self.exit_code

    def _check_boot_overlay(self, config_txt: Path, expected_overlay: str) -> None:
        if not expected_overlay:
            (
                self.soft_warn("Could not determine expected Raspberry Pi overlay line")
                if self.allow_non_pi
                else self.warn_fail("Could not determine expected Raspberry Pi overlay line")
            )
            return
        if (
            config_txt.is_file()
            and expected_overlay in config_txt.read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            ok(f"config.txt contains expected overlay ({expected_overlay})")
        else:
            self.warn_fail(f"config.txt is missing expected overlay ({expected_overlay})")

    def _check_modules(self, token: str, required: list[str]) -> None:
        normalized = f",{token.removeprefix('modules-load=')},"
        missing = [module for module in required if f",{module}," not in normalized]
        if missing:
            self.warn_fail(
                f"cmdline.txt is missing required modules ({','.join(required)}); current value: {token or '<missing>'}"
            )
        else:
            ok(f"cmdline.txt contains required modules-load ({token or '<missing>'})")

    def _check_overlay_runtime(self, overlay: str, root_overlay_active: str, post_reboot: bool) -> None:
        if overlay in {"enabled", "disabled"}:
            ok(f"OverlayFS boot configuration is {overlay}")
        else:
            (
                self.soft_warn("OverlayFS boot configuration status is unknown")
                if self.allow_non_pi
                else self.warn_fail("OverlayFS boot configuration status is unknown")
            )
        if root_overlay_active == "yes":
            ok("Root overlay is active")
        elif root_overlay_active == "unknown":
            (
                self.soft_warn("Could not determine whether the root overlay is active")
                if self.allow_non_pi or (overlay == "enabled" and not post_reboot)
                else self.warn_fail("Could not determine whether the root overlay is active")
            )
            report = boot_config.root_overlay_report()
            if report:
                print(report)
        elif overlay == "enabled":
            (
                self.warn_fail("Root overlay is not active")
                if post_reboot
                else self.soft_warn("Root overlay is not active; reboot may still be pending")
            )
        else:
            ok("Root overlay is inactive")

    def _check_initramfs(self, overlay: str, root_overlay_active: str, readonly: str, expected_path: str) -> None:
        should_require = overlay == "enabled" or root_overlay_active == "yes" or readonly == "persistent"
        if not expected_path:
            if should_require:
                self.warn_fail("Boot initramfs target could not be determined")
            return
        path = Path(expected_path)
        present = path.is_file() and path.stat().st_size > 0
        if present:
            ok(f"Boot initramfs is present ({path})")
        elif should_require:
            self.warn_fail(f"Boot initramfs is missing or empty ({path})")
        else:
            self.soft_warn(f"Boot initramfs is not present yet ({path})")

    def _check_readonly(
        self, readonly: str, overlay: str, root_overlay_active: str, bluetooth_persistent: bool, post_reboot: bool
    ) -> None:
        if bluetooth_persistent:
            ok(
                "Bluetooth state is mounted persistently"
                if readonly == "persistent"
                else "Bluetooth state persistence is active"
            )
        elif overlay == "enabled" or readonly == "persistent":
            self.warn_fail("Bluetooth state is not mounted persistently")
        else:
            ok("Bluetooth state persistence is not configured")
        if readonly == "persistent":
            ok("Read-only mode is persistent")
        elif readonly == "unknown":
            (
                self.soft_warn("Read-only mode could not be determined")
                if self.allow_non_pi
                else self.warn_fail("Read-only mode could not be determined")
            )
        elif overlay == "disabled" and root_overlay_active == "no":
            ok("Read-only mode is disabled")
        elif overlay == "enabled" and root_overlay_active == "no":
            (
                self.warn_fail("Read-only mode is not persistent")
                if post_reboot
                else self.soft_warn("Read-only mode is not persistent")
            )
        else:
            self.warn_fail("Read-only mode is not persistent")

    def _relayable_count(self, inventory: tuple[int, str]) -> int:
        if inventory[0] != 0:
            self.warn_fail("Device inventory failed", inventory[1])
            return 0
        try:
            devices = json.loads(inventory[1])
            count = sum(1 for device in devices if device.get("relay_candidate"))
        except Exception:
            self.warn_fail("Failed to parse relayable device inventory", inventory[1])
            return 0
        if count:
            ok(f"Relayable input devices detected ({count})")
        else:
            self.soft_warn("No relayable input devices detected")
        return count

    def _paired_count(self) -> int:
        try:
            count = bluetooth_paired_count()
        except Exception:
            self.warn_fail("bluetoothctl failed while listing paired devices")
            return 0
        if count:
            ok(f"Paired Bluetooth devices detected ({count})")
        else:
            self.soft_warn("No paired Bluetooth devices detected")
        return count

    def _path_exists(self, path: Path, success: str, failure: str) -> None:
        self._bool(path.exists(), success, failure)

    def _command_ok(self, command: list[str], success: str, failure: str) -> None:
        try:
            completed = run(command, check=False, capture=True)
        except (FileNotFoundError, OpsError) as exc:
            self.warn_fail(failure, str(exc))
            return
        self._bool(completed.returncode == 0, success, failure)

    def _bool(self, condition: bool, success: str, failure: str, detail: str = "") -> None:
        if condition:
            ok(success)
        else:
            self.warn_fail(failure, detail)

    def soft_warn(self, message: str) -> None:
        warn(message)
        self.soft_warnings += 1

    def warn_fail(self, message: str, detail: str = "") -> None:
        warn(message)
        if detail:
            print("\n".join(detail.splitlines()[:20]))
        self.exit_code = 1

    def _capture(self, command: list[str | Path]) -> tuple[int, str]:
        try:
            completed = run(command, check=False, capture=True)
        except (FileNotFoundError, OpsError) as exc:
            return 127, str(exc)
        return completed.returncode, (completed.stdout + completed.stderr)

    def _print_verbose(self, *logs: tuple[int, str]) -> None:
        print("\n## Summary")
        for key, value in self.summary.items():
            print(f"{key}: {value}")
        titles = [
            "CLI validate-env output",
            "Service settings check",
            "bluetoothctl show",
            "btmgmt info",
            "Device inventory",
        ]
        for title, (_, text) in zip(titles, logs, strict=True):
            print(f"\n## {title}")
            print(text or "<no output>")
        print("\n## rfkill bluetooth")
        print("\n".join(entry.line() for entry in bluetooth_rfkill_entries()) or "<no output>")
        print("\n## Mount details")
        print(self._capture(["findmnt", "-n", "-T", "/"])[1] or "<no output>")
        print(self._capture(["findmnt", "-n", "-T", "/var/lib/bluetooth"])[1] or "<no output>")
        print("\n## Service status")
        print(self._capture(["systemctl", "--no-pager", "--full", "status", PATHS.service_unit])[1] or "<no output>")
        print("\n## Journal")
        print(
            self._capture(["journalctl", "-b", "-u", PATHS.service_unit, "-n", "100", "--no-pager"])[1] or "<no output>"
        )


def _first_modules_load(cmdline_txt: Path) -> str:
    if not cmdline_txt.is_file():
        return ""
    for token in cmdline_txt.read_text(encoding="utf-8", errors="replace").split():
        if token.startswith("modules-load="):
            return token
    return ""


def _try(func, default: str = "") -> str:
    try:
        return func()
    except Exception:
        return default


def debug_report(duration: int | None) -> int:
    PATHS.log_dir.mkdir(parents=True, exist_ok=True)
    report_file = PATHS.log_dir / f"debug_{timestamp()}.md"
    hostname = os.environ.get("HOSTNAME") or output(["hostname"])
    body: list[str] = []
    config = load_readonly_config()

    def heading(title: str) -> None:
        body.append(f"## {title}\n")

    def text_block(title: str, text: str) -> None:
        heading(title)
        body.append("```text\n" + redact(text or "<no output>", hostname) + "\n```\n")

    def command_block(title: str, command: list[str | Path], timeout: int = 8) -> None:
        heading(title)
        try:
            completed = run(command, check=False, capture=True, timeout=timeout)
            text = completed.stdout + completed.stderr
            suffix = "" if completed.returncode == 0 else f"\n[command exited with status {completed.returncode}]"
        except (FileNotFoundError, OpsError) as exc:
            text = str(exc)
            suffix = "\n[command failed]"
        except subprocess.TimeoutExpired as exc:
            text = ((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else ""
            suffix = f"\n[timed out after {timeout}s]"
        body.append("```console\n" + redact((text or "<no output>") + suffix, hostname) + "\n```\n")

    text_block(
        "System summary",
        "\n".join(
            [
                f"boot_dir={boot_config.detect_boot_dir()}",
                "initial_service_state="
                + (
                    run(["systemctl", "is-active", PATHS.service_unit], check=False, capture=True).stdout.strip()
                    or "unknown"
                ),
                f"overlayfs={overlay_status()}",
                f"readonly_mode={readonly_mode()}",
                f"bluetooth_state_persistent={'yes' if bluetooth_state_persistent(config) else 'no'}",
            ]
        ),
    )
    command_block("Kernel", ["uname", "-a"], 5)
    command_block(
        "OS release", ["bash", "-lc", "grep -E '^(PRETTY_NAME|ID|VERSION|VERSION_CODENAME)=' /etc/os-release"], 5
    )
    command_block("Hardware model", ["bash", "-lc", "tr -d '\\0' </proc/device-tree/model 2>/dev/null || true"], 5)
    command_block(
        "config.txt dwc2 lines",
        [
            "bash",
            "-lc",
            f"grep -nE '^\\[all\\]|dtoverlay=dwc2.*' '{boot_config.boot_config_path()}' 2>/dev/null || true",
        ],
        5,
    )
    command_block("cmdline.txt", ["cat", boot_config.boot_cmdline_path()], 5)
    command_block("UDC controllers", ["ls", "/sys/class/udc"], 5)
    command_block("Overlay and tmpfs mounts", ["findmnt", "-t", "overlay,tmpfs"], 5)
    command_block("Bluetooth state mount", ["findmnt", "-n", "-T", "/var/lib/bluetooth"], 5)
    command_block("Persistent mount target", ["findmnt", "-n", config.persist_mount], 5)
    if PATHS.readonly_env_file.is_file():
        command_block("Read-only environment file", ["cat", PATHS.readonly_env_file], 5)
    command_block("Service status", ["systemctl", "--no-pager", "--full", "status", PATHS.service_unit], 8)
    command_block(
        "Recent service journal", ["journalctl", "-b", "-u", PATHS.service_unit, "-n", "200", "--no-pager"], 8
    )
    command_block("bluetooth.service status", ["systemctl", "--no-pager", "--full", "status", "bluetooth.service"], 8)
    command_block(
        "Relevant kernel log lines",
        ["bash", "-lc", "dmesg | grep -Ei 'dwc2|gadget|udc|bluetooth|overlay' | tail -200 || true"],
        8,
    )
    command_block("bluetoothctl show", ["bluetoothctl", "show"], 8)
    command_block("Paired devices", ["bluetoothctl", "devices", "Paired"], 8)
    command_block("btmgmt info", ["btmgmt", "info"], 8)
    text_block("rfkill bluetooth state", rfkill_list_bluetooth())
    if PATHS.venv_python.exists():
        command_block("CLI version", [PATHS.venv_python, "-m", "bluetooth_2_usb", "--version"], 5)
        command_block("CLI environment validation", [PATHS.venv_python, "-m", "bluetooth_2_usb", "--validate-env"], 5)
        command_block(
            "Service settings summary",
            [PATHS.venv_python, "-m", "bluetooth_2_usb.service_settings", "--print-summary-json"],
            5,
        )
        command_block(
            "Device inventory (json)",
            [PATHS.venv_python, "-m", "bluetooth_2_usb", "--list_devices", "--output", "json"],
            8,
        )
        debug_command = run(
            [PATHS.venv_python, "-m", "bluetooth_2_usb.service_settings", "--print-shell-command", "--append-debug"],
            check=False,
            capture=True,
        ).stdout.strip()
        text_block(
            "Live debug setup",
            f"live_debug_duration={duration if duration else 'until interrupted'}\n"
            + f"live_debug_command={debug_command or '<missing>'}",
        )
        if debug_command:
            text_block("Live Bluetooth-2-USB debug output", _run_live_debug(debug_command, duration, hostname))
    else:
        text_block("CLI runtime", f"missing virtualenv at {PATHS.venv_python}")

    report_file.write_text(
        "# bluetooth_2_usb debug report\n\n"
        f"_Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}_\n\n" + "\n".join(body),
        encoding="utf-8",
    )
    ok(f"Wrote: {report_file}")
    return 0


def _run_live_debug(command: str, duration: int | None, hostname: str) -> str:
    stopped_service = False
    if run(["systemctl", "is-active", "--quiet", PATHS.service_unit], check=False).returncode == 0:
        run(["systemctl", "stop", PATHS.service_unit], check=False)
        stopped_service = True
    try:
        timeout = duration
        with tempfile.TemporaryFile("w+t", encoding="utf-8") as output_file:
            process = subprocess.Popen(
                ["setsid", "bash", "--noprofile", "--norc", "-c", command],
                stdout=output_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            output_file.seek(0)
            return redact(output_file.read(), hostname) or "<no output>"
    finally:
        if stopped_service:
            run(["systemctl", "start", PATHS.service_unit], check=False)


def redact(text: str, hostname: str) -> str:
    patterns = [
        (r"PARTUUID=[^\s]+", "PARTUUID=<<REDACTED_PARTUUID>>"),
        (r"UUID=[^\s]+", "UUID=<<REDACTED_UUID>>"),
        (r"/dev/disk/by-uuid/[^\s]+", "/dev/disk/by-uuid/<<REDACTED_UUID>>"),
        (r"/dev/disk/by-partuuid/[^\s]+", "/dev/disk/by-partuuid/<<REDACTED_PARTUUID>>"),
        (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<<REDACTED_UUID>>"),
        (r"^(?:[0-9a-f]{32})$", "<<REDACTED_MACHINE_ID>>"),
        (r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b", "<<REDACTED_BT_MAC>>"),
    ]
    redacted = text
    if hostname:
        redacted = re.sub(rf"\b{re.escape(hostname)}\b", "<<REDACTED_HOSTNAME>>", redacted)
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE | re.MULTILINE)
    return redacted
