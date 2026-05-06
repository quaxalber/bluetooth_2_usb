import asyncio
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bluetooth_2_usb import cli
from bluetooth_2_usb.ops.devices import collector
from bluetooth_2_usb.ops.devices.cli import _CliProgress
from bluetooth_2_usb.ops.devices.cli import run as run_device
from bluetooth_2_usb.ops.devices.linux import (
    DeviceSelectionError,
    _hidraw_device_node,
    read_bounded_bytes,
    select_input_device,
    select_input_devices,
)
from bluetooth_2_usb.ops.devices.result import json_line, normalize
from bluetooth_2_usb.ops.devices.validate import validate_capture


class _FakeInputDevice:
    def __init__(self, path: str, name: str, *, uniq: str = "", events: list[object] | None = None) -> None:
        self.path = path
        self.name = name
        self.phys = f"{name}-phys"
        self.uniq = uniq
        self.version = 1
        self.info = SimpleNamespace(bustype=5, vendor=1, product=2, version=3)
        self.closed = False
        self.grabbed = False
        self.ungrabbed = False
        self._events = list(events or [])

    def capabilities(self, verbose=True):
        return {1: [(30, "KEY_A")]}

    def async_read_loop(self):
        events = list(self._events)

        class _Reader:
            def __aiter__(self):
                return self

            async def __anext__(self):
                if not events:
                    await asyncio.sleep(60)
                return events.pop(0)

        return _Reader()

    def grab(self):
        self.grabbed = True

    def ungrab(self):
        self.ungrabbed = True

    def close(self):
        self.closed = True


class _FutureInputDevice(_FakeInputDevice):
    def async_read_loop(self):
        event = SimpleNamespace(sec=1, usec=2, type=1, code=30, value=1)
        emitted = False

        class _Reader:
            def __aiter__(self):
                return self

            def __anext__(self):
                nonlocal emitted
                future = asyncio.get_running_loop().create_future()
                if emitted:
                    future.set_exception(StopAsyncIteration())
                else:
                    emitted = True
                    future.set_result(event)
                return future

        return _Reader()


class _CancelledInputDevice(_FakeInputDevice):
    def async_read_loop(self):
        event = SimpleNamespace(sec=1, usec=2, type=3, code=1, value=42)
        emitted = False

        class _Reader:
            def __aiter__(self):
                return self

            async def __anext__(self):
                nonlocal emitted
                if emitted:
                    raise asyncio.CancelledError
                emitted = True
                return event

        return _Reader()


class _PendingFutureInputDevice(_FakeInputDevice):
    def __init__(self, path: str, name: str) -> None:
        super().__init__(path, name)
        self.pending_future = None

    def async_read_loop(self):
        device = self

        class _Reader:
            def __aiter__(self):
                return self

            def __anext__(self):
                device.pending_future = asyncio.get_running_loop().create_future()
                return device.pending_future

        return _Reader()


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json_line(record) for record in records), encoding="utf-8")


def _minimal_capture_records(*, live_mode: str = "summarized", warning: str | None = None) -> list[dict[str, object]]:
    records: list[dict[str, object]] = [
        {
            "record_type": "capture_start",
            "schema_version": 1,
            "tool": "bluetooth_2_usb device capture",
            "started_at": "2026-05-06T01:02:03Z",
            "duration_sec": 30,
            "live_mode": live_mode,
            "devices": "/dev/input/event1",
            "matched_devices": [{"path": "/dev/input/event1", "name": "Keyboard"}],
        },
        {"record_type": "input_device", "path": "/dev/input/event1", "name": "Keyboard"},
        {"record_type": "evdev_capabilities", "path": "/dev/input/event1", "capabilities": {}},
        {"record_type": "udev_properties", "path": "/dev/input/event1", "properties": {}},
        {"record_type": "sysfs_snapshot", "path": "/dev/input/event1", "files": []},
        {"record_type": "capture_note", "path": "/dev/input/event1", "message": "grabbed input device"},
    ]
    if live_mode == "raw":
        records.append(
            {
                "record_type": "evdev_event",
                "path": "/dev/input/event1",
                "type": 1,
                "type_name": "EV_KEY",
                "code": 30,
                "code_name": "KEY_A",
                "value": 1,
            }
        )
    else:
        records.extend(
            [
                {
                    "record_type": "evdev_key_snapshot",
                    "path": "/dev/input/event1",
                    "type": 1,
                    "type_name": "EV_KEY",
                    "code": 30,
                    "code_name": "KEY_A",
                },
                {
                    "record_type": "evdev_axis_snapshot",
                    "path": "/dev/input/event1",
                    "type": 2,
                    "type_name": "EV_REL",
                    "code": 0,
                    "code_name": "REL_X",
                },
                {"record_type": "evdev_sync_summary", "path": "/dev/input/event1", "syn_report_count": 1},
            ]
        )
    if warning is not None:
        records.append({"record_type": "capture_warning", "source": "hidraw", "message": warning})
    counts: dict[str, int] = {}
    for record in records:
        record_type = str(record["record_type"])
        counts[record_type] = counts.get(record_type, 0) + 1
    records.append({"record_type": "capture_end", "elapsed_sec": 30.0, "interrupted": False, "counts": counts})
    return records


