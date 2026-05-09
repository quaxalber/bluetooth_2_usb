from __future__ import annotations

import asyncio
import re
import socket
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TextIO

from ...evdev import ecodes
from ...evdev.types import InputDevice
from ..artifacts import make_user_copyable
from ..commands import timestamp
from ..diagnostics.redaction import redact
from . import linux
from .result import SCHEMA_VERSION, json_line

try:
    from evdev import ecodes as native_ecodes
except ModuleNotFoundError:
    native_ecodes = None

_LOCAL_EVENT_TYPE_NAMES = {
    getattr(ecodes, name): name
    for name in dir(ecodes)
    if name.startswith("EV_") and isinstance(getattr(ecodes, name), int)
}
_LOCAL_EVENT_CODE_PREFIXES = {
    getattr(ecodes, "EV_KEY", None): ("KEY_", "BTN_"),
    getattr(ecodes, "EV_REL", None): ("REL_",),
    getattr(ecodes, "EV_ABS", None): ("ABS_",),
    getattr(ecodes, "EV_MSC", None): ("MSC_",),
    getattr(ecodes, "EV_SYN", None): ("SYN_",),
}
_LOCAL_EVENT_CODE_NAMES = {
    event_type: {
        getattr(ecodes, name): name
        for name in dir(ecodes)
        if name.startswith(prefixes) and isinstance(getattr(ecodes, name), int)
    }
    for event_type, prefixes in _LOCAL_EVENT_CODE_PREFIXES.items()
    if event_type is not None
}

LiveMode = Literal["summarized", "raw"]
_AXIS_SAMPLE_LIMIT = 8
_HIDRAW_SAMPLE_LIMIT = 16


class JsonlWriter:
    def __init__(self, output_file: TextIO, *, hostname: str = "") -> None:
        self._output_file = output_file
        self._hostname = hostname
        self.counts: dict[str, int] = {}

    def write(self, record: dict[str, object], *, flush: bool = False) -> None:
        record_type = str(record.get("record_type", "unknown"))
        self.counts[record_type] = self.counts.get(record_type, 0) + 1
        self._output_file.write(redact(json_line(record), self._hostname))
        if flush:
            self._output_file.flush()


class CaptureProgress(Protocol):
    def capture_started(self, devices: list[InputDevice], output_path: Path, *, duration_sec: int) -> None: ...

    def evdev_event(self, device: InputDevice, event: object) -> None: ...

    def hidraw_report(self, path: Path, report: bytes) -> None: ...

    def capture_finished(self, output_path: Path, *, interrupted: bool) -> None: ...


@dataclass(slots=True)
class _CaptureHandle:
    device: InputDevice
    hidraw_nodes: list[Path]
    opened_hidraw: list[tuple[Path, int]]
    grabbed: bool = False


async def capture_device(
    *,
    devices: str,
    duration_sec: int,
    output_path: Path | None,
    grab: bool,
    include_hidraw: bool,
    max_report_bytes: int,
    max_sysfs_file_bytes: int,
    live_mode: LiveMode = "summarized",
    progress: CaptureProgress | None = None,
) -> Path:
    started_monotonic = time.monotonic()
    interrupted = False
    input_devices = linux.select_input_devices(devices)
    handles = [_CaptureHandle(device=device, hidraw_nodes=[], opened_hidraw=[]) for device in input_devices]

    try:
        output_path, created_parent = _prepare_capture_output(devices, input_devices, output_path, live_mode)
        hostname = socket.gethostname()
        with output_path.open("w", encoding="utf-8") as output_file:
            writer = JsonlWriter(output_file, hostname=hostname)
            writer_lock = asyncio.Lock()
            if progress is not None:
                progress.capture_started(input_devices, output_path, duration_sec=duration_sec)
            _write_capture_start(
                writer, duration_sec=duration_sec, live_mode=live_mode, devices_filter=devices, handles=handles
            )

            try:
                hidraw_report_id_paths = _prepare_capture_handles(
                    writer,
                    handles=handles,
                    grab=grab,
                    include_hidraw=include_hidraw,
                    max_sysfs_file_bytes=max_sysfs_file_bytes,
                )
                await asyncio.gather(
                    *(
                        _capture_live_records(
                            writer=writer,
                            device=handle.device,
                            opened_hidraw=handle.opened_hidraw,
                            duration_sec=duration_sec,
                            max_report_bytes=max_report_bytes,
                            live_mode=live_mode,
                            writer_lock=writer_lock,
                            hidraw_report_id_paths=hidraw_report_id_paths,
                            progress=progress,
                        )
                        for handle in handles
                    )
                )
            except (KeyboardInterrupt, asyncio.CancelledError):
                interrupted = True
                raise
            finally:
                _write_capture_end(writer, started_monotonic=started_monotonic, interrupted=interrupted)
                if progress is not None:
                    progress.capture_finished(output_path, interrupted=interrupted)
                make_user_copyable(output_path, created_parent=created_parent)
    finally:
        _close_capture_handles(handles)

    return output_path


