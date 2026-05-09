from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from ...evdev import ecodes
from ..diagnostics.redaction import redact
from .result import SCHEMA_VERSION

KNOWN_RECORD_TYPES = {
    "capture_start",
    "capture_end",
    "capture_note",
    "capture_warning",
    "input_device",
    "evdev_capabilities",
    "evdev_input_properties",
    "udev_properties",
    "sysfs_snapshot",
    "hidraw_node",
    "evdev_event",
    "hidraw_report",
    "evdev_axis_snapshot",
    "evdev_key_snapshot",
    "evdev_misc_snapshot",
    "evdev_event_type_summary",
    "evdev_sample_sequence",
    "evdev_sync_summary",
    "hidraw_report_group_summary",
}


@dataclass(slots=True)
class CaptureValidationReport:
    path: str
    valid: bool
    schema_version: int | None
    live_mode: str | None
    duration_sec: int | None
    started_at: str | None
    elapsed_sec: float | None
    interrupted: bool | None
    line_count: int
    parse_error_count: int
    record_counts: dict[str, int]
    matched_devices: list[dict[str, object]]
    captured: dict[str, bool]
    metrics: dict[str, object]
    warnings: list[str]
    errors: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def validate_capture(path: Path, *, generated_output: bool = False) -> CaptureValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    records: list[dict[str, object]] = []
    line_count = 0
    parse_error_count = 0
    redaction_change_count = 0

    try:
        file_size_bytes = path.stat().st_size
    except OSError as exc:
        return _report(path=path, errors=[f"cannot read capture file: {exc}"])
    if not path.is_file():
        return _report(path=path, errors=["capture path is not a file"], file_size_bytes=file_size_bytes)

    try:
        with path.open("r", encoding="utf-8") as capture_file:
            for line_count, line in enumerate(capture_file, 1):
                if redact(line, "") != line:
                    redaction_change_count += 1
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    parse_error_count += 1
                    errors.append(f"line {line_count}: invalid JSON: {exc.msg}")
                    continue
                if not isinstance(value, dict):
                    errors.append(f"line {line_count}: record is not a JSON object")
                    continue
                records.append(value)
    except OSError as exc:
        return _report(path=path, errors=[f"cannot read capture file: {exc}"], file_size_bytes=file_size_bytes)

    if line_count == 0:
        errors.append("capture file is empty")

    start = records[0] if records else {}
    end = _last_record(records, "capture_end")
    if records and start.get("record_type") != "capture_start":
        errors.append("first record is not capture_start")
    if end is None:
        errors.append("missing capture_end record")

    schema_version = _int_or_none(start.get("schema_version"))
    if schema_version != SCHEMA_VERSION:
        errors.append(f"unsupported or missing schema_version: {schema_version!r}")
    live_mode = _str_or_none(start.get("live_mode"))
    if live_mode not in {"summarized", "raw", None}:
        errors.append(f"unsupported live_mode: {live_mode!r}")
    elif live_mode is None and records:
        errors.append("missing live_mode")

    record_counts = Counter(str(record.get("record_type", "unknown")) for record in records)
    if end is not None and isinstance(end.get("counts"), dict):
        expected_counts = {
            str(key): int(value) for key, value in end["counts"].items() if _int_or_none(value) is not None
        }
        for record_type in sorted(set(expected_counts) | set(record_counts)):
            expected = expected_counts.get(record_type)
            actual = record_counts.get(record_type, 0)
            if expected is not None and expected != actual:
                errors.append(f"capture_end count mismatch for {record_type}: expected {expected}, saw {actual}")

    matched_devices = _matched_devices(start.get("matched_devices"))
    duration_sec = _int_or_none(start.get("duration_sec"))
    elapsed_sec = _float_or_none(end.get("elapsed_sec") if end else None)
    interrupted = end.get("interrupted") if end and isinstance(end.get("interrupted"), bool) else None
    unknown_record_types = sorted(record_type for record_type in record_counts if record_type not in KNOWN_RECORD_TYPES)
    warning_records = [record for record in records if record.get("record_type") == "capture_warning"]

    if interrupted:
        warnings.append("capture was interrupted")
    if duration_sec is None or duration_sec <= 0:
        warnings.append("duration_sec is missing or non-positive")
    if elapsed_sec is None:
        warnings.append("elapsed_sec is missing")
    if not matched_devices:
        warnings.append("no matched devices recorded")
    for required_type in (
        "input_device",
        "evdev_capabilities",
        "evdev_input_properties",
        "udev_properties",
        "sysfs_snapshot",
    ):
        if record_counts.get(required_type, 0) == 0:
            warnings.append(f"missing {required_type} records")

    has_live = any(record_counts.get(record_type, 0) for record_type in _live_record_types())
    if not has_live:
        warnings.append("no live input evidence captured")

    unique_key_codes = _unique_codes(records, ecodes.EV_KEY)
    unique_rel_codes = _unique_codes(records, ecodes.EV_REL)
    unique_abs_codes = _unique_codes(records, ecodes.EV_ABS)
    unique_msc_codes = _unique_codes(records, ecodes.EV_MSC)
    if warning_records:
        for record in warning_records:
            message = str(record.get("message") or "capture warning")
            warnings.append(message)
    if unknown_record_types:
        warnings.append(f"unknown record types: {', '.join(unknown_record_types)}")
    if redaction_change_count:
        warnings.append(f"{redaction_change_count} lines still contain diagnostics-redactable values")

    filename_has_raw_suffix = "_raw_" in path.name
    filename_expected_raw_suffix = live_mode == "raw"
    if generated_output:
        if live_mode == "raw" and not filename_has_raw_suffix:
            warnings.append("raw capture filename is missing _raw suffix")
        if live_mode == "summarized" and filename_has_raw_suffix:
            warnings.append("summarized capture filename contains _raw suffix")
        if not _generated_filename(path.name):
            warnings.append("filename does not match generated naming scheme")

    if file_size_bytes > 5 * 1024 * 1024:
        notes.append(f"large capture file: {_format_bytes(file_size_bytes)}")
    if len(matched_devices) > 1:
        notes.append(f"multiple matched devices: {len(matched_devices)}")
    if any(
        record.get("record_type") == "capture_note" and record.get("message") == "grabbed input device"
        for record in records
    ):
        notes.append("input devices were grabbed during capture")

    captured = {
        "capture_start": record_counts.get("capture_start", 0) > 0,
        "capture_end": record_counts.get("capture_end", 0) > 0,
        "input_device": record_counts.get("input_device", 0) > 0,
        "evdev_capabilities": record_counts.get("evdev_capabilities", 0) > 0,
        "evdev_input_properties": record_counts.get("evdev_input_properties", 0) > 0,
        "udev_properties": record_counts.get("udev_properties", 0) > 0,
        "sysfs_snapshot": record_counts.get("sysfs_snapshot", 0) > 0,
        "grabbed": any(
            record.get("record_type") == "capture_note" and record.get("message") == "grabbed input device"
            for record in records
        ),
        "hidraw_node": record_counts.get("hidraw_node", 0) > 0,
        "hidraw_report_raw": record_counts.get("hidraw_report", 0) > 0,
        "hidraw_report_summary": record_counts.get("hidraw_report_group_summary", 0) > 0,
        "evdev_event_raw": record_counts.get("evdev_event", 0) > 0,
        "evdev_key_snapshot": record_counts.get("evdev_key_snapshot", 0) > 0,
        "evdev_axis_snapshot": record_counts.get("evdev_axis_snapshot", 0) > 0,
        "evdev_misc_snapshot": record_counts.get("evdev_misc_snapshot", 0) > 0,
        "evdev_event_type_summary": record_counts.get("evdev_event_type_summary", 0) > 0,
        "evdev_sample_sequence": record_counts.get("evdev_sample_sequence", 0) > 0,
        "evdev_sync_summary": record_counts.get("evdev_sync_summary", 0) > 0,
    }
    unique_paths = sorted(
        str(record.get("path")) for record in records if isinstance(record.get("path"), str) and record.get("path")
    )
    metrics: dict[str, object] = {
        "file_size_bytes": file_size_bytes,
        "matched_device_count": len(matched_devices),
        "line_count": line_count,
        "record_counts": dict(sorted(record_counts.items())),
        "unique_paths": sorted(set(unique_paths)),
        "unique_key_codes": sorted(unique_key_codes),
        "unique_rel_codes": sorted(unique_rel_codes),
        "unique_abs_codes": sorted(unique_abs_codes),
        "unique_msc_codes": sorted(unique_msc_codes),
        "input_properties_count": record_counts.get("evdev_input_properties", 0),
        "axis_snapshot_count": record_counts.get("evdev_axis_snapshot", 0),
        "key_snapshot_count": record_counts.get("evdev_key_snapshot", 0),
        "misc_snapshot_count": record_counts.get("evdev_misc_snapshot", 0),
        "event_type_summary_count": record_counts.get("evdev_event_type_summary", 0),
        "sample_sequence_count": record_counts.get("evdev_sample_sequence", 0),
        "raw_evdev_event_count": record_counts.get("evdev_event", 0),
        "raw_hidraw_report_count": record_counts.get("hidraw_report", 0),
        "hidraw_summary_count": record_counts.get("hidraw_report_group_summary", 0),
        "capture_warning_count": record_counts.get("capture_warning", 0),
        "unknown_record_types": unknown_record_types,
        "filename_expected_raw_suffix": filename_expected_raw_suffix,
        "filename_has_raw_suffix": filename_has_raw_suffix,
        "redaction_change_count": redaction_change_count,
    }
    return CaptureValidationReport(
        path=str(path),
        valid=not errors,
        schema_version=schema_version,
        live_mode=live_mode,
        duration_sec=duration_sec,
        started_at=_str_or_none(start.get("started_at")),
        elapsed_sec=elapsed_sec,
        interrupted=interrupted,
        line_count=line_count,
        parse_error_count=parse_error_count,
        record_counts=dict(sorted(record_counts.items())),
        matched_devices=matched_devices,
        captured=captured,
        metrics=metrics,
        warnings=warnings,
        errors=errors,
        notes=notes,
    )


