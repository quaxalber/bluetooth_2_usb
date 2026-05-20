from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console

from ...udc import udc_states as read_udc_states
from .. import boot_config
from ..bluetooth import (
    bluetooth_controller_powered_from_text,
    bluetooth_paired_count,
    bluetooth_rfkill_blocked,
    bluetooth_rfkill_entries,
)
from ..commands import OpsError, bold, fail_final, info, ok, ok_final, run, warn
from ..commands import warn_fail as red_warn
from ..paths import PATHS
from ..readonly import (
    bluetooth_state_persistent,
    bluetooth_state_storage,
    display_readonly_mode,
    overlay_status,
    readonly_mode,
)
from .types import ProbeResult, ProbeStatus

SMOKETEST_COMMAND_TIMEOUT_SECONDS = 20


class SmokeTest:
    def __init__(self, *, verbose: bool, allow_non_pi: bool = False) -> None:
        self.verbose = verbose
        self.allow_non_pi = allow_non_pi
        self.exit_code = 0
        self.soft_warnings = 0
        self.summary: dict[str, str] = {}
        self.summary_groups: list[tuple[str, list[tuple[str, str]]]] = []
        self.results: list[ProbeResult] = []
        self.current_section = ""
        self.section_statuses: dict[str, ProbeStatus] = {}

    def run(self) -> int:
        config_txt = boot_config.boot_config_path()
        cmdline_txt = boot_config.boot_cmdline_path()
        readonly = readonly_mode()
        overlay = overlay_status()
        post_reboot = os.environ.get("SMOKETEST_POST_REBOOT", "0") == "1"
        modules_load_value = _first_modules_load(cmdline_txt)
        dwc2_mode = _try(boot_config.dwc2_mode, "unknown")
        required_modules = (
            boot_config.required_boot_modules_csv(dwc2_mode).split(",") if dwc2_mode != "unknown" else ["libcomposite"]
        )
        expected_overlay = _try(boot_config.expected_dwc2_overlay_line)
        root_filesystem_type = _try(boot_config.current_root_filesystem_type, "unknown")
        root_overlay_active = "yes" if root_filesystem_type == "overlay" else "no"
        if root_filesystem_type == "unknown":
            root_overlay_active = "unknown"
        bluetooth_persistent = bluetooth_state_persistent()
        bluetooth_storage = bluetooth_state_storage()
        expected_initramfs_file = boot_config.expected_boot_initramfs_file()
        expected_initramfs_path = (
            str(boot_config.boot_initramfs_target_path(expected_initramfs_file)) if expected_initramfs_file else ""
        )

        self._heading("Boot and USB")
        self._check_boot_overlay(config_txt, expected_overlay)
        self._check_modules(modules_load_value, required_modules)
        if dwc2_mode == "unknown":
            self.soft_warn(
                "Could not determine whether dwc2 is built-in or modular; boot module validation is heuristic"
            )
        self._path_exists(
            Path("/sys/kernel/config/usb_gadget"), "configfs gadget path is present", "configfs gadget path is missing"
        )
        udc_states = _udc_states()
        udc_list = " ".join(udc_states) if udc_states else ""
        self.record_bool(bool(udc_list), f"UDC is present ({udc_list})", "No UDC detected")
        if udc_states:
            configured_udcs = [name for name, state in udc_states.items() if state == "configured"]
            if configured_udcs:
                self.pass_probe("UDC state is configured (" + ", ".join(configured_udcs) + ")")
            else:
                self.soft_warn(
                    "UDC is not configured; relay output is gated until the host attaches. "
                    + "Current state: "
                    + ", ".join(f"{name}={state}" for name, state in udc_states.items())
                )
        self._heading("B2U Runtime")
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
            validate_log = self._capture_with_status(
                [PATHS.venv_python, "-m", "bluetooth_2_usb", "--validate-env"], "Validating CLI environment"
            )
            self.record_bool(
                validate_log[0] == 0,
                "CLI environment validation passed",
                "CLI environment validation failed",
                validate_log[1],
            )
            service_settings_log = self._capture_with_status(
                [PATHS.venv_python, "-m", "bluetooth_2_usb.service_settings", "--check"], "Checking runtime settings"
            )
            self.record_bool(
                service_settings_log[0] == 0,
                "Runtime settings are valid",
                "Runtime settings validation failed",
                service_settings_log[1],
            )
        else:
            missing_venv = f"Virtualenv interpreter is missing: {PATHS.venv_python}"
            validate_log = (127, missing_venv)
            service_settings_log = (127, missing_venv)
        self._heading("Bluetooth")
        bluetooth_service_log = self._capture_with_status(
            ["systemctl", "is-active", "bluetooth.service"], "Checking Bluetooth service"
        )
        self.record_bool(
            bluetooth_service_log[0] == 0,
            "bluetooth.service is active",
            "bluetooth.service is not active",
            bluetooth_service_log[1],
        )
        bt_show = self._capture_with_status(["bluetoothctl", "show"], "Checking Bluetooth controller")
        self.record_bool(
            bt_show[0] == 0 and bluetooth_controller_powered_from_text(bt_show[1]),
            "Bluetooth controller is powered",
            "bluetoothctl show failed or controller is not powered",
            bt_show[1],
        )
        btmgmt = self._capture_with_status(["btmgmt", "info"], "Checking Bluetooth management state")
        self.record_bool(btmgmt[0] == 0, "btmgmt info succeeded", "btmgmt info failed", btmgmt[1])
        entries = bluetooth_rfkill_entries()
        if entries:
            detail = "\n".join(entry.line() for entry in entries)
            if bluetooth_rfkill_blocked():
                self.warn_fail("Bluetooth rfkill is blocking the controller")
                print(detail)
            else:
                self.record_bool(
                    True, "Bluetooth rfkill state is not blocked", "Bluetooth rfkill is blocking the controller", detail
                )
        else:
            self.soft_warn("No bluetooth rfkill entries found")
        self._heading("Devices")
        inventory = (
            self._capture_with_status(
                [PATHS.venv_python, "-m", "bluetooth_2_usb", "--list", "--output", "json"], "Checking input devices"
            )
            if venv_present
            else (127, missing_venv)
        )
        relayable_count = self._relayable_count(inventory)
        paired_count = self._paired_count()
        self._path_exists(
            Path("/var/lib/bluetooth"), "Bluetooth state directory exists", "Bluetooth state directory is missing"
        )
        self._heading("Read-Only Mode")
        self._check_overlay_runtime(overlay, root_overlay_active, post_reboot)
        self._check_initramfs(overlay, root_overlay_active, readonly, expected_initramfs_path)
        self._check_readonly(
            readonly, overlay, root_overlay_active, bluetooth_persistent, bluetooth_storage, post_reboot
        )
        self._print_readonly_summary(readonly, overlay, root_overlay_active, bluetooth_storage)

        self.summary_groups = [
            (
                "Boot and USB",
                [
                    ("Boot config", str(config_txt)),
                    ("Cmdline", str(cmdline_txt)),
                    ("modules-load token", modules_load_value or "<missing>"),
                    ("required modules", ",".join(required_modules)),
                    ("expected overlay line", expected_overlay or "<unknown>"),
                    ("configured kernel image", boot_config.configured_kernel_image()),
                    ("configured initramfs file", boot_config.configured_initramfs_file() or "<none>"),
                    ("expected boot initramfs file", expected_initramfs_file or "<none>"),
                    ("expected boot initramfs path", expected_initramfs_path or "<none>"),
                    ("UDC controllers", udc_list or "<none>"),
                    ("UDC state", ", ".join(f"{name}={state}" for name, state in udc_states.items()) or "<none>"),
                    ("USB gadget identity", _usb_gadget_identity()),
                ],
            ),
            (
                "B2U Runtime",
                [
                    (
                        "Virtualenv interpreter",
                        str(PATHS.venv_python) if venv_present else f"missing: {PATHS.venv_python}",
                    ),
                    ("CLI environment validation", "passed" if validate_log[0] == 0 else "failed"),
                    ("Runtime settings validation", "passed" if service_settings_log[0] == 0 else "failed"),
                ],
            ),
            (
                "Bluetooth",
                [
                    ("bluetooth.service", "active" if bluetooth_service_log[0] == 0 else "inactive"),
                    ("Bluetooth controller", "powered" if bt_show[0] == 0 else "unknown"),
                    ("btmgmt info", "succeeded" if btmgmt[0] == 0 else "failed"),
                    (
                        "Bluetooth rfkill",
                        (
                            "not blocked"
                            if entries and not bluetooth_rfkill_blocked()
                            else ("blocked" if entries else "not found")
                        ),
                    ),
                ],
            ),
            (
                "Devices",
                [
                    ("Relayable device count", str(relayable_count)),
                    ("Paired Bluetooth device count", str(paired_count)),
                ],
            ),
            (
                "Read-Only Mode",
                [
                    ("Read-only state", display_readonly_mode(readonly)),
                    ("OverlayFS boot setting", overlay),
                    ("Root filesystem type", root_filesystem_type),
                    (
                        "Root source",
                        self._capture(["findmnt", "-n", "-o", "SOURCE", "--target", "/"])[1].strip() or "<unknown>",
                    ),
                    ("Bluetooth state storage", bluetooth_storage),
                    (
                        "Bluetooth state source",
                        self._capture(["findmnt", "-n", "-o", "SOURCE", "--target", "/var/lib/bluetooth"])[1].strip()
                        or "<none>",
                    ),
                    ("Persistent storage mount", "mounted" if bluetooth_persistent else "not mounted"),
                ],
            ),
            ("Result", [("Non-fatal warning count", str(self.soft_warnings))]),
        ]
        self.summary = {key: value for _, items in self.summary_groups for key, value in items}
        if self.verbose:
            self._print_verbose(entries, validate_log, service_settings_log, bt_show, btmgmt, inventory)
        self._heading("Summary")
        if self.exit_code == 0:
            ok_final("Smoke test PASSED (with warnings)" if self.soft_warnings else "Smoke test PASSED")
        else:
            fail_final("Smoke test FAILED")
        return self.exit_code

    def result_dict(self) -> dict[str, object]:
        return {
            "exit_code": self.exit_code,
            "result": "ok" if self.exit_code == 0 else "failed",
            "soft_warnings": self.soft_warnings,
            "summary": dict(self.summary),
            "probes": [result.to_dict() for result in self.results],
        }

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
            self.pass_probe(f"config.txt contains expected overlay ({expected_overlay})")
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
            self.pass_probe(f"cmdline.txt contains required modules-load ({token or '<missing>'})")

    def _check_overlay_runtime(self, overlay: str, root_overlay_active: str, post_reboot: bool) -> None:
        if overlay in {"enabled", "disabled"}:
            self.pass_probe(f"OverlayFS boot setting is {overlay}")
        else:
            (
                self.soft_warn("OverlayFS boot setting is unknown")
                if self.allow_non_pi
                else self.warn_fail("OverlayFS boot setting is unknown")
            )
        if root_overlay_active == "yes":
            self.pass_probe("Root filesystem is overlay-backed")
        elif root_overlay_active == "unknown":
            (
                self.soft_warn("Could not determine root filesystem read-only state")
                if self.allow_non_pi or (overlay == "enabled" and not post_reboot)
                else self.warn_fail("Could not determine root filesystem read-only state")
            )
            report = boot_config.root_overlay_report()
            if report:
                print(report)
        elif overlay == "enabled":
            (
                self.warn_fail("Root filesystem is not overlay-backed")
                if post_reboot
                else self.soft_warn("Read-only mode enablement is pending reboot")
            )
        else:
            self.pass_probe("Root filesystem is writable")

    def _check_initramfs(self, overlay: str, root_overlay_active: str, readonly: str, expected_path: str) -> None:
        should_require = overlay == "enabled" or root_overlay_active == "yes" or readonly == "enabled"
        if not expected_path:
            if should_require:
                self.warn_fail("Boot initramfs target could not be determined")
            return
        path = Path(expected_path)
        present = path.is_file() and path.stat().st_size > 0
        if present:
            self.pass_probe(f"Boot initramfs is present ({path})")
        elif should_require:
            self.warn_fail(f"Boot initramfs is missing or empty ({path})")
        else:
            info(f"Boot initramfs is not present yet ({path})")

    def _check_readonly(
        self,
        readonly: str,
        overlay: str,
        root_overlay_active: str,
        bluetooth_persistent: bool,
        bluetooth_storage: str,
        post_reboot: bool,
    ) -> None:
        if bluetooth_storage == "persistent":
            self.pass_probe("Bluetooth state is stored on persistent storage")
        elif overlay == "enabled" or readonly == "enabled" or root_overlay_active == "yes":
            self.warn_fail("Bluetooth persistent state is required but not mounted")
        elif bluetooth_storage == "rootfs":
            self.pass_probe("Bluetooth state is stored on rootfs")
        elif bluetooth_storage == "missing":
            self.warn_fail("Bluetooth state directory is missing")
        else:
            self.soft_warn("Bluetooth state storage could not be determined")
        if readonly == "enabled":
            self.pass_probe("Read-only mode is active")
        elif readonly == "unknown":
            (
                self.soft_warn("Read-only mode could not be determined")
                if self.allow_non_pi
                else self.warn_fail("Read-only mode could not be determined")
            )
        elif overlay == "disabled" and root_overlay_active == "no":
            self.pass_probe("Read-only mode is disabled")
        elif overlay == "enabled" and root_overlay_active == "no":
            (
                self.warn_fail("Read-only mode is not active")
                if post_reboot
                else self.soft_warn("Read-only mode enablement is pending reboot")
            )
        else:
            self.warn_fail("Read-only mode is not active")

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
            self.pass_probe(f"Relayable input devices detected ({count})", visible=True)
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
            self.pass_probe(f"Paired Bluetooth devices detected ({count})", visible=True)
        else:
            self.soft_warn("No paired Bluetooth devices detected")
        return count

    def _path_exists(self, path: Path, success: str, failure: str, *, visible: bool = False) -> None:
        self.record_bool(path.exists(), success, failure, visible=visible)

    def _command_ok(self, command: list[str], success: str, failure: str, *, visible: bool = False) -> None:
        try:
            completed = run(command, check=False, capture=True, timeout=SMOKETEST_COMMAND_TIMEOUT_SECONDS)
        except (FileNotFoundError, OpsError) as exc:
            self.warn_fail(failure, str(exc))
            return
        self.record_bool(completed.returncode == 0, success, failure, visible=visible)

    def record_bool(
        self, condition: bool, success: str, failure: str, detail: str = "", *, visible: bool = False
    ) -> None:
        if condition:
            self.pass_probe(success, detail, visible=visible)
        else:
            self.warn_fail(failure, detail)

    def pass_probe(self, message: str, detail: str = "", *, visible: bool = False) -> None:
        self._mark_section(ProbeStatus.PASS)
        if self.verbose or visible:
            ok(message)
        self.results.append(ProbeResult(ProbeStatus.PASS, message, detail))

    def soft_warn(self, message: str) -> None:
        self._mark_section(ProbeStatus.WARN)
        warn(message)
        self.soft_warnings += 1
        self.results.append(ProbeResult(ProbeStatus.WARN, message))

    def warn_fail(self, message: str, detail: str = "") -> None:
        self._mark_section(ProbeStatus.FAIL)
        red_warn(message)
        if detail:
            print("\n".join(detail.splitlines()[:20]))
        self.exit_code = 1
        self.results.append(ProbeResult(ProbeStatus.FAIL, message, detail))

    def _capture(self, command: list[str | Path]) -> tuple[int, str]:
        try:
            completed = run(command, check=False, capture=True, timeout=SMOKETEST_COMMAND_TIMEOUT_SECONDS)
        except (FileNotFoundError, OpsError) as exc:
            return 127, str(exc)
        return completed.returncode, (completed.stdout + completed.stderr)

    def _capture_with_status(self, command: list[str | Path], message: str) -> tuple[int, str]:
        with self._status(message):
            return self._capture(command)

    @contextmanager
    def _status(self, message: str):
        with Console(file=sys.stdout).status(message, spinner="dots"):
            yield

    def _heading(self, title: str) -> None:
        if self.current_section:
            self._finish_section(self.current_section)
        self.current_section = title
        self.section_statuses.setdefault(title, ProbeStatus.PASS)
        print()
        print(bold(title))

    def _finish_section(self, title: str) -> None:
        if self.verbose or self.section_statuses.get(title) is not ProbeStatus.PASS:
            return
        if title in {"Boot and USB", "B2U Runtime", "Bluetooth"}:
            ok("All checks passed")

    def _mark_section(self, status: ProbeStatus) -> None:
        if not self.current_section:
            return
        current = self.section_statuses.get(self.current_section, ProbeStatus.PASS)
        if current is ProbeStatus.FAIL:
            return
        if status is ProbeStatus.FAIL or current is ProbeStatus.PASS:
            self.section_statuses[self.current_section] = status

    def _print_readonly_summary(
        self, readonly: str, overlay: str, root_overlay_active: str, bluetooth_storage: str
    ) -> None:
        if self.section_statuses.get("Read-Only Mode") is ProbeStatus.FAIL:
            return
        message = _readonly_summary_message(readonly, overlay, root_overlay_active, bluetooth_storage)
        if self.verbose:
            print(bold(f"Read-only summary: {message}"))
        else:
            ok(message)
        self.results.append(ProbeResult(ProbeStatus.PASS, message, ""))

    def _print_verbose(self, rfkill_entries, *logs: tuple[int, str]) -> None:
        print("\n## Details")
        for group, items in self.summary_groups:
            print(f"\n### {group}")
            for key, value in items:
                print(f"{key}: {value}")
        titles = ["CLI validate-env output", "Service settings check", "Device inventory"]
        for title, (_, text) in zip(titles[:2], logs[:2], strict=True):
            print(f"\n## {title}")
            print(text or "<no output>")
        print("\n## Bluetooth diagnostics")
        print("\n### bluetoothctl show")
        print(logs[2][1] or "<no output>")
        print("\n### btmgmt info")
        print(logs[3][1] or "<no output>")
        print("\n### rfkill bluetooth")
        print("\n".join(entry.line() for entry in rfkill_entries) or "<no output>")
        print(f"\n## {titles[2]}")
        print(logs[4][1] or "<no output>")
        print("\n## Mount details")
        self._print_mount_details()
        print("\n## Service status")
        print(
            self._capture_with_status(
                ["systemctl", "--no-pager", "--full", "status", PATHS.service_unit], "Collecting service status"
            )[1]
            or "<no output>"
        )

    def _print_mount_details(self) -> None:
        root_mount = self._capture_with_status(["findmnt", "-n", "-T", "/"], "Collecting root mount details")[1].strip()
        bluetooth_mount = self._capture_with_status(
            ["findmnt", "-n", "-T", "/var/lib/bluetooth"], "Collecting Bluetooth mount details"
        )[1].strip()
        print("Root mount:")
        print(root_mount or "<no output>")
        print("\nBluetooth state mount:")
        print(
            "same as root mount"
            if bluetooth_mount and bluetooth_mount == root_mount
            else bluetooth_mount or "<no output>"
        )