class DeviceCaptureTest(unittest.TestCase):
    def test_top_level_device_command_delegates_to_device_cli(self) -> None:
        with patch("bluetooth_2_usb.ops.devices.run", return_value=23) as device_run:
            exit_code = cli.run(["device", "capture", "--devices", "/dev/input/event1"])

        self.assertEqual(exit_code, 23)
        device_run.assert_called_once_with(["capture", "--devices", "/dev/input/event1"])

    def test_device_capture_help_does_not_load_usb_hid(self) -> None:
        stdout = io.StringIO()
        with patch("sys.stdout", stdout), self.assertRaises(SystemExit) as raised:
            run_device(["capture", "--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--devices DEVICE", stdout.getvalue())
        self.assertIn("--live-mode", stdout.getvalue())

    def test_device_capture_defaults_to_summarized_live_mode(self) -> None:
        with (
            patch("bluetooth_2_usb.ops.devices.cli.capture_device", return_value=Path("/tmp/capture.jsonl")) as capture,
            patch("bluetooth_2_usb.ops.devices.cli._print_capture_summary"),
        ):
            exit_code = run_device(["capture", "--devices", "/dev/input/event1"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(capture.call_args.kwargs["live_mode"], "summarized")

    def test_device_capture_accepts_raw_live_mode(self) -> None:
        with (
            patch("bluetooth_2_usb.ops.devices.cli.capture_device", return_value=Path("/tmp/capture.jsonl")) as capture,
            patch("bluetooth_2_usb.ops.devices.cli._print_capture_summary"),
        ):
            exit_code = run_device(["capture", "--devices", "/dev/input/event1", "--live-mode", "raw"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(capture.call_args.kwargs["live_mode"], "raw")

    def test_device_validate_is_not_public_command(self) -> None:
        stderr = io.StringIO()
        with patch("sys.stderr", stderr), self.assertRaises(SystemExit) as raised:
            run_device(["validate", "--help"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())

    def test_device_capture_prints_internal_validation_summary(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            _write_jsonl(output, _minimal_capture_records())
            with (
                patch("bluetooth_2_usb.ops.devices.cli.capture_device", return_value=output),
                patch("sys.stdout", stdout),
            ):
                exit_code = run_device(["capture", "--devices", "/dev/input/event1", "--output", str(output)])

        self.assertEqual(exit_code, 0)
        self.assertIn("Capture summary: mode=summarized matched=1 live=yes warnings=0", stdout.getvalue())

    def test_capture_progress_status_line_stays_compact(self) -> None:
        progress = _CliProgress()
        progress.evdev_events = 12
        progress.hidraw_reports = 3
        progress.key_codes.update({"KEY_A", "BTN_LEFT"})
        progress.rel_codes.add("REL_X")
        progress.abs_codes.add("ABS_X")
        progress.hidraw_paths.add("hidraw0:8B")

        line = progress._render_text()

        self.assertEqual(line, "events=12 keys=2 axes=2 hidraw=3 groups=1")

    def test_select_input_device_accepts_exact_path_and_closes_nonmatches(self) -> None:
        selected = _FakeInputDevice("/dev/input/event1", "Keyboard")
        other = _FakeInputDevice("/dev/input/event2", "Mouse")

        with patch("bluetooth_2_usb.ops.devices.linux.list_input_devices", return_value=[selected, other]):
            result = select_input_device("/dev/input/event1")

        self.assertIs(result, selected)
        self.assertFalse(selected.closed)
        self.assertTrue(other.closed)

    def test_capture_reports_output_open_failure_cleanly(self) -> None:
        stderr = io.StringIO()

        with (
            patch("bluetooth_2_usb.ops.devices.cli.capture_device", side_effect=PermissionError("denied")),
            patch("sys.stderr", stderr),
        ):
            exit_code = run_device(["capture", "--devices", "/dev/input/event1"])

        self.assertEqual(exit_code, 3)
        self.assertIn("Device capture failed: denied", stderr.getvalue())

    def test_capture_reports_interrupted_partial_output_path(self) -> None:
        stderr = io.StringIO()

        with (
            patch("bluetooth_2_usb.ops.devices.cli.capture_device", side_effect=KeyboardInterrupt),
            patch("sys.stderr", stderr),
        ):
            exit_code = run_device(["capture", "--devices", "/dev/input/event1"])

        self.assertEqual(exit_code, 130)
        self.assertIn("Device capture interrupted", stderr.getvalue())

    def test_select_input_devices_returns_all_name_matches(self) -> None:
        devices = [_FakeInputDevice("/dev/input/event1", "Keyboard"), _FakeInputDevice("/dev/input/event2", "Keyboard")]

        with patch("bluetooth_2_usb.ops.devices.linux.list_input_devices", return_value=devices):
            matches = select_input_devices("key")

        self.assertEqual(matches, devices)
        self.assertFalse(any(device.closed for device in devices))

    def test_select_input_device_keeps_single_device_ambiguity_error_for_callers_that_need_one(self) -> None:
        devices = [_FakeInputDevice("/dev/input/event1", "Keyboard"), _FakeInputDevice("/dev/input/event2", "Keyboard")]

        with patch("bluetooth_2_usb.ops.devices.linux.list_input_devices", return_value=devices):
            with self.assertRaisesRegex(DeviceSelectionError, "Multiple input devices matched"):
                select_input_device("key")

        self.assertTrue(all(device.closed for device in devices))

    def test_select_input_device_reports_missing_match(self) -> None:
        devices = [_FakeInputDevice("/dev/input/event1", "Keyboard")]

        with patch("bluetooth_2_usb.ops.devices.linux.list_input_devices", return_value=devices):
            with self.assertRaisesRegex(DeviceSelectionError, "No input device matched"):
                select_input_device("mouse")

        self.assertTrue(devices[0].closed)

    def test_json_line_normalizes_paths_bytes_and_unknown_objects(self) -> None:
        record = json.loads(json_line({"path": Path("/tmp/x"), "payload": b"\x01\x02", "obj": object()}))

        self.assertEqual(record["path"], "/tmp/x")
        self.assertEqual(record["payload"], "01 02")
        self.assertIsInstance(record["obj"], str)
        self.assertEqual(normalize({Path("/tmp/x")}), ["/tmp/x"])

    def test_repeated_evdev_events_are_serialized_as_distinct_records(self) -> None:
        device = _FakeInputDevice("/dev/input/event1", "Keyboard")
        event = SimpleNamespace(sec=1, usec=2, type=1, code=30, value=1)

        records = [collector.evdev_event_record(device, event), collector.evdev_event_record(device, event)]

        self.assertEqual([record["record_type"] for record in records], ["evdev_event", "evdev_event"])
        self.assertEqual(records[0]["code"], records[1]["code"])
        self.assertEqual(records[0]["value"], records[1]["value"])

    def test_repeated_hidraw_reports_are_serialized_as_distinct_records(self) -> None:
        path = Path("/dev/hidraw0")
        report = b"\x00\x01"

        records = [
            collector.hidraw_report_record(path, report, truncated=False),
            collector.hidraw_report_record(path, report, truncated=False),
        ]

        self.assertEqual([record["record_type"] for record in records], ["hidraw_report", "hidraw_report"])
        self.assertEqual(records[0]["report"], "00 01")
        self.assertEqual(records[1]["report"], "00 01")

    def test_bounded_file_read_marks_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "descriptor"
            path.write_bytes(b"abcdef")

            result = read_bounded_bytes(path, 3)

        self.assertEqual(result.hex, "61 62 63")
        self.assertTrue(result.truncated)

    def test_hidraw_device_node_rejects_parent_hidraw_directory(self) -> None:
        self.assertIsNone(_hidraw_device_node(Path("/sys/devices/example/hidraw")))
        self.assertIsNone(_hidraw_device_node(Path("/sys/devices/example/hidrawfoo")))
        self.assertEqual(_hidraw_device_node(Path("/sys/devices/example/hidraw9")), Path("/dev/hidraw9"))

    def test_capture_writes_end_record_and_ungrabs(self) -> None:
        device = _FakeInputDevice(
            "/dev/input/event1", "Keyboard", events=[SimpleNamespace(sec=1, usec=2, type=1, code=30, value=1)]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="/dev/input/event1",
                        duration_sec=1,
                        output_path=output,
                        grab=True,
                        include_hidraw=False,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                    )
                )

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(device.grabbed)
        self.assertTrue(device.ungrabbed)
        self.assertTrue(device.closed)
        self.assertEqual(records[-1]["record_type"], "capture_end")
        self.assertEqual([record["record_type"] for record in records].count("evdev_event"), 0)
        self.assertEqual([record["record_type"] for record in records].count("evdev_key_snapshot"), 1)
        self.assertFalse(records[-1]["interrupted"])

    def test_capture_default_output_path_uses_matched_device_name_and_timestamp(self) -> None:
        device = _FakeInputDevice("/dev/input/event1", "Apple Inc. Magic Trackpad")
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = Path.cwd()
            with (
                patch("bluetooth_2_usb.ops.devices.collector.timestamp", return_value="20260506_010203"),
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                try:
                    os.chdir(tmpdir)
                    output = asyncio.run(
                        collector.capture_device(
                            devices="Apple",
                            duration_sec=0,
                            output_path=None,
                            grab=False,
                            include_hidraw=False,
                            max_report_bytes=8,
                            max_sysfs_file_bytes=8,
                        )
                    )
                finally:
                    os.chdir(previous_cwd)

            self.assertEqual(output.name, "apple_inc_magic_trackpad_20260506_010203.jsonl")
            self.assertEqual(output.parent, Path(tmpdir) / "device_capture")
            self.assertTrue(output.exists())

    def test_capture_default_output_path_deduplicates_matched_device_names(self) -> None:
        keyboard = _FakeInputDevice("/dev/input/event1", "quaxalber USB Combo Device")
        mouse = _FakeInputDevice("/dev/input/event2", "quaxalber USB Combo Device")
        consumer = _FakeInputDevice("/dev/input/event3", "quaxalber USB Combo Device")
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = Path.cwd()
            with (
                patch("bluetooth_2_usb.ops.devices.collector.timestamp", return_value="20260506_010203"),
                patch(
                    "bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[keyboard, mouse, consumer]
                ),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                try:
                    os.chdir(tmpdir)
                    output = asyncio.run(
                        collector.capture_device(
                            devices="b2u28bc43209b9e4a56",
                            duration_sec=0,
                            output_path=None,
                            grab=False,
                            include_hidraw=False,
                            max_report_bytes=8,
                            max_sysfs_file_bytes=8,
                        )
                    )
                finally:
                    os.chdir(previous_cwd)

            self.assertEqual(output.name, "quaxalber_usb_combo_device_20260506_010203.jsonl")

    def test_capture_default_output_path_uses_common_name_prefix_for_suffixed_nodes(self) -> None:
        touchpad = _FakeInputDevice("/dev/input/event14", "Sony Interactive Entertainment Wireless Controller Touchpad")
        motion = _FakeInputDevice(
            "/dev/input/event13", "Sony Interactive Entertainment Wireless Controller Motion Sensors"
        )
        controller = _FakeInputDevice("/dev/input/event12", "Sony Interactive Entertainment Wireless Controller")
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = Path.cwd()
            with (
                patch("bluetooth_2_usb.ops.devices.collector.timestamp", return_value="20260506_010203"),
                patch(
                    "bluetooth_2_usb.ops.devices.linux.select_input_devices",
                    return_value=[touchpad, motion, controller],
                ),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                try:
                    os.chdir(tmpdir)
                    output = asyncio.run(
                        collector.capture_device(
                            devices="Sony",
                            duration_sec=0,
                            output_path=None,
                            grab=False,
                            include_hidraw=False,
                            max_report_bytes=8,
                            max_sysfs_file_bytes=8,
                        )
                    )
                finally:
                    os.chdir(previous_cwd)

            self.assertEqual(output.name, "sony_interactive_entertainment_wireless_controller_20260506_010203.jsonl")

    def test_raw_capture_default_output_path_includes_raw_suffix(self) -> None:
        device = _FakeInputDevice("/dev/input/event1", "Keyboard")
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = Path.cwd()
            with (
                patch("bluetooth_2_usb.ops.devices.collector.timestamp", return_value="20260506_010203"),
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                try:
                    os.chdir(tmpdir)
                    output = asyncio.run(
                        collector.capture_device(
                            devices="keyboard",
                            duration_sec=0,
                            output_path=None,
                            grab=False,
                            include_hidraw=False,
                            max_report_bytes=8,
                            max_sysfs_file_bytes=8,
                            live_mode="raw",
                        )
                    )
                finally:
                    os.chdir(previous_cwd)

            self.assertEqual(output.name, "keyboard_raw_20260506_010203.jsonl")

    def test_raw_capture_explicit_output_path_is_not_renamed(self) -> None:
        device = _FakeInputDevice("/dev/input/event1", "Keyboard")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "custom.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                result = asyncio.run(
                    collector.capture_device(
                        devices="keyboard",
                        duration_sec=0,
                        output_path=output,
                        grab=False,
                        include_hidraw=False,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                        live_mode="raw",
                    )
                )

        self.assertEqual(result, output)

    def test_capture_hands_default_output_to_sudo_user(self) -> None:
        device = _FakeInputDevice("/dev/input/event1", "Keyboard")
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = Path.cwd()
            with (
                patch.dict(os.environ, {"SUDO_UID": "123", "SUDO_GID": "456"}),
                patch("bluetooth_2_usb.ops.artifacts.os.chown") as chown,
                patch("bluetooth_2_usb.ops.devices.collector.timestamp", return_value="20260506_010203"),
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                try:
                    os.chdir(tmpdir)
                    output = asyncio.run(
                        collector.capture_device(
                            devices="keyboard",
                            duration_sec=0,
                            output_path=None,
                            grab=False,
                            include_hidraw=False,
                            max_report_bytes=8,
                            max_sysfs_file_bytes=8,
                        )
                    )
                finally:
                    os.chdir(previous_cwd)

            self.assertEqual(output.stat().st_mode & 0o777, 0o644)
            self.assertIn((output, 123, 456), [call.args for call in chown.call_args_list])
            self.assertIn((output.parent, 123, 456), [call.args for call in chown.call_args_list])

    def test_capture_redacts_jsonl_records_with_diagnostics_pipeline(self) -> None:
        device = _FakeInputDevice(
            "/dev/input/event1",
            "Keyboard",
            uniq="AA:BB:CC:DD:EE:FF",
            events=[SimpleNamespace(type=1, code=30, value=1)],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="AA:BB:CC:DD:EE:FF",
                        duration_sec=1,
                        output_path=output,
                        grab=False,
                        include_hidraw=False,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                    )
                )

            text = output.read_text(encoding="utf-8")

        self.assertIn("<<REDACTED_BT_MAC>>", text)
        self.assertNotIn("AA:BB:CC:DD:EE:FF", text)

    def test_raw_capture_records_events_from_all_matched_devices(self) -> None:
        keyboard = _FakeInputDevice(
            "/dev/input/event1", "Keyboard", events=[SimpleNamespace(sec=1, usec=2, type=1, code=30, value=1)]
        )
        consumer = _FakeInputDevice(
            "/dev/input/event2", "Keyboard Consumer", events=[SimpleNamespace(sec=3, usec=4, type=1, code=115, value=1)]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[keyboard, consumer]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="keyboard",
                        duration_sec=1,
                        output_path=output,
                        grab=False,
                        include_hidraw=False,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                        live_mode="raw",
                    )
                )

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        start = records[0]
        event_paths = {record["path"] for record in records if record["record_type"] == "evdev_event"}
        self.assertEqual(
            start["matched_devices"],
            [
                {"name": "Keyboard", "path": "/dev/input/event1"},
                {"name": "Keyboard Consumer", "path": "/dev/input/event2"},
            ],
        )
        self.assertEqual(event_paths, {"/dev/input/event1", "/dev/input/event2"})
        self.assertTrue(keyboard.closed)
        self.assertTrue(consumer.closed)

    def test_summarized_capture_records_snapshots_from_all_matched_devices(self) -> None:
        keyboard = _FakeInputDevice(
            "/dev/input/event1", "Keyboard", events=[SimpleNamespace(sec=1, usec=2, type=1, code=30, value=1)]
        )
        consumer = _FakeInputDevice(
            "/dev/input/event2", "Keyboard Consumer", events=[SimpleNamespace(sec=3, usec=4, type=1, code=115, value=1)]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[keyboard, consumer]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="keyboard",
                        duration_sec=1,
                        output_path=output,
                        grab=False,
                        include_hidraw=False,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                    )
                )

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        key_paths = {record["path"] for record in records if record["record_type"] == "evdev_key_snapshot"}
        self.assertEqual(key_paths, {"/dev/input/event1", "/dev/input/event2"})
        self.assertEqual([record["record_type"] for record in records].count("evdev_event"), 0)

    def test_grab_exclusively_grabs_and_ungrabs_all_matched_devices(self) -> None:
        keyboard = _FakeInputDevice("/dev/input/event1", "Keyboard")
        consumer = _FakeInputDevice("/dev/input/event2", "Keyboard Consumer")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[keyboard, consumer]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="keyboard",
                        duration_sec=1,
                        output_path=output,
                        grab=True,
                        include_hidraw=False,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                    )
                )

        self.assertTrue(keyboard.grabbed)
        self.assertTrue(consumer.grabbed)
        self.assertTrue(keyboard.ungrabbed)
        self.assertTrue(consumer.ungrabbed)

    def test_capture_deduplicates_shared_hidraw_nodes_across_matched_devices(self) -> None:
        keyboard = _FakeInputDevice("/dev/input/event1", "Keyboard")
        consumer = _FakeInputDevice("/dev/input/event2", "Keyboard Consumer")
        hidraw = Path("/dev/hidraw9")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[keyboard, consumer]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[hidraw]),
                patch(
                    "bluetooth_2_usb.ops.devices.linux.hidraw_node_records",
                    return_value=[{"record_type": "hidraw_node", "path": str(hidraw)}],
                ) as records,
                patch("bluetooth_2_usb.ops.devices.linux.open_hidraw_nodes", return_value=([], [])) as open_nodes,
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="keyboard",
                        duration_sec=1,
                        output_path=output,
                        grab=False,
                        include_hidraw=True,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                    )
                )

            output_records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        records.assert_called_once_with([hidraw], 8)
        open_nodes.assert_called_once_with([hidraw])
        self.assertEqual([record["record_type"] for record in output_records].count("hidraw_node"), 1)

    def test_capture_accepts_evdev_future_awaitable_readers(self) -> None:
        device = _FutureInputDevice("/dev/input/event1", "Keyboard")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="/dev/input/event1",
                        duration_sec=1,
                        output_path=output,
                        grab=False,
                        include_hidraw=False,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                        live_mode="raw",
                    )
                )

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([record["record_type"] for record in records].count("evdev_event"), 1)

    def test_summarized_capture_records_short_rel_and_abs_axis_snapshots(self) -> None:
        device = _FakeInputDevice(
            "/dev/input/event1",
            "Controller",
            events=[
                SimpleNamespace(sec=1, usec=1, type=2, code=0, value=3),
                SimpleNamespace(sec=1, usec=2, type=2, code=0, value=-1),
                SimpleNamespace(sec=1, usec=3, type=3, code=1, value=10),
                SimpleNamespace(sec=1, usec=4, type=3, code=1, value=10),
                SimpleNamespace(sec=1, usec=5, type=3, code=1, value=20),
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="/dev/input/event1",
                        duration_sec=1,
                        output_path=output,
                        grab=False,
                        include_hidraw=False,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                    )
                )

            snapshots = [
                json.loads(line)
                for line in output.read_text(encoding="utf-8").splitlines()
                if json.loads(line)["record_type"] == "evdev_axis_snapshot"
            ]

        rel = next(record for record in snapshots if record["type_name"] == "EV_REL")
        abs_axis = next(record for record in snapshots if record["type_name"] == "EV_ABS")
        self.assertEqual(rel["count"], 2)
        self.assertEqual(rel["sum_value"], 2)
        self.assertEqual(rel["sum_abs_value"], 4)
        self.assertEqual(abs_axis["count"], 3)
        self.assertEqual(abs_axis["min_value"], 10)
        self.assertEqual(abs_axis["max_value"], 20)
        self.assertEqual(abs_axis["sample_values"], [10, 20])
        self.assertEqual(abs_axis["changed_value_count"], 2)
        self.assertEqual(abs_axis["same_value_repeat_count"], 1)

    def test_summarized_capture_records_sync_summary(self) -> None:
        device = _FakeInputDevice(
            "/dev/input/event1",
            "Controller",
            events=[
                SimpleNamespace(sec=1, usec=1, type=0, code=0, value=0),
                SimpleNamespace(sec=1, usec=2, type=0, code=3, value=0),
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="/dev/input/event1",
                        duration_sec=1,
                        output_path=output,
                        grab=False,
                        include_hidraw=False,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                    )
                )

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        sync = next(record for record in records if record["record_type"] == "evdev_sync_summary")
        self.assertEqual(sync["syn_report_count"], 1)
        self.assertEqual(sync["syn_dropped_count"], 1)

    def test_summarized_capture_records_hidraw_group_summary(self) -> None:
        device = _FakeInputDevice("/dev/input/event1", "Controller")
        hidraw = Path("/dev/hidraw1")
        reports = [b"\x01\x00\x00", b"\x01\x00\x00", b"\x01\x02\x00", None]

        def read_hidraw(_fd, _max_bytes):
            if not reports:
                return None
            return reports.pop(0)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[hidraw]),
                patch("bluetooth_2_usb.ops.devices.linux.hidraw_node_records", return_value=[]),
                patch("bluetooth_2_usb.ops.devices.linux.open_hidraw_nodes", return_value=([(hidraw, 5)], [])),
                patch("bluetooth_2_usb.ops.devices.linux.close_hidraw_nodes"),
                patch("bluetooth_2_usb.ops.devices.linux.read_hidraw", side_effect=read_hidraw),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="/dev/input/event1",
                        duration_sec=1,
                        output_path=output,
                        grab=False,
                        include_hidraw=True,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                    )
                )

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        summary = next(record for record in records if record["record_type"] == "hidraw_report_group_summary")
        self.assertEqual(summary["path"], str(hidraw))
        self.assertIsNone(summary["report_id"])
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["exact_duplicate_count"], 1)
        self.assertEqual(summary["unique_report_count"], 2)
        self.assertEqual(summary["changed_byte_indexes"], [1])

    def test_summarized_capture_uses_hidraw_report_id_only_when_descriptor_declares_one(self) -> None:
        device = _FakeInputDevice("/dev/input/event1", "Controller")
        hidraw = Path("/dev/hidraw1")
        descriptor = "05 01 85 02 09 05"
        reports = [b"\x02\x00\x00", None]

        def read_hidraw(_fd, _max_bytes):
            if not reports:
                return None
            return reports.pop(0)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[hidraw]),
                patch(
                    "bluetooth_2_usb.ops.devices.linux.hidraw_node_records",
                    return_value=[
                        {
                            "record_type": "hidraw_node",
                            "path": str(hidraw),
                            "files": [
                                {"path": "/sys/class/hidraw/hidraw1/device/report_descriptor", "hex": descriptor}
                            ],
                        }
                    ],
                ),
                patch("bluetooth_2_usb.ops.devices.linux.open_hidraw_nodes", return_value=([(hidraw, 5)], [])),
                patch("bluetooth_2_usb.ops.devices.linux.close_hidraw_nodes"),
                patch("bluetooth_2_usb.ops.devices.linux.read_hidraw", side_effect=read_hidraw),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="/dev/input/event1",
                        duration_sec=1,
                        output_path=output,
                        grab=False,
                        include_hidraw=True,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                    )
                )

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        summary = next(record for record in records if record["record_type"] == "hidraw_report_group_summary")
        self.assertEqual(summary["report_id"], 2)

    def test_cancelled_capture_writes_interrupted_end_record_and_partial_summary(self) -> None:
        device = _CancelledInputDevice("/dev/input/event1", "Controller")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(
                        collector.capture_device(
                            devices="/dev/input/event1",
                            duration_sec=30,
                            output_path=output,
                            grab=False,
                            include_hidraw=False,
                            max_report_bytes=8,
                            max_sysfs_file_bytes=8,
                        )
                    )

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(records[-1]["record_type"], "capture_end")
        self.assertTrue(records[-1]["interrupted"])
        self.assertEqual([record["record_type"] for record in records].count("evdev_axis_snapshot"), 1)
        self.assertTrue(device.closed)

    def test_capture_timeout_does_not_cancel_pending_evdev_future(self) -> None:
        device = _PendingFutureInputDevice("/dev/input/event1", "Controller")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "capture.jsonl"
            with (
                patch("bluetooth_2_usb.ops.devices.linux.select_input_devices", return_value=[device]),
                patch("bluetooth_2_usb.ops.devices.linux.discover_hidraw_nodes", return_value=[]),
            ):
                asyncio.run(
                    collector.capture_device(
                        devices="/dev/input/event1",
                        duration_sec=0,
                        output_path=output,
                        grab=False,
                        include_hidraw=False,
                        max_report_bytes=8,
                        max_sysfs_file_bytes=8,
                    )
                )

        self.assertIsNotNone(device.pending_future)
        self.assertFalse(device.pending_future.cancelled())

    def test_validate_capture_accepts_summarized_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyboard_20260506_010203.jsonl"
            _write_jsonl(path, _minimal_capture_records())

            report = validate_capture(path, generated_output=True)

        self.assertTrue(report.valid)
        self.assertEqual(report.live_mode, "summarized")
        self.assertTrue(report.captured["evdev_key_snapshot"])
        self.assertFalse(report.errors)

    def test_validate_capture_accepts_raw_capture_with_raw_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyboard_raw_20260506_010203.jsonl"
            _write_jsonl(path, _minimal_capture_records(live_mode="raw"))

            report = validate_capture(path, generated_output=True)

        self.assertTrue(report.valid)
        self.assertEqual(report.live_mode, "raw")
        self.assertTrue(report.captured["evdev_event_raw"])
        self.assertNotIn("raw capture filename is missing _raw suffix", report.warnings)

    def test_validate_capture_warns_for_generated_raw_capture_without_raw_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyboard_20260506_010203.jsonl"
            _write_jsonl(path, _minimal_capture_records(live_mode="raw"))

            report = validate_capture(path, generated_output=True)

        self.assertTrue(report.valid)
        self.assertIn("raw capture filename is missing _raw suffix", report.warnings)

    def test_validate_capture_warns_for_generated_summarized_capture_with_raw_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyboard_raw_20260506_010203.jsonl"
            _write_jsonl(path, _minimal_capture_records())

            report = validate_capture(path, generated_output=True)

        self.assertTrue(report.valid)
        self.assertIn("summarized capture filename contains _raw suffix", report.warnings)

    def test_validate_capture_skips_filename_warnings_for_explicit_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "custom.jsonl"
            _write_jsonl(path, _minimal_capture_records(live_mode="raw"))

            report = validate_capture(path)

        self.assertTrue(report.valid)
        self.assertNotIn("raw capture filename is missing _raw suffix", report.warnings)
        self.assertNotIn("filename does not match generated naming scheme", report.warnings)

    def test_validate_capture_does_not_warn_for_keyboard_only_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyboard_20260506_010203.jsonl"
            records = [
                record for record in _minimal_capture_records() if record["record_type"] != "evdev_axis_snapshot"
            ]
            _write_jsonl(path, records)

            report = validate_capture(path)

        self.assertTrue(report.valid)
        self.assertNotIn("no relative or absolute axis evidence captured", report.warnings)

    def test_validate_capture_does_not_warn_for_axis_only_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "pointer_20260506_010203.jsonl"
            records = [record for record in _minimal_capture_records() if record["record_type"] != "evdev_key_snapshot"]
            _write_jsonl(path, records)

            report = validate_capture(path)

        self.assertTrue(report.valid)
        self.assertNotIn("no key/button evidence captured", report.warnings)

    def test_validate_capture_reports_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyboard_20260506_010203.jsonl"
            path.write_text("{not json}\n", encoding="utf-8")

            report = validate_capture(path)

        self.assertFalse(report.valid)
        self.assertEqual(report.parse_error_count, 1)

    def test_validate_capture_reports_missing_start_and_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyboard_20260506_010203.jsonl"
            _write_jsonl(path, [{"record_type": "input_device", "path": "/dev/input/event1"}])

            report = validate_capture(path)

        self.assertFalse(report.valid)
        self.assertIn("first record is not capture_start", report.errors)
        self.assertIn("missing capture_end record", report.errors)

    def test_validate_capture_warns_for_unredacted_mac_and_capture_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyboard_20260506_010203.jsonl"
            records = _minimal_capture_records(warning="no matching hidraw node discovered")
            records[1]["uniq"] = "AA:BB:CC:DD:EE:FF"
            _write_jsonl(path, records)

            report = validate_capture(path)

        self.assertTrue(report.valid)
        self.assertIn("no matching hidraw node discovered", report.warnings)
        self.assertIn("1 lines still contain diagnostics-redactable values", report.warnings)

    def test_validate_capture_warns_when_no_live_evidence_was_captured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyboard_20260506_010203.jsonl"
            records = _minimal_capture_records()
            records = [
                record
                for record in records
                if record["record_type"] not in {"evdev_key_snapshot", "evdev_axis_snapshot", "evdev_sync_summary"}
            ]
            _write_jsonl(path, records)

            report = validate_capture(path)

        self.assertTrue(report.valid)
        self.assertIn("no live input evidence captured", report.warnings)


if __name__ == "__main__":
    unittest.main()