def _report(path: Path, *, errors: list[str], file_size_bytes: int | None = None) -> CaptureValidationReport:
    return CaptureValidationReport(
        path=str(path),
        valid=False,
        schema_version=None,
        live_mode=None,
        duration_sec=None,
        started_at=None,
        elapsed_sec=None,
        interrupted=None,
        line_count=0,
        parse_error_count=0,
        record_counts={},
        matched_devices=[],
        captured={},
        metrics={"file_size_bytes": file_size_bytes or 0},
        warnings=[],
        errors=errors,
        notes=[],
    )


def _last_record(records: list[dict[str, object]], record_type: str) -> dict[str, object] | None:
    for record in reversed(records):
        if record.get("record_type") == record_type:
            return record
    return None


def _matched_devices(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _live_record_types() -> tuple[str, ...]:
    return (
        "evdev_event",
        "hidraw_report",
        "evdev_axis_snapshot",
        "evdev_key_snapshot",
        "evdev_misc_snapshot",
        "evdev_event_type_summary",
        "evdev_sample_sequence",
        "evdev_sync_summary",
        "hidraw_report_group_summary",
    )


def _unique_codes(records: list[dict[str, object]], event_type: int) -> set[str]:
    codes: set[str] = set()
    for record in records:
        record_type = record.get("record_type")
        if record_type == "evdev_event" and record.get("type") != event_type:
            continue
        if record_type == "evdev_axis_snapshot" and record.get("type") != event_type:
            continue
        if record_type == "evdev_key_snapshot" and event_type != ecodes.EV_KEY:
            continue
        if record_type == "evdev_misc_snapshot" and event_type != ecodes.EV_MSC:
            continue
        if record_type not in {"evdev_event", "evdev_axis_snapshot", "evdev_key_snapshot", "evdev_misc_snapshot"}:
            continue
        code = record.get("code_name") or record.get("code")
        if code is not None:
            codes.add(str(code))
    return codes


def _generated_filename(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_]+(?:_raw)?_\d{8}_\d{6}\.jsonl", name))


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _format_bytes(size: int) -> str:
    units = ("B", "K", "M", "G")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}" if unit != "B" else f"{size}B"
        value /= 1024
    return f"{size}B"
