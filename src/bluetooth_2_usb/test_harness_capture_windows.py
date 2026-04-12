from __future__ import annotations

import ctypes
import os
import re
import time
from ctypes import wintypes
from dataclasses import dataclass, field

from .test_harness_capture import (
    CaptureMismatchError,
    CaptureTimeoutError,
    ConsumerSequenceMatcher,
    GadgetNodeCandidates,
    GadgetNodes,
    HarnessResult,
    KeyboardSequenceMatcher,
    MissingNodeError,
    MouseSequenceMatcher,
)
from .test_harness_common import EXIT_OK, get_scenario

WM_INPUT = 0x00FF
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
RIM_TYPEHID = 2
PM_REMOVE = 0x0001
RI_KEY_BREAK = 0x0001
RI_MOUSE_WHEEL = 0x0400
CW_USEDEFAULT = -2147483648
GENERIC_DESKTOP_USAGE_PAGE = 0x01
KEYBOARD_USAGE = 0x06
MOUSE_USAGE = 0x02
CONSUMER_USAGE_PAGE = 0x0C
CONSUMER_USAGE = 0x01
VK_F13 = 0x7C
VK_F14 = 0x7D
VK_F15 = 0x7E

VK_TO_HID = {
    VK_F13: 104,
    VK_F14: 105,
    VK_F15: 106,
}


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("ulButtons", wintypes.ULONG),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class RAWINPUTUNION(ctypes.Union):
    _fields_ = [
        ("mouse", RAWMOUSE),
        ("keyboard", RAWKEYBOARD),
    ]


class RAWINPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data", RAWINPUTUNION),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
        ("lPrivate", wintypes.DWORD),
    ]


class RID_DEVICE_INFO_MOUSE(ctypes.Structure):
    _fields_ = [
        ("dwId", wintypes.DWORD),
        ("dwNumberOfButtons", wintypes.DWORD),
        ("dwSampleRate", wintypes.DWORD),
        ("fHasHorizontalWheel", wintypes.BOOL),
    ]


class RID_DEVICE_INFO_KEYBOARD(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSubType", wintypes.DWORD),
        ("dwKeyboardMode", wintypes.DWORD),
        ("dwNumberOfFunctionKeys", wintypes.DWORD),
        ("dwNumberOfIndicators", wintypes.DWORD),
        ("dwNumberOfKeysTotal", wintypes.DWORD),
    ]


class RID_DEVICE_INFO_HID(ctypes.Structure):
    _fields_ = [
        ("dwVendorId", wintypes.DWORD),
        ("dwProductId", wintypes.DWORD),
        ("dwVersionNumber", wintypes.DWORD),
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
    ]


class RID_DEVICE_INFO_UNION(ctypes.Union):
    _fields_ = [
        ("mouse", RID_DEVICE_INFO_MOUSE),
        ("keyboard", RID_DEVICE_INFO_KEYBOARD),
        ("hid", RID_DEVICE_INFO_HID),
    ]


class RID_DEVICE_INFO(ctypes.Structure):
    _anonymous_ = ("info",)
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
        ("info", RID_DEVICE_INFO_UNION),
    ]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [
        ("hDevice", wintypes.HANDLE),
        ("dwType", wintypes.DWORD),
    ]


class RAWHIDHEADER(ctypes.Structure):
    _fields_ = [
        ("dwSizeHid", wintypes.DWORD),
        ("dwCount", wintypes.DWORD),
    ]


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
LRESULT = ctypes.c_ssize_t
HRAWINPUT = wintypes.HANDLE

WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

RIDI_DEVICENAME = 0x20000007
RIDI_DEVICEINFO = 0x2000000B
WM_QUIT = 0x0012

