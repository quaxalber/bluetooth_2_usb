from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .. import boot_config
from ..artifacts import make_user_copyable
from ..bluetooth import rfkill_list_bluetooth
from ..commands import OpsError, ok, output, run, timestamp
from ..paths import PATHS
from ..readonly import (
    bluetooth_state_persistent,
    display_readonly_mode,
    load_readonly_config,
    overlay_status,
    readonly_mode,
)
from .redaction import redact

DEBUG_COMMAND_TIMEOUT_SECONDS = 20


def debug_report(duration: int | None) -> int:
    PATHS.log_dir.mkdir(parents=True, exist_ok=True)
    report_file = PATHS.log_dir / f"debug_{timestamp()}.md"
    hostname = os.environ.get("HOSTNAME") or output(["hostname"])
    body: list[str] = []
    try:
        config = load_readonly_config()
        readonly_config_error = ""
    except Exception as exc:
        config = None
        readonly_config_error = f"Persistent Bluetooth state config parse error: {exc}"

    def heading(title: str) -> None:
        body.append(f"## {title}\n")

    def text_block(title: str, text: str) -> None:
        heading(title)
        body.append("```text\n" + redact(text or "<no output>", hostname) + "\n```\n")

    def command_block(title: str, command: list[str | Path]) -> None:
        heading(title)
        try:
            completed = run(command, check=False, capture=True, timeout=DEBUG_COMMAND_TIMEOUT_SECONDS)
            text = completed.stdout + completed.stderr
            suffix = "" if completed.returncode == 0 else f"\n[command exited with status {completed.returncode}]"
        except (OSError, OpsError) as exc:
            text = str(exc)
            suffix = (
                f"\n[timed out after {DEBUG_COMMAND_TIMEOUT_SECONDS}s]"
                if "timed out after" in text
                else "\n[command failed]"
            )
        except subprocess.TimeoutExpired as exc:
            text = ((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else ""
            suffix = f"\n[timed out after {DEBUG_COMMAND_TIMEOUT_SECONDS}s]"
        body.append("```console\n" + redact((text or "<no output>") + suffix, hostname) + "\n```\n")

    try:
        initial_service_state = (
            run(
                ["systemctl", "is-active", PATHS.service_unit],
                check=False,
                capture=True,
                timeout=DEBUG_COMMAND_TIMEOUT_SECONDS,
            ).stdout.strip()
            or "unknown"
        )
    except (OpsError, OSError):
        initial_service_state = "unknown"

    text_block(
        "System summary",
        "\n".join(
            line
            for line in [
                f"boot_dir={boot_config.detect_boot_dir()}",
                f"initial_service_state={initial_service_state}",
                f"overlayfs={overlay_status()}",
                f"read_only_mode={display_readonly_mode(readonly_mode())}",
                (
                    "bluetooth_state_persistent_mount="
                    + ("mounted" if bluetooth_state_persistent(config) else "not_mounted")
                    if config is not None
                    else "bluetooth_state_persistent_mount=unknown"
                ),
                readonly_config_error,
            ]
            if line
        ),
    )
    command_block("Kernel", ["uname", "-a"])
    command_block(
        "OS release", ["bash", "-lc", "grep -E '^(PRETTY_NAME|ID|VERSION|VERSION_CODENAME)=' /etc/os-release"]
    )
    command_block("Hardware model", ["bash", "-lc", "tr -d '\\0' </proc/device-tree/model 2>/dev/null || true"])
    command_block(
        "config.txt dwc2 lines",
        [
            "bash",
            "-lc",
            f"grep -nE '^\\[all\\]|dtoverlay=dwc2.*' '{boot_config.boot_config_path()}' 2>/dev/null || true",
        ],
    )
    command_block("cmdline.txt", ["cat", boot_config.boot_cmdline_path()])
    command_block("UDC controllers", ["ls", "/sys/class/udc"])
    command_block(
        "USB gadget identity",
        [
            "bash",
            "-lc",
            "for f in /sys/kernel/config/usb_gadget/*/strings/0x409/{manufacturer,product,serialnumber}; "
            + 'do [ -f "$f" ] && printf \'%s=\' "$f" && cat "$f"; done; '
            + "test -f /var/lib/bluetooth_2_usb/usb_identity.json && "
            + "printf 'state=' && cat /var/lib/bluetooth_2_usb/usb_identity.json || true",
        ],
    )
    command_block("Overlay and tmpfs mounts", ["findmnt", "-t", "overlay,tmpfs"])
    command_block("Bluetooth state mount", ["findmnt", "-n", "-T", "/var/lib/bluetooth"])
    if config is not None:
        command_block("Persistent state storage mount", ["findmnt", "-n", config.persist_mount])
    if PATHS.readonly_env_file.is_file():
        command_block("Persistent Bluetooth state config", ["cat", PATHS.readonly_env_file])
    command_block("Service status", ["systemctl", "--no-pager", "--full", "status", PATHS.service_unit])
    command_block("Recent service journal", ["journalctl", "-b", "-u", PATHS.service_unit, "-n", "200", "--no-pager"])
    command_block("bluetooth.service status", ["systemctl", "--no-pager", "--full", "status", "bluetooth.service"])
    command_block(
        "Relevant kernel log lines",
        ["bash", "-lc", "dmesg | grep -Ei 'dwc2|gadget|udc|bluetooth|overlay' | tail -200 || true"],
    )
    command_block("bluetoothctl show", ["bluetoothctl", "show"])
    command_block("Paired devices", ["bluetoothctl", "devices", "Paired"])
    command_block("btmgmt info", ["btmgmt", "info"])
    text_block("rfkill bluetooth state", rfkill_list_bluetooth())
    if PATHS.venv_python.exists():
        command_block("CLI version", [PATHS.venv_python, "-m", "bluetooth_2_usb", "--version"])
        command_block("CLI environment validation", [PATHS.venv_python, "-m", "bluetooth_2_usb", "--validate-env"])
        command_block(
            "Service settings summary",
            [PATHS.venv_python, "-m", "bluetooth_2_usb.service_settings", "--print-summary-json"],
        )
        command_block(
            "Device inventory (json)", [PATHS.venv_python, "-m", "bluetooth_2_usb", "--list", "--output", "json"]
        )
        try:
            debug_command = run(
                [
                    PATHS.venv_python,
                    "-m",
                    "bluetooth_2_usb.service_settings",
                    "--print-shell-command",
                    "--append-debug",
                ],
                check=False,
                capture=True,
                timeout=DEBUG_COMMAND_TIMEOUT_SECONDS,
            ).stdout.strip()
        except (OSError, OpsError, subprocess.TimeoutExpired):
            debug_command = ""
        text_block(
            "Live debug setup",
            f"live_debug_duration={duration if duration else 'until interrupted'}\n"
            + f"live_debug_command={debug_command or '<missing>'}",
        )
        if debug_command:
            text_block("Live Bluetooth-2-USB debug output", _run_live_debug(debug_command, duration, hostname))
    else:
        text_block("CLI runtime", f"missing virtualenv at {PATHS.venv_python}")

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    header = f"# bluetooth_2_usb debug report\n\n_Generated: {generated_at}_\n\n"
    report_file.write_text(header + "\n".join(body), encoding="utf-8")
    make_user_copyable(report_file)
    ok(f"Wrote: {report_file}")
    return 0


def _run_live_debug(command: str, duration: int | None, hostname: str) -> str:
    stopped_service = False
    if (
        run(
            ["systemctl", "is-active", "--quiet", PATHS.service_unit],
            check=False,
            timeout=DEBUG_COMMAND_TIMEOUT_SECONDS,
        ).returncode
        == 0
    ):
        stop = run(
            ["systemctl", "stop", PATHS.service_unit], check=False, capture=True, timeout=DEBUG_COMMAND_TIMEOUT_SECONDS
        )
        if stop.returncode != 0:
            output_text = stop.stdout + stop.stderr
            return redact(
                "Failed to stop bluetooth_2_usb.service; live debug was not started.\n"
                + (output_text or "<no output>"),
                hostname,
            )
        stopped_service = True
    debug_output = ""
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
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                _terminate_process_group(process)
            output_file.seek(0)
            debug_output = output_file.read()
    finally:
        if stopped_service:
            start = run(
                ["systemctl", "start", PATHS.service_unit],
                check=False,
                capture=True,
                timeout=DEBUG_COMMAND_TIMEOUT_SECONDS,
            )
            if start.returncode != 0:
                debug_output += (
                    "\n[failed to restart bluetooth_2_usb.service: "
                    + ((start.stdout + start.stderr).strip() or "<no output>")
                    + "]"
                )
    return redact(debug_output, hostname) or "<no output>"


def _terminate_process_group(process: subprocess.Popen) -> None:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