def _first_modules_load(cmdline_txt: Path) -> str:
    if not cmdline_txt.is_file():
        return ""
    for token in cmdline_txt.read_text(encoding="utf-8", errors="replace").split():
        if token.startswith("modules-load="):
            return token
    return ""


def _udc_states() -> dict[str, str]:
    try:
        return read_udc_states()
    except (FileNotFoundError, RuntimeError, OSError):
        return {}


def _usb_gadget_identity() -> str:
    gadget_roots = sorted(Path("/sys/kernel/config/usb_gadget").glob("*"))
    for gadget_root in gadget_roots:
        strings_root = gadget_root / "strings" / "0x409"
        values = []
        for name in ("manufacturer", "product", "serialnumber"):
            try:
                value = (strings_root / name).read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                value = ""
            if value:
                values.append(f"{name}={value}")
        if values:
            return f"{gadget_root.name}: " + ", ".join(values)
    return "<none>"


def _readonly_summary_message(readonly: str, overlay: str, root_overlay_active: str, bluetooth_storage: str) -> str:
    root_text = {"yes": "overlay root active", "no": "rootfs writable", "unknown": "root filesystem state unknown"}.get(
        root_overlay_active, "root filesystem state unknown"
    )
    storage_text = {
        "persistent": "Bluetooth state on persistent storage",
        "rootfs": "Bluetooth state on rootfs",
        "missing": "Bluetooth state missing",
        "unknown": "Bluetooth state unknown",
    }.get(bluetooth_storage, "Bluetooth state unknown")
    if overlay == "enabled" and root_overlay_active == "no":
        state = "pending reboot"
    elif readonly in {"enabled", "disabled"}:
        state = readonly
    else:
        state = "unknown"
    return f"{state}: {root_text}, {storage_text}"


def _try(func, default: str = "") -> str:
    try:
        return func()
    except Exception:
        return default
