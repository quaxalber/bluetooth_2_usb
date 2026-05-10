from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.text import Text

from ...evdev import ecodes
from ..commands import info, ok, warn
from .collector import capture_device
from .linux import DeviceCaptureError
from .validate import validate_capture

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ENVIRONMENT = 3
EXIT_INTERRUPTED = 130
_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_PROGRESS_WIDTH = 8


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bluetooth_2_usb device", description="Device support tooling for collecting source input-device captures."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser(
        "capture",
        help="Capture static device metadata plus summarized live evdev and hidraw evidence.",
        description=(
            "Capture local evidence for adding support for a Linux input device. "
            "Summarized mode keeps compact support data by default; raw mode emits every live event and report. "
            "The artifact may contain typed keys, report bytes, MAC addresses, and unique device IDs."
        ),
    )
    capture.add_argument(
        "--devices",
        required=True,
        help=(
            "Comma-separated input device filters. Each filter may match path, uniq, phys, "
            "Bluetooth MAC, or name fragment. Multiple matches are captured together."
        ),
    )
    capture.add_argument("--duration", type=_positive_int, default=30, help="Capture duration in seconds. Default: 30")
    capture.add_argument(
        "--output",
        type=Path,
        default=None,
        help=("JSONL output path. Default: " "./device_capture/<matched-device-name>[_raw]_<timestamp>.jsonl"),
    )
    capture.add_argument(
        "--grab", action="store_true", help="Exclusively grab all matched input event devices during capture."
    )
    capture.add_argument(
        "--include-hidraw",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also capture matching hidraw reports when available. Default: enabled",
    )
    capture.add_argument(
        "--live-mode",
        choices=["summarized", "raw"],
        default="summarized",
        help="Live data retention mode. summarized keeps compact support snapshots; raw emits every event/report. Default: summarized",
    )
    capture.add_argument(
        "--max-report-bytes",
        type=_positive_int,
        default=4096,
        help="Maximum bytes retained from one hidraw report. Default: 4096",
    )
    capture.add_argument(
        "--max-file-bytes",
        type=_positive_int,
        default=65536,
        help="Maximum bytes retained from one sysfs metadata file. Default: 65536",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command != "capture":
        parser.error(f"Unhandled command: {args.command}")

    progress = _CliProgress()
    try:
        path = asyncio.run(
            capture_device(
                devices=args.devices,
                duration_sec=args.duration,
                output_path=args.output,
                grab=args.grab,
                include_hidraw=args.include_hidraw,
                max_report_bytes=args.max_report_bytes,
                max_sysfs_file_bytes=args.max_file_bytes,
                live_mode=args.live_mode,
                progress=progress,
            )
        )
    except KeyboardInterrupt:
        progress.finish_line()
        if progress.output_path is not None:
            warn("Received keyboard interrupt; finalizing partial capture.")
            ok(f"Wrote: {progress.output_path}")
            _print_capture_summary(progress.output_path, generated_output=args.output is None)
        else:
            warn("Received keyboard interrupt before a capture path was created.")
        return EXIT_INTERRUPTED
    except DeviceCaptureError as exc:
        progress.finish_line()
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        progress.finish_line()
        print(f"Device capture failed: {exc}", file=sys.stderr)
        return EXIT_ENVIRONMENT
    progress.finish_line()
    ok(f"Wrote: {path}")
    _print_capture_summary(path, generated_output=args.output is None)
    return EXIT_OK


def _print_capture_summary(path: Path, *, generated_output: bool) -> None:
    report = validate_capture(path, generated_output=generated_output)
    metrics = report.metrics
    live = "yes" if any(report.captured.get(key, False) for key in _LIVE_CAPTURE_FLAGS) else "no"
    info(
        "Capture summary: mode={mode} matched={matched} live={live} warnings={warnings}".format(
            mode=report.live_mode or "unknown",
            matched=metrics.get("matched_device_count", 0),
            live=live,
            warnings=len(report.warnings),
        )
    )
    if not report.valid:
        warn("Capture summary found structural issues; review the JSONL before sharing.")
    for warning in report.warnings:
        warn(f"Capture warning: {warning}")
    for error in report.errors:
        warn(f"Capture error: {error}")


_LIVE_CAPTURE_FLAGS = (
    "hidraw_report_raw",
    "hidraw_report_summary",
    "evdev_event_raw",
    "evdev_key_snapshot",
    "evdev_axis_snapshot",
    "evdev_sync_summary",
)


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


@dataclass
class _CliProgress:
    output_path: Path | None = None
    evdev_events: int = 0
    hidraw_reports: int = 0
    key_codes: set[str] = field(default_factory=set)
    rel_codes: set[str] = field(default_factory=set)
    abs_codes: set[str] = field(default_factory=set)
    hidraw_paths: set[str] = field(default_factory=set)
    _last_render_monotonic: float = 0.0
    _started_monotonic: float = 0.0
    _duration_sec: int = 0
    _live: Live | None = None
    _console: Console | None = None

    def capture_started(self, devices, output_path: Path, *, duration_sec: int) -> None:
        self.output_path = output_path
        self._duration_sec = duration_sec
        self._started_monotonic = time.monotonic()
        summaries = ", ".join(f"{getattr(device, 'path', '')} ({getattr(device, 'name', '')})" for device in devices)
        info(f"Capturing these matching devices: {summaries}")
        self._console = Console(stderr=True, highlight=False)
        self._live = Live(self, console=self._console, refresh_per_second=4, transient=False)
        self._live.start()

    def evdev_event(self, device, event: object) -> None:
        self.evdev_events += 1
        event_type = getattr(event, "type", None)
        code_name = _event_code_label(event)
        if event_type == ecodes.EV_KEY:
            self.key_codes.add(code_name)
        elif event_type == ecodes.EV_REL:
            self.rel_codes.add(code_name)
        elif event_type == ecodes.EV_ABS:
            self.abs_codes.add(code_name)
        self._render()

    def hidraw_report(self, path: Path, report: bytes) -> None:
        self.hidraw_reports += 1
        self.hidraw_paths.add(f"{path.name}:{len(report)}B")
        self._render()

    def capture_finished(self, output_path: Path, *, interrupted: bool) -> None:
        self.output_path = output_path
        self._render(force=True)

    def finish_line(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def _render(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_render_monotonic < 0.25:
            return
        self._last_render_monotonic = now
        if self._live is not None:
            self._live.update(self)

    def _render_text(self) -> str:
        return self._render_status().plain

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        del console, options
        yield self._render_status()

    def _render_status(self, *, now: float | None = None) -> Text:
        now = time.monotonic() if now is None else now
        elapsed_sec = max(0, int(now - self._started_monotonic)) if self._started_monotonic else 0
        duration_sec = max(0, self._duration_sec)
        remaining_sec = max(0, duration_sec - elapsed_sec) if duration_sec else 0
        frame = _SPINNER_FRAMES[int(now * 4) % len(_SPINNER_FRAMES)]
        axes = len(self.rel_codes) + len(self.abs_codes)
        status = Text()
        status.append(frame, style="cyan")
        status.append(" Waiting for input...", style="cyan")
        status.append("   ")
        status.append(
            _progress_indicator(elapsed_sec=elapsed_sec, duration_sec=duration_sec, remaining_sec=remaining_sec)
        )
        status.append("   |   ", style="white")
        _append_metric(status, "events", self.evdev_events)
        _append_metric(status, "keys", len(self.key_codes))
        _append_metric(status, "axes", axes)
        _append_metric(status, "hidraw", self.hidraw_reports)
        _append_metric(status, "groups", len(self.hidraw_paths))
        if self.output_path is not None and self.output_path.exists():
            _append_metric(status, "size", _format_bytes(self.output_path.stat().st_size), trailing=False)
        return status


def _progress_indicator(*, elapsed_sec: int, duration_sec: int, remaining_sec: int) -> Text:
    if duration_sec <= 0:
        return Text(f"[{'-' * _PROGRESS_WIDTH}] {elapsed_sec}s", style="cyan")
    filled = min(_PROGRESS_WIDTH, int((_PROGRESS_WIDTH * min(elapsed_sec, duration_sec)) / duration_sec))
    bar = "#" * filled + "-" * (_PROGRESS_WIDTH - filled)
    return Text(f"[{bar}] {remaining_sec}s", style="cyan")


def _append_metric(status: Text, label: str, value: object, *, trailing: bool = True) -> None:
    status.append(f"{label}=", style="yellow")
    status.append(str(value), style="cyan")
    if trailing:
        status.append("   ")


def _event_code_label(event: object) -> str:
    event_type = getattr(event, "type", None)
    code = getattr(event, "code", None)
    if isinstance(event_type, int) and isinstance(code, int):
        return _event_code_name(event_type, code)
    return str(code)


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    value = float(size)
    for unit in ("K", "M", "G"):
        value /= 1024
        if value < 1024 or unit == "G":
            return f"{value:.1f}{unit}"
    return f"{size}B"


@lru_cache(maxsize=512)
def _event_code_name(event_type: int, code: int) -> str:
    prefixes = {
        getattr(ecodes, "EV_KEY", None): ("KEY_", "BTN_"),
        getattr(ecodes, "EV_REL", None): ("REL_",),
        getattr(ecodes, "EV_ABS", None): ("ABS_",),
    }.get(event_type, ())
    for name in dir(ecodes):
        if name.startswith(prefixes) and getattr(ecodes, name) == code:
            return name
    return str(code)