_DEVICE_TOKEN_RE = re.compile(r"vid_[0-9a-f]{4}&pid_[0-9a-f]{4}(?:&mi_[0-9a-f]{2})?")
user32.DefWindowProcW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = (
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
)
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.DestroyWindow.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = (ctypes.c_int,)
user32.PostQuitMessage.restype = None
user32.RegisterRawInputDevices.argtypes = (
    ctypes.POINTER(RAWINPUTDEVICE),
    wintypes.UINT,
    wintypes.UINT,
)
user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = (
    ctypes.POINTER(MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
)
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)
user32.DispatchMessageW.restype = LRESULT
user32.GetRawInputData.argtypes = (
    HRAWINPUT,
    wintypes.UINT,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.UINT),
    wintypes.UINT,
)
user32.GetRawInputData.restype = wintypes.UINT
user32.GetRawInputDeviceInfoW.argtypes = (
    wintypes.HANDLE,
    wintypes.UINT,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.UINT),
)
user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
user32.GetRawInputDeviceList.argtypes = (
    ctypes.POINTER(RAWINPUTDEVICELIST),
    ctypes.POINTER(wintypes.UINT),
    wintypes.UINT,
)
user32.GetRawInputDeviceList.restype = wintypes.UINT
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.argtypes = ()
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


@dataclass(slots=True)
class _RawInputCandidate:
    role: str
    tokens: tuple[str, ...]
    matcher: KeyboardSequenceMatcher | MouseSequenceMatcher | ConsumerSequenceMatcher
    matched_name: str | None = None
    matched_reports: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.matcher.complete

    def note_report(self, report: bytes) -> None:
        if len(self.matched_reports) >= 12:
            return
        self.matched_reports.append(report.hex(" "))

@dataclass(slots=True)
class _RawInputDebug:
    keyboard_tokens: tuple[str, ...]
    mouse_tokens: tuple[str, ...]
    consumer_tokens: tuple[str, ...]
    total_messages_seen: int = 0
    keyboard_messages_seen: int = 0
    mouse_messages_seen: int = 0
    consumer_messages_seen: int = 0
    keyboard_matches_seen: int = 0
    mouse_matches_seen: int = 0
    consumer_matches_seen: int = 0
    device_names_seen: dict[str, int] | None = None
    sample_events: list[dict[str, object]] | None = None
    raw_device_list: list[dict[str, object]] | None = None

    def __post_init__(self) -> None:
        self.device_names_seen = {}
        self.sample_events = []
        self.raw_device_list = []

    def note_device(self, device_name: str) -> None:
        assert self.device_names_seen is not None
        self.device_names_seen[device_name] = self.device_names_seen.get(device_name, 0) + 1

    def note_event(
        self,
        *,
        role: str,
        device_name: str,
        token: str | None,
        matched: bool,
        report: bytes | None = None,
        vkey: int | None = None,
        is_key_up: bool | None = None,
        rel_x: int | None = None,
        rel_y: int | None = None,
    ) -> None:
        self.total_messages_seen += 1
        if role == "keyboard":
            self.keyboard_messages_seen += 1
            if matched:
                self.keyboard_matches_seen += 1
        elif role == "mouse":
            self.mouse_messages_seen += 1
            if matched:
                self.mouse_matches_seen += 1
        elif role == "consumer":
            self.consumer_messages_seen += 1
            if matched:
                self.consumer_matches_seen += 1

        self.note_device(device_name)
        assert self.sample_events is not None
        if len(self.sample_events) >= 12:
            return
        event: dict[str, object] = {
            "role": role,
            "device_name": device_name,
            "expected_token": token,
            "matched_token": matched,
        }
        if report is not None:
            event["report_hex"] = report.hex(" ")
        if vkey is not None:
            event["vkey"] = vkey
        if is_key_up is not None:
            event["is_key_up"] = is_key_up
        if rel_x is not None or rel_y is not None:
            event["rel_x"] = rel_x
            event["rel_y"] = rel_y
        self.sample_events.append(event)

    def to_dict(self) -> dict[str, object]:
        assert self.device_names_seen is not None
        assert self.sample_events is not None
        assert self.raw_device_list is not None
        return {
            "keyboard_tokens": list(self.keyboard_tokens),
            "mouse_tokens": list(self.mouse_tokens),
            "consumer_tokens": list(self.consumer_tokens),
            "total_messages_seen": self.total_messages_seen,
            "keyboard_messages_seen": self.keyboard_messages_seen,
            "mouse_messages_seen": self.mouse_messages_seen,
            "consumer_messages_seen": self.consumer_messages_seen,
            "keyboard_matches_seen": self.keyboard_matches_seen,
            "mouse_matches_seen": self.mouse_matches_seen,
            "consumer_matches_seen": self.consumer_matches_seen,
            "device_names_seen": dict(sorted(self.device_names_seen.items())),
            "raw_device_list": list(self.raw_device_list),
            "sample_events": list(self.sample_events),
        }