def _prepare_capture_output(
    devices_filter: str, input_devices: list[InputDevice], output_path: Path | None, live_mode: LiveMode
) -> tuple[Path, Path | None]:
    output_path = output_path or _default_output_path(devices_filter, input_devices, live_mode)
    created_parent = output_path.parent if not output_path.parent.exists() else None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path, created_parent


def _write_capture_start(
    writer: JsonlWriter, *, duration_sec: int, live_mode: LiveMode, devices_filter: str, handles: list[_CaptureHandle]
) -> None:
    writer.write(
        {
            "record_type": "capture_start",
            "schema_version": SCHEMA_VERSION,
            "tool": "bluetooth_2_usb device capture",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_sec": duration_sec,
            "live_mode": live_mode,
            "devices": devices_filter,
            "matched_devices": [
                {"path": getattr(handle.device, "path", ""), "name": getattr(handle.device, "name", "")}
                for handle in handles
            ],
        },
        flush=True,
    )


def _write_capture_end(writer: JsonlWriter, *, started_monotonic: float, interrupted: bool) -> None:
    writer.write(
        {
            "record_type": "capture_end",
            "elapsed_sec": round(time.monotonic() - started_monotonic, 6),
            "interrupted": interrupted,
            "counts": dict(writer.counts),
        },
        flush=True,
    )


def _prepare_capture_handles(
    writer: JsonlWriter, *, handles: list[_CaptureHandle], grab: bool, include_hidraw: bool, max_sysfs_file_bytes: int
) -> set[Path]:
    opened_hidraw_paths: set[Path] = set()
    recorded_hidraw_paths: set[Path] = set()
    hidraw_report_id_paths: set[Path] = set()

    for handle in handles:
        _write_static_records(writer, handle.device, max_sysfs_file_bytes)
        if grab:
            _grab_capture_handle(writer, handle)
        if include_hidraw:
            _prepare_hidraw_nodes(
                writer,
                handle,
                recorded_hidraw_paths=recorded_hidraw_paths,
                opened_hidraw_paths=opened_hidraw_paths,
                hidraw_report_id_paths=hidraw_report_id_paths,
                max_sysfs_file_bytes=max_sysfs_file_bytes,
            )

    return hidraw_report_id_paths


def _grab_capture_handle(writer: JsonlWriter, handle: _CaptureHandle) -> None:
    handle.device.grab()
    handle.grabbed = True
    writer.write(
        {"record_type": "capture_note", "path": getattr(handle.device, "path", ""), "message": "grabbed input device"},
        flush=True,
    )


def _prepare_hidraw_nodes(
    writer: JsonlWriter,
    handle: _CaptureHandle,
    *,
    recorded_hidraw_paths: set[Path],
    opened_hidraw_paths: set[Path],
    hidraw_report_id_paths: set[Path],
    max_sysfs_file_bytes: int,
) -> None:
    handle.hidraw_nodes = linux.discover_hidraw_nodes(handle.device)
    nodes_to_record = [node for node in handle.hidraw_nodes if node not in recorded_hidraw_paths]
    if nodes_to_record:
        for record in linux.hidraw_node_records(nodes_to_record, max_sysfs_file_bytes):
            if _hidraw_node_uses_report_ids(record):
                hidraw_report_id_paths.add(Path(str(record.get("path", ""))))
            writer.write(record, flush=True)
        recorded_hidraw_paths.update(nodes_to_record)

    nodes_to_open = [node for node in handle.hidraw_nodes if node not in opened_hidraw_paths]
    if nodes_to_open:
        handle.opened_hidraw, warnings = linux.open_hidraw_nodes(nodes_to_open)
        opened_hidraw_paths.update(nodes_to_open)
    else:
        warnings = []
    for warning in warnings:
        writer.write(warning, flush=True)
    if not handle.hidraw_nodes:
        writer.write(
            {
                "record_type": "capture_warning",
                "source": "hidraw",
                "path": getattr(handle.device, "path", ""),
                "message": "no matching hidraw node discovered",
            },
            flush=True,
        )


