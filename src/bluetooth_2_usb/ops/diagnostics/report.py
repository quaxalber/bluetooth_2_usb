from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .. import boot_config
from ..bluetooth import rfkill_list_bluetooth
from ..commands import OpsError, ok, output, run, timestamp
from ..paths import PATHS
from ..readonly import (
    bluetooth_state_persistent,
    load_readonly_config,
    overlay_status,
    readonly_mode,
)
from .redaction import redact


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
            suffix = (
                ""
                if completed.returncode == 0
                else f"\n[command exited with status {completed.returncode}]"
            )
        except (FileNotFoundError, OpsError) as exc:
            text = str(exc)
            suffix = "\n[command failed]"
        except subprocess.TimeoutExpired as exc:
            text = ((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else ""
            suffix = f"\n[timed out after {timeout}s]"
        body.append("```console\n" + redact((text or "<no output>") + suffix, hostname) + "\n```\n")

    try:
        initial_service_state = (
            run(
                ["systemctl", "is-active", PATHS.service_unit], check=False, capture=True
            ).stdout.strip()
            or "unknown"
        )
    except OpsError:
        initial_service_state = "unknown"

    text_block(
        "System summary",
        "\n".join(
            [
                f"boot_dir={boot_config.detect_boot_dir()}",
                f"initial_service_state={initial_service_state}",
                f"overlayfs={overlay_status()}",
                f"readonly_mode={readonly_mode()}",
                f"bluetooth_state_persistent={'yes' if bluetooth_state_persistent(config) else 'no'}",
            ]
        ),
    )
    command_block("Kernel", ["uname", "-a"], 5)
    command_block(
        "OS release",
        ["bash", "-lc", "grep -E '^(PRETTY_NAME|ID|VERSION|VERSION_CODENAME)=' /etc/os-release"],
        5,
    )
    command_block(
        "Hardware model",
        ["bash", "-lc", "tr -d '\\0' </proc/device-tree/model 2>/dev/null || true"],
        5,
    )
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
    command_block(
        "Service status", ["systemctl", "--no-pager", "--full", "status", PATHS.service_unit], 8
    )
    command_block(
        "Recent service journal",
        ["journalctl", "-b", "-u", PATHS.service_unit, "-n", "200", "--no-pager"],
        8,
    )
    command_block(
        "bluetooth.service status",
        ["systemctl", "--no-pager", "--full", "status", "bluetooth.service"],
        8,
    )
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
        command_block(
            "CLI environment validation",
            [PATHS.venv_python, "-m", "bluetooth_2_usb", "--validate-env"],
            5,
        )
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
            [
                PATHS.venv_python,
                "-m",
                "bluetooth_2_usb.service_settings",
                "--print-shell-command",
                "--append-debug",
            ],
            check=False,
            capture=True,
        ).stdout.strip()
        text_block(
            "Live debug setup",
            f"live_debug_duration={duration if duration else 'until interrupted'}\n"
            + f"live_debug_command={debug_command or '<missing>'}",
        )
        if debug_command:
            text_block(
                "Live Bluetooth-2-USB debug output",
                _run_live_debug(debug_command, duration, hostname),
            )
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