def _extract_device_token(node: str | None) -> str | None:
    if not node:
        return None
    match = _DEVICE_TOKEN_RE.search(node.lower())
    if not match:
        return None
    return match.group(0)


def _extract_device_tokens(nodes: tuple[str | None, ...]) -> tuple[str, ...]:
    tokens: list[str] = []
    for node in nodes:
        token = _extract_device_token(node)
        if token and token not in tokens:
            tokens.append(token)
    return tuple(tokens)


def _extract_candidate_tokens(candidate_nodes: GadgetNodeCandidates) -> tuple[str, ...]:
    return _extract_device_tokens(
        tuple(
            info.node
            for info in (
                candidate_nodes.keyboard_nodes
                + candidate_nodes.mouse_nodes
                + candidate_nodes.consumer_nodes
            )
        )
    )


def _normalize_device_name(name: str) -> str:
    return name.lower().replace("#", "\\")


def _device_matches_token(device_name: str, tokens: tuple[str, ...]) -> bool:
    if not tokens:
        return "vid_1d6b" in device_name and "pid_0104" in device_name
    for token in tokens:
        if token.replace("&", "\\") in device_name or token in device_name:
            return True
    return False


def _keyboard_event_to_report(vkey: int, is_key_up: bool) -> bytes | None:
    hid_code = VK_TO_HID.get(vkey)
    if hid_code is None:
        return None
    if is_key_up:
        return bytes([0x00] * 8)
    return bytes([0x00, 0x00, hid_code, 0, 0, 0, 0, 0])


def _mouse_event_to_reports(raw_mouse: RAWMOUSE) -> list[bytes]:
    reports: list[bytes] = []
    button_flags = raw_mouse.ulButtons & 0xFFFF
    if button_flags & RI_MOUSE_WHEEL:
        return reports
    if raw_mouse.lLastX:
        reports.append(bytes([0x02, 0x00, raw_mouse.lLastX & 0xFF, 0x00, 0x00]))
    if raw_mouse.lLastY:
        reports.append(bytes([0x02, 0x00, 0x00, raw_mouse.lLastY & 0xFF, 0x00]))
    return reports


def _get_raw_input_device_name(hdevice: int) -> str:
    size = wintypes.UINT(0)
    if user32.GetRawInputDeviceInfoW(
        wintypes.HANDLE(hdevice), RIDI_DEVICENAME, None, ctypes.byref(size)
    ) == 0xFFFFFFFF:
        raise OSError("GetRawInputDeviceInfoW failed while sizing device name")
    buffer = ctypes.create_unicode_buffer(size.value)
    if user32.GetRawInputDeviceInfoW(
        wintypes.HANDLE(hdevice), RIDI_DEVICENAME, buffer, ctypes.byref(size)
    ) == 0xFFFFFFFF:
        raise OSError("GetRawInputDeviceInfoW failed while reading device name")
    return _normalize_device_name(buffer.value)