def _close_capture_handles(handles: list[_CaptureHandle]) -> None:
    for handle in handles:
        if handle.grabbed:
            with suppress(Exception):
                handle.device.ungrab()
        linux.close_hidraw_nodes(handle.opened_hidraw)
        handle.device.close()


def _write_static_records(writer: JsonlWriter, device: InputDevice, max_sysfs_file_bytes: int) -> None:
    for record_factory in (linux.input_device_record, linux.evdev_capabilities_record, linux.udev_properties_record):
        try:
            writer.write(record_factory(device), flush=True)
        except Exception as exc:
            writer.write(
                {"record_type": "capture_warning", "source": record_factory.__name__, "message": str(exc)}, flush=True
            )
    writer.write(linux.sysfs_snapshot_record(device, max_sysfs_file_bytes), flush=True)


async def _capture_live_records(
    *,
    writer: JsonlWriter,
    device: InputDevice,
    opened_hidraw: list[tuple[Path, int]],
    duration_sec: int,
    max_report_bytes: int,
    live_mode: LiveMode,
    writer_lock: asyncio.Lock,
    hidraw_report_id_paths: set[Path],
    progress: CaptureProgress | None,
) -> None:
    deadline = time.monotonic() + duration_sec
    reader = device.async_read_loop().__aiter__()
    pending_event = _pending_event(reader)
    summaries = _LiveSummaries(device)
    active_hidraw = list(opened_hidraw)

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            done, _pending = await asyncio.wait({pending_event}, timeout=min(0.05, remaining))
            if pending_event in done:
                try:
                    event = pending_event.result()
                except StopAsyncIteration:
                    break
                except OSError as exc:
                    async with writer_lock:
                        writer.write(
                            {
                                "record_type": "capture_warning",
                                "source": "evdev",
                                "path": getattr(device, "path", ""),
                                "message": f"stopped reading input device: {exc}",
                            },
                            flush=True,
                        )
                    break
                if live_mode == "raw":
                    async with writer_lock:
                        writer.write(evdev_event_record(device, event), flush=True)
                else:
                    summaries.add_event(event)
                if progress is not None:
                    progress.evdev_event(device, event)
                pending_event = _pending_event(reader)

            next_active_hidraw: list[tuple[Path, int]] = []
            for path, fd in active_hidraw:
                while True:
                    try:
                        report = linux.read_hidraw(fd, max_report_bytes)
                    except OSError as exc:
                        async with writer_lock:
                            writer.write(
                                {
                                    "record_type": "capture_warning",
                                    "source": "hidraw",
                                    "path": str(path),
                                    "message": f"stopped reading hidraw node: {exc}",
                                },
                                flush=True,
                            )
                        break
                    if report is None:
                        next_active_hidraw.append((path, fd))
                        break
                    if not report:
                        next_active_hidraw.append((path, fd))
                        break
                    truncated = len(report) > max_report_bytes
                    if truncated:
                        report = report[:max_report_bytes]
                    if live_mode == "raw":
                        async with writer_lock:
                            writer.write(hidraw_report_record(path, report, truncated=truncated), flush=True)
                    else:
                        summaries.add_hidraw_report(
                            path, report, truncated=truncated, has_report_id=path in hidraw_report_id_paths
                        )
                    if progress is not None:
                        progress.hidraw_report(path, report)
            active_hidraw = next_active_hidraw
    finally:
        if live_mode == "summarized":
            async with writer_lock:
                for record in summaries.records():
                    writer.write(record, flush=True)