def _get_raw_input_device_info(hdevice: int) -> dict[str, object]:
    info = RID_DEVICE_INFO()
    info.cbSize = ctypes.sizeof(RID_DEVICE_INFO)
    size = wintypes.UINT(ctypes.sizeof(RID_DEVICE_INFO))
    if user32.GetRawInputDeviceInfoW(
        wintypes.HANDLE(hdevice),
        RIDI_DEVICEINFO,
        ctypes.byref(info),
        ctypes.byref(size),
    ) == 0xFFFFFFFF:
        raise OSError("GetRawInputDeviceInfoW failed while reading device info")

    details: dict[str, object] = {"dwType": int(info.dwType)}
    if info.dwType == RIM_TYPEKEYBOARD:
        details["keyboard_type"] = int(info.keyboard.dwType)
        details["keyboard_subtype"] = int(info.keyboard.dwSubType)
        details["keyboard_mode"] = int(info.keyboard.dwKeyboardMode)
        details["function_keys"] = int(info.keyboard.dwNumberOfFunctionKeys)
        details["indicators"] = int(info.keyboard.dwNumberOfIndicators)
        details["keys_total"] = int(info.keyboard.dwNumberOfKeysTotal)
    elif info.dwType == RIM_TYPEMOUSE:
        details["mouse_id"] = int(info.mouse.dwId)
        details["mouse_buttons"] = int(info.mouse.dwNumberOfButtons)
        details["sample_rate"] = int(info.mouse.dwSampleRate)
        details["has_horizontal_wheel"] = bool(info.mouse.fHasHorizontalWheel)
    else:
        details["vendor_id"] = int(info.hid.dwVendorId)
        details["product_id"] = int(info.hid.dwProductId)
        details["version_number"] = int(info.hid.dwVersionNumber)
        details["usage_page"] = int(info.hid.usUsagePage)
        details["usage"] = int(info.hid.usUsage)
    return details


def _list_raw_input_devices() -> list[dict[str, object]]:
    count = wintypes.UINT(0)
    entry_size = ctypes.sizeof(RAWINPUTDEVICELIST)
    if user32.GetRawInputDeviceList(None, ctypes.byref(count), entry_size) == 0xFFFFFFFF:
        raise OSError("GetRawInputDeviceList failed while sizing device list")
    if count.value == 0:
        return []

    raw_list = (RAWINPUTDEVICELIST * count.value)()
    result = user32.GetRawInputDeviceList(raw_list, ctypes.byref(count), entry_size)
    if result == 0xFFFFFFFF:
        raise OSError("GetRawInputDeviceList failed while reading device list")

    devices: list[dict[str, object]] = []
    for entry in raw_list[: count.value]:
        try:
            device_name = _get_raw_input_device_name(entry.hDevice)
        except OSError as exc:
            device_name = f"<name unavailable: {exc}>"
        try:
            info = _get_raw_input_device_info(entry.hDevice)
        except OSError as exc:
            info = {"error": str(exc)}
        devices.append(
            {
                "device_name": device_name,
                "dwType": int(entry.dwType),
                **info,
            }
        )
    return devices


def _register_raw_input(hwnd: int) -> None:
    devices = (RAWINPUTDEVICE * 3)(
        RAWINPUTDEVICE(
            usUsagePage=GENERIC_DESKTOP_USAGE_PAGE,
            usUsage=KEYBOARD_USAGE,
            dwFlags=RIDEV_INPUTSINK,
            hwndTarget=hwnd,
        ),
        RAWINPUTDEVICE(
            usUsagePage=GENERIC_DESKTOP_USAGE_PAGE,
            usUsage=MOUSE_USAGE,
            dwFlags=RIDEV_INPUTSINK,
            hwndTarget=hwnd,
        ),
        RAWINPUTDEVICE(
            usUsagePage=CONSUMER_USAGE_PAGE,
            usUsage=CONSUMER_USAGE,
            dwFlags=RIDEV_INPUTSINK,
            hwndTarget=hwnd,
        ),
    )
    if not user32.RegisterRawInputDevices(
        devices, len(devices), ctypes.sizeof(RAWINPUTDEVICE)
    ):
        raise OSError("RegisterRawInputDevices failed")