@dataclass(slots=True)
class _AxisSnapshot:
    path: str
    event_type: int
    code: int
    count: int = 0
    first_value: int | None = None
    last_value: int | None = None
    min_value: int | None = None
    max_value: int | None = None
    sum_value: int = 0
    sum_abs_value: int = 0
    changed_value_count: int = 0
    same_value_repeat_count: int = 0
    sample_values: list[int] | None = None
    sample_values_truncated: bool = False

    def add(self, value: int) -> None:
        if self.sample_values is None:
            self.sample_values = []
        previous = self.last_value
        self.count += 1
        if self.first_value is None:
            self.first_value = value
        self.last_value = value
        self.min_value = value if self.min_value is None else min(self.min_value, value)
        self.max_value = value if self.max_value is None else max(self.max_value, value)
        if self.event_type == ecodes.EV_REL:
            self.sum_value += value
            self.sum_abs_value += abs(value)
        if self.event_type == ecodes.EV_ABS and previous is not None:
            if previous == value:
                self.same_value_repeat_count += 1
            else:
                self.changed_value_count += 1
        elif self.event_type == ecodes.EV_ABS:
            self.changed_value_count += 1
        if previous != value:
            if len(self.sample_values) < _AXIS_SAMPLE_LIMIT:
                self.sample_values.append(value)
            else:
                self.sample_values_truncated = True

    def record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "record_type": "evdev_axis_snapshot",
            "path": self.path,
            "type": self.event_type,
            "type_name": _event_type_name(self.event_type),
            "code": self.code,
            "code_name": _event_code_name(self.event_type, self.code),
            "count": self.count,
            "first_value": self.first_value,
            "last_value": self.last_value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "sample_values": self.sample_values or [],
            "sample_values_truncated": self.sample_values_truncated,
        }
        if self.event_type == ecodes.EV_REL:
            record["sum_value"] = self.sum_value
            record["sum_abs_value"] = self.sum_abs_value
        if self.event_type == ecodes.EV_ABS:
            record["changed_value_count"] = self.changed_value_count
            record["same_value_repeat_count"] = self.same_value_repeat_count
        return record


@dataclass(slots=True)
class _KeySnapshot:
    path: str
    code: int
    press_count: int = 0
    release_count: int = 0
    repeat_count: int = 0
    first_value: int | None = None
    last_value: int | None = None

    def add(self, value: int) -> None:
        if self.first_value is None:
            self.first_value = value
        self.last_value = value
        if value == 0:
            self.release_count += 1
        elif value == 1:
            self.press_count += 1
        elif value == 2:
            self.repeat_count += 1

    def record(self) -> dict[str, object]:
        return {
            "record_type": "evdev_key_snapshot",
            "path": self.path,
            "type": ecodes.EV_KEY,
            "type_name": _event_type_name(ecodes.EV_KEY),
            "code": self.code,
            "code_name": _event_code_name(ecodes.EV_KEY, self.code),
            "press_count": self.press_count,
            "release_count": self.release_count,
            "repeat_count": self.repeat_count,
            "first_value": self.first_value,
            "last_value": self.last_value,
        }


@dataclass(slots=True)
class _SyncSnapshot:
    path: str
    syn_report_count: int = 0
    syn_dropped_count: int = 0
    other_sync_counts: dict[str, int] | None = None

    def add(self, code: int) -> None:
        if code == ecodes.SYN_REPORT:
            self.syn_report_count += 1
        elif code == ecodes.SYN_DROPPED:
            self.syn_dropped_count += 1
        else:
            if self.other_sync_counts is None:
                self.other_sync_counts = {}
            code_name = _event_code_name(ecodes.EV_SYN, code) or str(code)
            self.other_sync_counts[code_name] = self.other_sync_counts.get(code_name, 0) + 1

    def record(self) -> dict[str, object]:
        return {
            "record_type": "evdev_sync_summary",
            "path": self.path,
            "syn_report_count": self.syn_report_count,
            "syn_dropped_count": self.syn_dropped_count,
            "other_sync_counts": self.other_sync_counts or {},
        }


@dataclass(slots=True)
class _HidrawGroupSnapshot:
    path: Path
    report_id: int | None
    length: int
    count: int = 0
    exact_duplicate_count: int = 0
    truncated_report_count: int = 0
    sample_reports: list[bytes] | None = None
    seen_reports: set[bytes] | None = None
    sample_reports_truncated: bool = False
    changed_byte_indexes: set[int] | None = None
    byte_values: list[int | None] | None = None

    def add(self, report: bytes, *, truncated: bool) -> None:
        if self.sample_reports is None:
            self.sample_reports = []
        if self.seen_reports is None:
            self.seen_reports = set()
        if self.changed_byte_indexes is None:
            self.changed_byte_indexes = set()
        if self.byte_values is None:
            self.byte_values = [None] * len(report)

        self.count += 1
        if truncated:
            self.truncated_report_count += 1
        if report in self.seen_reports:
            self.exact_duplicate_count += 1
        else:
            self.seen_reports.add(report)
            if len(self.sample_reports) < _HIDRAW_SAMPLE_LIMIT:
                self.sample_reports.append(report)
            else:
                self.sample_reports_truncated = True
        for index, byte in enumerate(report):
            previous = self.byte_values[index]
            if previous is None:
                self.byte_values[index] = byte
            elif previous != byte:
                self.changed_byte_indexes.add(index)

    def record(self) -> dict[str, object]:
        return {
            "record_type": "hidraw_report_group_summary",
            "path": str(self.path),
            "report_id": self.report_id,
            "length": self.length,
            "count": self.count,
            "exact_duplicate_count": self.exact_duplicate_count,
            "unique_report_count": len(self.seen_reports or ()),
            "sample_reports": [report.hex(" ") for report in self.sample_reports or []],
            "sample_reports_truncated": self.sample_reports_truncated,
            "changed_byte_indexes": sorted(self.changed_byte_indexes or ()),
            "truncated_report_count": self.truncated_report_count,
        }


class _LiveSummaries:
    def __init__(self, device: InputDevice) -> None:
        self._path = getattr(device, "path", "")
        self._axes: dict[tuple[int, int], _AxisSnapshot] = {}
        self._keys: dict[int, _KeySnapshot] = {}
        self._sync: _SyncSnapshot | None = None
        self._hidraw: dict[tuple[Path, int | None, int], _HidrawGroupSnapshot] = {}

    def add_event(self, event: object) -> None:
        event_type = getattr(event, "type", None)
        code = getattr(event, "code", None)
        value = getattr(event, "value", None)
        if not isinstance(event_type, int) or not isinstance(code, int) or not isinstance(value, int):
            return
        if event_type in (ecodes.EV_REL, ecodes.EV_ABS):
            key = (event_type, code)
            snapshot = self._axes.get(key)
            if snapshot is None:
                snapshot = _AxisSnapshot(path=self._path, event_type=event_type, code=code)
                self._axes[key] = snapshot
            snapshot.add(value)
        elif event_type == ecodes.EV_KEY:
            snapshot = self._keys.get(code)
            if snapshot is None:
                snapshot = _KeySnapshot(path=self._path, code=code)
                self._keys[code] = snapshot
            snapshot.add(value)
        elif event_type == ecodes.EV_SYN:
            if self._sync is None:
                self._sync = _SyncSnapshot(path=self._path)
            self._sync.add(code)

    def add_hidraw_report(self, path: Path, report: bytes, *, truncated: bool, has_report_id: bool) -> None:
        report_id = report[0] if has_report_id and report else None
        key = (path, report_id, len(report))
        snapshot = self._hidraw.get(key)
        if snapshot is None:
            snapshot = _HidrawGroupSnapshot(path=path, report_id=report_id, length=len(report))
            self._hidraw[key] = snapshot
        snapshot.add(report, truncated=truncated)

    def records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        records.extend(self._axes[key].record() for key in sorted(self._axes))
        records.extend(self._keys[key].record() for key in sorted(self._keys))
        if self._sync is not None:
            records.append(self._sync.record())
        records.extend(
            self._hidraw[key].record()
            for key in sorted(self._hidraw, key=lambda item: (str(item[0]), item[1] or -1, item[2]))
        )
        return records


def _hidraw_node_uses_report_ids(record: dict[str, object]) -> bool:
    for file_record in record.get("files", []):
        if not isinstance(file_record, dict):
            continue
        path = str(file_record.get("path", ""))
        if not path.endswith("report_descriptor"):
            continue
        hex_text = file_record.get("hex")
        if not isinstance(hex_text, str):
            continue
        try:
            descriptor = bytes.fromhex(hex_text)
        except ValueError:
            continue
        if _report_descriptor_uses_report_ids(descriptor):
            return True
    return False