def _create_message_window() -> tuple[int, WNDPROC]:
    hinstance = kernel32.GetModuleHandleW(None)

    def _wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wndproc = WNDPROC(_wndproc)
    class_name = f"B2URawInputCapture-{kernel32.GetCurrentThreadId()}"
    wndclass = WNDCLASSW()
    wndclass.lpfnWndProc = ctypes.cast(wndproc, ctypes.c_void_p)
    wndclass.hInstance = hinstance
    wndclass.lpszClassName = class_name
    atom = user32.RegisterClassW(ctypes.byref(wndclass))
    if not atom and kernel32.GetLastError() != 1410:
        raise OSError("RegisterClassW failed")
    hwnd = user32.CreateWindowExW(
        0,
        class_name,
        class_name,
        0,
        CW_USEDEFAULT,
        CW_USEDEFAULT,
        1,
        1,
        None,
        None,
        hinstance,
        None,
    )
    if not hwnd:
        raise OSError("CreateWindowExW failed")
    return hwnd, wndproc


def _read_raw_input(lparam: int) -> tuple[RAWINPUT, bytes]:
    size = wintypes.UINT(0)
    header_size = ctypes.sizeof(RAWINPUTHEADER)
    if (
        user32.GetRawInputData(
            HRAWINPUT(lparam),
            RID_INPUT,
            None,
            ctypes.byref(size),
            header_size,
        )
        == 0xFFFFFFFF
    ):
        raise OSError("GetRawInputData sizing failed")
    buffer = ctypes.create_string_buffer(size.value)
    if (
        user32.GetRawInputData(
            HRAWINPUT(lparam),
            RID_INPUT,
            buffer,
            ctypes.byref(size),
            header_size,
        )
        == 0xFFFFFFFF
    ):
        raise OSError("GetRawInputData read failed")
    raw_bytes = buffer.raw[: size.value]
    if len(raw_bytes) < ctypes.sizeof(RAWINPUT):
        raw_bytes += b"\x00" * (ctypes.sizeof(RAWINPUT) - len(raw_bytes))
    return RAWINPUT.from_buffer_copy(raw_bytes[: ctypes.sizeof(RAWINPUT)]), raw_bytes


def _extract_raw_hid_reports(raw_bytes: bytes) -> list[bytes]:
    offset = ctypes.sizeof(RAWINPUTHEADER)
    if len(raw_bytes) < offset + ctypes.sizeof(RAWHIDHEADER):
        return []
    hid_header = RAWHIDHEADER.from_buffer_copy(
        raw_bytes[offset : offset + ctypes.sizeof(RAWHIDHEADER)]
    )
    report_size = int(hid_header.dwSizeHid)
    report_count = int(hid_header.dwCount)
    if report_size <= 0 or report_count <= 0:
        return []

    reports: list[bytes] = []
    data_offset = offset + ctypes.sizeof(RAWHIDHEADER)
    for index in range(report_count):
        start = data_offset + (index * report_size)
        end = start + report_size
        if end > len(raw_bytes):
            break
        reports.append(raw_bytes[start:end])
    return reports