def _report_descriptor_uses_report_ids(descriptor: bytes) -> bool:
    index = 0
    while index < len(descriptor):
        prefix = descriptor[index]
        index += 1
        if prefix == 0xFE:
            if index + 1 >= len(descriptor):
                return False
            data_size = descriptor[index]
            index += 2 + data_size
            continue
        data_size_code = prefix & 0x03
        data_size = 4 if data_size_code == 3 else data_size_code
        item_type = prefix & 0x0C
        item_tag = prefix & 0xF0
        if item_type == 0x04 and item_tag == 0x80:
            return True
        index += data_size
    return False


def _pending_event(reader: object) -> asyncio.Future:
    pending = asyncio.ensure_future(reader.__anext__())
    pending.add_done_callback(_drain_late_reader_exception)
    return pending


def _drain_late_reader_exception(future: asyncio.Future) -> None:
    if future.cancelled():
        return
    with suppress(Exception):
        future.exception()


def evdev_event_record(device: InputDevice, event: object) -> dict[str, object]:
    event_type = getattr(event, "type", None)
    code = getattr(event, "code", None)
    value = getattr(event, "value", None)
    return {
        "record_type": "evdev_event",
        "monotonic": round(time.monotonic(), 6),
        "path": getattr(device, "path", ""),
        "sec": getattr(event, "sec", None),
        "usec": getattr(event, "usec", None),
        "type": event_type,
        "type_name": _event_type_name(event_type),
        "code": code,
        "code_name": _event_code_name(event_type, code),
        "value": value,
    }


def hidraw_report_record(path: Path, report: bytes, *, truncated: bool) -> dict[str, object]:
    return {
        "record_type": "hidraw_report",
        "monotonic": round(time.monotonic(), 6),
        "path": str(path),
        "length": len(report),
        "report": report.hex(" "),
        "truncated": truncated,
    }


def _event_type_name(event_type: int | None) -> str | None:
    if event_type is None:
        return None
    native_ev = getattr(native_ecodes, "EV", None)
    if isinstance(native_ev, dict) and event_type in native_ev:
        return native_ev[event_type]
    if event_type in _LOCAL_EVENT_TYPE_NAMES:
        return _LOCAL_EVENT_TYPE_NAMES[event_type]
    return f"EV_{event_type}"


def _event_code_name(event_type: int | None, code: int | None) -> str | None:
    if event_type is None or code is None:
        return None
    native_bytype = getattr(native_ecodes, "bytype", None)
    if isinstance(native_bytype, dict):
        mapping = native_bytype.get(event_type)
        if isinstance(mapping, dict) and code in mapping:
            value = mapping[code]
            if isinstance(value, list | tuple):
                return "/".join(str(item) for item in value)
            return str(value)
    local_names = _LOCAL_EVENT_CODE_NAMES.get(event_type)
    if local_names is not None and code in local_names:
        return local_names[code]
    return str(code)


def _default_output_path(devices_filter: str, devices: list[InputDevice], live_mode: LiveMode) -> Path:
    source = _device_name_source(devices) or "device"
    slug = _slug(source) or "device"
    mode_suffix = "_raw" if live_mode == "raw" else ""
    return Path.cwd() / "device_capture" / f"{slug}{mode_suffix}_{timestamp()}.jsonl"


def _device_name_source(devices: list[InputDevice]) -> str:
    names = _unique_device_names(devices)
    if not names:
        return ""
    common_prefix = _common_name_prefix(names)
    if common_prefix:
        return common_prefix
    return "_".join(names[:2])


def _unique_device_names(devices: list[InputDevice]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for device in devices:
        name = getattr(device, "name", "")
        if not name:
            continue
        normalized = _slug(name)
        if normalized in seen:
            continue
        seen.add(normalized)
        names.append(name)
    return names


def _common_name_prefix(names: list[str]) -> str:
    if len(names) < 2:
        return names[0] if names else ""
    tokenized = [name.split() for name in names]
    prefix: list[str] = []
    for tokens in zip(*tokenized, strict=False):
        lowered = {token.lower() for token in tokens}
        if len(lowered) != 1:
            break
        prefix.append(tokens[0])
    if len(prefix) < 2:
        return ""
    if all(len(prefix) == len(tokens) for tokens in tokenized):
        return names[0]
    return " ".join(prefix)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug[:80].strip("_")