def _pump_raw_input(
    timeout_sec: float,
    keyboard_tokens: tuple[str, ...],
    mouse_tokens: tuple[str, ...],
    consumer_tokens: tuple[str, ...],
    scenario_name: str,
) -> HarnessResult:
    scenario = get_scenario(scenario_name)
    debug_only = os.environ.get("B2U_RAW_INPUT_DEBUG_ONLY") == "1"
    keyboard_candidate = (
        _RawInputCandidate(
            "keyboard",
            keyboard_tokens,
            KeyboardSequenceMatcher(scenario.keyboard_steps),
        )
        if scenario.keyboard_enabled
        else None
    )
    mouse_candidate = (
        _RawInputCandidate(
            "mouse",
            mouse_tokens,
            MouseSequenceMatcher.create(
                scenario.mouse_rel_steps, scenario.mouse_button_steps
            ),
        )
        if scenario.mouse_enabled
        else None
    )
    consumer_candidate = (
        _RawInputCandidate(
            "consumer",
            consumer_tokens,
            ConsumerSequenceMatcher(scenario.consumer_steps),
        )
        if scenario.consumer_enabled
        else None
    )

    hwnd, wndproc = _create_message_window()
    del wndproc
    _register_raw_input(hwnd)
    deadline = time.monotonic() + timeout_sec
    msg = MSG()
    debug = _RawInputDebug(
        keyboard_tokens=keyboard_candidate.tokens if keyboard_candidate else (),
        mouse_tokens=mouse_candidate.tokens if mouse_candidate else (),
        consumer_tokens=consumer_candidate.tokens if consumer_candidate else (),
    )
    debug.raw_device_list = _list_raw_input_devices()

    try:
        while time.monotonic() < deadline:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_QUIT:
                    break
                if msg.message == WM_INPUT:
                    raw, raw_bytes = _read_raw_input(msg.lParam)
                    try:
                        device_name = _get_raw_input_device_name(raw.header.hDevice)
                    except OSError:
                        device_name = "<unavailable>"

                    if raw.header.dwType == RIM_TYPEKEYBOARD and keyboard_candidate:
                        matched = _device_matches_token(device_name, keyboard_candidate.tokens)
                        report = _keyboard_event_to_report(
                            raw.keyboard.VKey,
                            bool(raw.keyboard.Flags & RI_KEY_BREAK),
                        )
                        debug.note_event(
                            role="keyboard",
                            device_name=device_name,
                            token="|".join(keyboard_candidate.tokens) or None,
                            matched=matched,
                            report=report,
                            vkey=raw.keyboard.VKey,
                            is_key_up=bool(raw.keyboard.Flags & RI_KEY_BREAK),
                        )
                        if not matched:
                            continue
                        if report is None:
                            continue
                        keyboard_candidate.matched_name = device_name
                        keyboard_candidate.note_report(report)
                        if not debug_only:
                            keyboard_candidate.matcher.handle(report)

                    elif raw.header.dwType == RIM_TYPEMOUSE and mouse_candidate:
                        matched = _device_matches_token(device_name, mouse_candidate.tokens)
                        debug.note_event(
                            role="mouse",
                            device_name=device_name,
                            token="|".join(mouse_candidate.tokens) or None,
                            matched=matched,
                            rel_x=raw.mouse.lLastX,
                            rel_y=raw.mouse.lLastY,
                        )
                        if not matched:
                            continue
                        mouse_candidate.matched_name = device_name
                        for report in _mouse_event_to_reports(raw.mouse):
                            mouse_candidate.note_report(report)
                            if not debug_only:
                                mouse_candidate.matcher.handle(report)
                    elif raw.header.dwType == RIM_TYPEHID and consumer_candidate:
                        matched = _device_matches_token(device_name, consumer_candidate.tokens)
                        for report in _extract_raw_hid_reports(raw_bytes):
                            debug.note_event(
                                role="consumer",
                                device_name=device_name,
                                token="|".join(consumer_candidate.tokens) or None,
                                matched=matched,
                                report=report,
                            )
                            if not matched:
                                continue
                            consumer_candidate.matched_name = device_name
                            consumer_candidate.note_report(report)
                            if not debug_only:
                                consumer_candidate.matcher.handle(report)

                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            if (
                not debug_only
                and (
                (keyboard_candidate is None or keyboard_candidate.complete)
                and (mouse_candidate is None or mouse_candidate.complete)
                and (consumer_candidate is None or consumer_candidate.complete)
                )
            ):
                nodes = GadgetNodes(
                    keyboard_node=keyboard_candidate.matched_name if keyboard_candidate else None,
                    mouse_node=mouse_candidate.matched_name if mouse_candidate else None,
                    consumer_node=consumer_candidate.matched_name if consumer_candidate else None,
                )
                details: dict[str, object] = {
                    "capture_backend": "raw_input",
                    "timeout_sec": timeout_sec,
                    "nodes": nodes.to_dict(),
                    "raw_input_debug": debug.to_dict(),
                }
                if keyboard_candidate is not None:
                    details["keyboard_steps_seen"] = keyboard_candidate.matcher.index
                    details["keyboard_reports_seen"] = list(
                        keyboard_candidate.matched_reports
                    )
                if mouse_candidate is not None:
                    details["mouse_rel_steps_seen"] = mouse_candidate.matcher.rel_index
                    details["mouse_button_steps_seen"] = mouse_candidate.matcher.button_index
                    details["mouse_reports_seen"] = list(mouse_candidate.matched_reports)
                if consumer_candidate is not None:
                    details["consumer_steps_seen"] = consumer_candidate.matcher.index
                    details["consumer_reports_seen"] = list(
                        consumer_candidate.matched_reports
                    )
                return HarnessResult(
                    command="capture",
                    scenario=scenario.name,
                    success=True,
                    exit_code=EXIT_OK,
                    message="Observed expected relay events through Windows Raw Input",
                    details=details,
                )

            time.sleep(0.01)
    except CaptureMismatchError as exc:
        return HarnessResult(
            command="capture",
            scenario=scenario.name,
            success=False,
            exit_code=exc.exit_code,
            message=str(exc),
            details={
                "capture_backend": "raw_input",
                "timeout_sec": timeout_sec,
                "nodes": GadgetNodes(None, None, None).to_dict(),
                "raw_input_debug": debug.to_dict(),
            },
        )
    finally:
        user32.DestroyWindow(hwnd)

    return HarnessResult(
        command="capture",
        scenario=scenario.name,
        success=False,
        exit_code=CaptureTimeoutError.exit_code,
        message=(
            f"Observed raw input for {timeout_sec}s without strict matching"
            if debug_only
            else f"Timed out waiting for {scenario.name} events after {timeout_sec}s"
        ),
        details={
            "capture_backend": "raw_input",
            "timeout_sec": timeout_sec,
            "nodes": GadgetNodes(None, None, None).to_dict(),
            "raw_input_debug": debug.to_dict(),
        },
    )


def run_windows_raw_input_capture(
    scenario_name: str,
    timeout_sec: float,
    candidate_nodes: GadgetNodeCandidates,
) -> HarnessResult:
    scenario = get_scenario(scenario_name)
    keyboard_tokens: tuple[str, ...] = ()
    mouse_tokens: tuple[str, ...] = ()
    consumer_tokens: tuple[str, ...] = ()
    if scenario.keyboard_enabled:
        if not candidate_nodes.keyboard_nodes:
            raise MissingNodeError("Keyboard HID device was not found")
        keyboard_tokens = _extract_device_tokens(
            tuple(info.node for info in candidate_nodes.keyboard_nodes)
        )
    if scenario.mouse_enabled:
        if not candidate_nodes.mouse_nodes:
            raise MissingNodeError("Mouse HID device was not found")
        mouse_tokens = _extract_device_tokens(
            tuple(info.node for info in candidate_nodes.mouse_nodes)
        )
    if scenario.consumer_enabled:
        if not candidate_nodes.consumer_nodes:
            raise MissingNodeError("Consumer-control HID device was not found")
        consumer_tokens = _extract_device_tokens(
            tuple(info.node for info in candidate_nodes.consumer_nodes)
        )

    result = _pump_raw_input(
        timeout_sec=timeout_sec,
        keyboard_tokens=keyboard_tokens,
        mouse_tokens=mouse_tokens,
        consumer_tokens=consumer_tokens,
        scenario_name=scenario_name,
    )
    result.details.setdefault("candidates", candidate_nodes.to_dict())
    return result
