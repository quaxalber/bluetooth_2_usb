from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from types import SimpleNamespace

from adafruit_hid.keycode import Keycode

from ..evdev import KeyEvent, ecodes, evdev_to_usb_hid
from ..hid.constants import (
    HID_PAGE_CONSUMER,
    HID_PAGE_GENERIC_DESKTOP,
    HID_USAGE_CONSUMER_CONTROL,
    HID_USAGE_KEYBOARD,
    HID_USAGE_MOUSE,
)
from .capture import (
    CaptureMismatchError,
    CaptureTimeoutError,
    ConsumerSequenceMatcher,
    GadgetNodeCandidates,
    KeyboardSequenceMatcher,
    MissingNodeError,
    MouseSequenceMatcher,
    candidate_progress_details,
    progress_summary_details,
)
from .constants import EXIT_ACCESS, EXIT_OK
from .result import GadgetNodes, LoopbackResult
from .scenarios import BTN_EXTRA, BTN_LEFT, BTN_MIDDLE, BTN_RIGHT, BTN_SIDE, EV_KEY, EVENT_CODE_NAMES, get_scenario

IS_WINDOWS = sys.platform == "win32"

if not IS_WINDOWS:
    # Some non-Windows Python builds expose an incomplete ctypes.wintypes
    # surface even though the module itself imports successfully.
    for _name, _fallback in {
        "ATOM": ctypes.c_ushort,
        "BOOL": ctypes.c_long,
        "DWORD": ctypes.c_ulong,
        "HANDLE": ctypes.c_void_p,
        "HBRUSH": ctypes.c_void_p,
        "HCURSOR": ctypes.c_void_p,
        "HICON": ctypes.c_void_p,
        "HINSTANCE": ctypes.c_void_p,
        "HMENU": ctypes.c_void_p,
        "HMODULE": ctypes.c_void_p,
        "HWND": ctypes.c_void_p,
        "LONG": ctypes.c_long,
        "LPARAM": ctypes.c_long,
        "LPCWSTR": ctypes.c_wchar_p,
        "LPVOID": ctypes.c_void_p,
        "UINT": ctypes.c_uint,
        "ULONG": ctypes.c_ulong,
        "USHORT": ctypes.c_ushort,
        "WPARAM": ctypes.c_ulong,
    }.items():
        if not hasattr(wintypes, _name):
            setattr(wintypes, _name, _fallback)

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
RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002
RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
RI_MOUSE_RIGHT_BUTTON_UP = 0x0008
RI_MOUSE_MIDDLE_BUTTON_DOWN = 0x0010
RI_MOUSE_MIDDLE_BUTTON_UP = 0x0020
RI_MOUSE_BUTTON_4_DOWN = 0x0040
RI_MOUSE_BUTTON_4_UP = 0x0080
RI_MOUSE_BUTTON_5_DOWN = 0x0100
RI_MOUSE_BUTTON_5_UP = 0x0200
RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HORIZONTAL_WHEEL = 0x0800
CW_USEDEFAULT = -2147483648
HID_MOUSE_I16_MIN = -32767
HID_MOUSE_I16_MAX = 32767
UINT32_ERROR = 0xFFFFFFFF
RAW_INPUT_BUTTON_FLAGS_MASK = 0xFFFF
RAW_INPUT_WHEEL_VALUE_SHIFT = 16
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_SNAPSHOT = 0x2C
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_APPS = 0x5D
VK_NUMPAD0 = 0x60
VK_MULTIPLY = 0x6A
VK_ADD = 0x6B
VK_SUBTRACT = 0x6D
VK_DECIMAL = 0x6E
VK_DIVIDE = 0x6F
VK_F1 = 0x70
VK_F13 = 0x7C
VK_F14 = 0x7D
VK_F15 = 0x7E
VK_F24 = 0x87
VK_NUMLOCK = 0x90
VK_SCROLL = 0x91
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_OEM_1 = 0xBA
VK_OEM_PLUS = 0xBB
VK_OEM_COMMA = 0xBC
VK_OEM_MINUS = 0xBD
VK_OEM_PERIOD = 0xBE
VK_OEM_2 = 0xBF
VK_OEM_3 = 0xC0
VK_OEM_4 = 0xDB
VK_OEM_5 = 0xDC
VK_OEM_6 = 0xDD
VK_OEM_7 = 0xDE
VK_OEM_102 = 0xE2

VK_TO_EVDEV = {
    VK_BACK: ecodes.KEY_BACKSPACE,
    VK_TAB: ecodes.KEY_TAB,
    VK_RETURN: ecodes.KEY_ENTER,
    VK_SHIFT: ecodes.KEY_LEFTSHIFT,
    VK_CONTROL: ecodes.KEY_LEFTCTRL,
    VK_MENU: ecodes.KEY_LEFTALT,
    VK_ESCAPE: ecodes.KEY_ESC,
    VK_SPACE: ecodes.KEY_SPACE,
    VK_PRIOR: ecodes.KEY_PAGEUP,
    VK_NEXT: ecodes.KEY_PAGEDOWN,
    VK_END: ecodes.KEY_END,
    VK_HOME: ecodes.KEY_HOME,
    VK_LEFT: ecodes.KEY_LEFT,
    VK_UP: ecodes.KEY_UP,
    VK_RIGHT: ecodes.KEY_RIGHT,
    VK_DOWN: ecodes.KEY_DOWN,
    VK_SNAPSHOT: ecodes.KEY_SYSRQ,
    VK_INSERT: ecodes.KEY_INSERT,
    VK_DELETE: ecodes.KEY_DELETE,
    **{ord(str(number)): getattr(ecodes, f"KEY_{number}") for number in range(10)},
    **{ord(letter): getattr(ecodes, f"KEY_{letter}") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    VK_LWIN: ecodes.KEY_LEFTMETA,
    VK_RWIN: ecodes.KEY_RIGHTMETA,
    VK_APPS: ecodes.KEY_COMPOSE,
    **{VK_NUMPAD0 + number: getattr(ecodes, f"KEY_KP{number}") for number in range(10)},
    VK_MULTIPLY: ecodes.KEY_KPASTERISK,
    VK_ADD: ecodes.KEY_KPPLUS,
    VK_SUBTRACT: ecodes.KEY_KPMINUS,
    VK_DECIMAL: ecodes.KEY_KPDOT,
    VK_DIVIDE: ecodes.KEY_KPSLASH,
    **{VK_F1 + index: getattr(ecodes, f"KEY_F{index + 1}") for index in range(24)},
    VK_NUMLOCK: ecodes.KEY_NUMLOCK,
    VK_SCROLL: ecodes.KEY_SCROLLLOCK,
    VK_LSHIFT: ecodes.KEY_LEFTSHIFT,
    VK_RSHIFT: ecodes.KEY_RIGHTSHIFT,
    VK_LCONTROL: ecodes.KEY_LEFTCTRL,
    VK_RCONTROL: ecodes.KEY_RIGHTCTRL,
    VK_LMENU: ecodes.KEY_LEFTALT,
    VK_RMENU: ecodes.KEY_RIGHTALT,
    VK_OEM_1: ecodes.KEY_SEMICOLON,
    VK_OEM_PLUS: ecodes.KEY_EQUAL,
    VK_OEM_COMMA: ecodes.KEY_COMMA,
    VK_OEM_MINUS: ecodes.KEY_MINUS,
    VK_OEM_PERIOD: ecodes.KEY_DOT,
    VK_OEM_2: ecodes.KEY_SLASH,
    VK_OEM_3: ecodes.KEY_GRAVE,
    VK_OEM_4: ecodes.KEY_LEFTBRACE,
    VK_OEM_5: ecodes.KEY_BACKSLASH,
    VK_OEM_6: ecodes.KEY_RIGHTBRACE,
    VK_OEM_7: ecodes.KEY_APOSTROPHE,
    VK_OEM_102: ecodes.KEY_102ND,
}


def _mapped_hid_usage(evdev_code: int) -> int | None:
    usage, _name = evdev_to_usb_hid(SimpleNamespace(scancode=evdev_code, keystate=KeyEvent.key_down))
    return usage


VK_TO_HID = {vkey: usage for vkey, evdev_code in VK_TO_EVDEV.items() if (usage := _mapped_hid_usage(evdev_code))}

RAW_MOUSE_BUTTON_BITS = (
    (RI_MOUSE_LEFT_BUTTON_DOWN, RI_MOUSE_LEFT_BUTTON_UP, 0x01),
    (RI_MOUSE_RIGHT_BUTTON_DOWN, RI_MOUSE_RIGHT_BUTTON_UP, 0x02),
    (RI_MOUSE_MIDDLE_BUTTON_DOWN, RI_MOUSE_MIDDLE_BUTTON_UP, 0x04),
    (RI_MOUSE_BUTTON_4_DOWN, RI_MOUSE_BUTTON_4_UP, 0x08),
    (RI_MOUSE_BUTTON_5_DOWN, RI_MOUSE_BUTTON_5_UP, 0x10),
)
WINDOWS_RAW_INPUT_MOUSE_BUTTON_CODES = {BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA}


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
    _fields_ = [("mouse", RAWMOUSE), ("keyboard", RAWKEYBOARD)]


class RAWINPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("header", RAWINPUTHEADER), ("data", RAWINPUTUNION)]


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
    _fields_ = [("mouse", RID_DEVICE_INFO_MOUSE), ("keyboard", RID_DEVICE_INFO_KEYBOARD), ("hid", RID_DEVICE_INFO_HID)]


class RID_DEVICE_INFO(ctypes.Structure):
    _anonymous_ = ("info",)
    _fields_ = [("cbSize", wintypes.DWORD), ("dwType", wintypes.DWORD), ("info", RID_DEVICE_INFO_UNION)]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]


class RAWHIDHEADER(ctypes.Structure):
    _fields_ = [("dwSizeHid", wintypes.DWORD), ("dwCount", wintypes.DWORD)]


class _UnsupportedWin32DLL:
    def __init__(self, dll_name: str) -> None:
        self._dll_name = dll_name

    def __getattr__(self, function_name: str):
        raise RuntimeError(f"{self._dll_name}.{function_name} is only available on Windows")


if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
else:
    user32 = _UnsupportedWin32DLL("user32")
    kernel32 = _UnsupportedWin32DLL("kernel32")

LRESULT = ctypes.c_ssize_t
HRAWINPUT = wintypes.HANDLE

WNDPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

RIDI_DEVICENAME = 0x20000007
RIDI_DEVICEINFO = 0x2000000B
WM_QUIT = 0x0012

if IS_WINDOWS:
    user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
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
    user32.RegisterRawInputDevices.argtypes = (ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT)
    user32.RegisterRawInputDevices.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = (ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
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
    candidate_identities: tuple[str, ...]
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
        device_identity: str,
        candidate_identities: tuple[str, ...],
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
            "device_identity": device_identity,
            "candidate_identities": list(candidate_identities),
            "matched_candidate": matched,
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


def extract_device_identities(nodes: tuple[str | None, ...]) -> tuple[str, ...]:
    identities: list[str] = []
    for node in nodes:
        if not node:
            continue
        identity = stable_device_identity(node)
        if identity not in identities:
            identities.append(identity)
    return tuple(identities)


def _normalize_device_name(name: str) -> str:
    return name.lower().replace("#", "\\")


def stable_device_identity(name: str) -> str:
    normalized = _normalize_device_name(name)
    if normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    parts = [part for part in normalized.split("\\") if part]
    if len(parts) >= 3 and parts[0] == "hid":
        return "\\".join(parts[:3])
    return normalized


def device_matches_candidate(device_name: str, candidate_identities: tuple[str, ...]) -> bool:
    if not candidate_identities:
        return False
    return stable_device_identity(device_name) in candidate_identities


class RawInputKeyboardReportBuilder:
    def __init__(self) -> None:
        self._modifier_state = 0
        self._pressed_keys: tuple[int, ...] = ()

    def report_for(self, vkey: int, *, is_key_up: bool) -> bytes | None:
        hid_code = VK_TO_HID.get(vkey)
        if hid_code is None:
            return None
        modifier = Keycode.modifier_bit(hid_code)
        if is_key_up:
            if modifier:
                self._modifier_state &= ~modifier
            else:
                self._pressed_keys = tuple(key for key in self._pressed_keys if key != hid_code)
        elif modifier:
            self._modifier_state |= modifier
        elif hid_code not in self._pressed_keys:
            self._pressed_keys = (*self._pressed_keys, hid_code)
        return self._current_report()

    def _current_report(self) -> bytes:
        keys = list(self._pressed_keys[:6])
        keys.extend([0] * (6 - len(keys)))
        return bytes([self._modifier_state, 0, *keys])


def keyboard_event_to_report(vkey: int, *, is_key_up: bool) -> bytes | None:
    return RawInputKeyboardReportBuilder().report_for(vkey, is_key_up=is_key_up)


def _mouse_i16_bytes(value: int) -> bytes:
    clamped = min(HID_MOUSE_I16_MAX, max(HID_MOUSE_I16_MIN, value))
    return clamped.to_bytes(2, "little", signed=True)


class RawInputMouseReportBuilder:
    def __init__(self) -> None:
        self._button_state = 0

    def reports_for(self, raw_mouse: RAWMOUSE) -> list[bytes]:
        reports: list[bytes] = []
        button_flags = raw_mouse.ulButtons & RAW_INPUT_BUTTON_FLAGS_MASK
        button_changed = self._apply_button_flags(button_flags)
        wheel_value = ctypes.c_short(
            (raw_mouse.ulButtons >> RAW_INPUT_WHEEL_VALUE_SHIFT) & RAW_INPUT_BUTTON_FLAGS_MASK
        ).value
        wheel = wheel_value if button_flags & RI_MOUSE_WHEEL else 0
        pan = wheel_value if button_flags & RI_MOUSE_HORIZONTAL_WHEEL else 0
        if raw_mouse.lLastX or raw_mouse.lLastY or wheel or pan:
            x_bytes = _mouse_i16_bytes(raw_mouse.lLastX)
            y_bytes = _mouse_i16_bytes(raw_mouse.lLastY)
            reports.append(bytes([self._button_state, *x_bytes, *y_bytes, wheel & 0xFF, pan & 0xFF]))
        if button_changed and not reports:
            reports.append(bytes([self._button_state, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
        return reports

    def _apply_button_flags(self, button_flags: int) -> bool:
        changed = False
        for down_flag, up_flag, button_bit in RAW_MOUSE_BUTTON_BITS:
            if button_flags & down_flag:
                self._button_state |= button_bit
                changed = True
            if button_flags & up_flag:
                self._button_state &= ~button_bit
                changed = True
        return changed


def _unsupported_mouse_buttons(scenario) -> tuple[int, ...]:
    return tuple(
        dict.fromkeys(
            step.code for step in scenario.mouse_button_steps if step.code not in WINDOWS_RAW_INPUT_MOUSE_BUTTON_CODES
        )
    )


def mouse_button_expectations(scenario) -> tuple[tuple, tuple[str, ...]]:
    skipped_codes = _unsupported_mouse_buttons(scenario)
    skipped_names = tuple(EVENT_CODE_NAMES[EV_KEY].get(code, str(code)) for code in skipped_codes)
    supported_steps = tuple(
        step for step in scenario.mouse_button_steps if step.code in WINDOWS_RAW_INPUT_MOUSE_BUTTON_CODES
    )
    return supported_steps, skipped_names


def _get_raw_input_device_name(hdevice: int) -> str:
    size = wintypes.UINT(0)
    if (
        user32.GetRawInputDeviceInfoW(wintypes.HANDLE(hdevice), RIDI_DEVICENAME, None, ctypes.byref(size))
        == UINT32_ERROR
    ):
        raise OSError("GetRawInputDeviceInfoW failed while sizing device name")
    buffer = ctypes.create_unicode_buffer(size.value)
    if (
        user32.GetRawInputDeviceInfoW(wintypes.HANDLE(hdevice), RIDI_DEVICENAME, buffer, ctypes.byref(size))
        == UINT32_ERROR
    ):
        raise OSError("GetRawInputDeviceInfoW failed while reading device name")
    return _normalize_device_name(buffer.value)


def _get_raw_input_device_info(hdevice: int) -> dict[str, object]:
    info = RID_DEVICE_INFO()
    info.cbSize = ctypes.sizeof(RID_DEVICE_INFO)
    size = wintypes.UINT(ctypes.sizeof(RID_DEVICE_INFO))
    if (
        user32.GetRawInputDeviceInfoW(wintypes.HANDLE(hdevice), RIDI_DEVICEINFO, ctypes.byref(info), ctypes.byref(size))
        == UINT32_ERROR
    ):
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
    if user32.GetRawInputDeviceList(None, ctypes.byref(count), entry_size) == UINT32_ERROR:
        raise OSError("GetRawInputDeviceList failed while sizing device list")
    if count.value == 0:
        return []

    raw_list = (RAWINPUTDEVICELIST * count.value)()
    result = user32.GetRawInputDeviceList(raw_list, ctypes.byref(count), entry_size)
    if result == UINT32_ERROR:
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
        devices.append({"device_name": device_name, "dwType": int(entry.dwType), **info})
    return devices


def _register_raw_input(hwnd: int) -> None:
    devices = (RAWINPUTDEVICE * 3)(
        RAWINPUTDEVICE(
            usUsagePage=HID_PAGE_GENERIC_DESKTOP, usUsage=HID_USAGE_KEYBOARD, dwFlags=RIDEV_INPUTSINK, hwndTarget=hwnd
        ),
        RAWINPUTDEVICE(
            usUsagePage=HID_PAGE_GENERIC_DESKTOP, usUsage=HID_USAGE_MOUSE, dwFlags=RIDEV_INPUTSINK, hwndTarget=hwnd
        ),
        RAWINPUTDEVICE(
            usUsagePage=HID_PAGE_CONSUMER, usUsage=HID_USAGE_CONSUMER_CONTROL, dwFlags=RIDEV_INPUTSINK, hwndTarget=hwnd
        ),
    )
    if not user32.RegisterRawInputDevices(devices, len(devices), ctypes.sizeof(RAWINPUTDEVICE)):
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
        0, class_name, class_name, 0, CW_USEDEFAULT, CW_USEDEFAULT, 1, 1, None, None, hinstance, None
    )
    if not hwnd:
        raise OSError("CreateWindowExW failed")
    return hwnd, wndproc


def _read_raw_input(lparam: int) -> tuple[RAWINPUT, bytes]:
    size = wintypes.UINT(0)
    header_size = ctypes.sizeof(RAWINPUTHEADER)
    if user32.GetRawInputData(HRAWINPUT(lparam), RID_INPUT, None, ctypes.byref(size), header_size) == UINT32_ERROR:
        raise OSError("GetRawInputData sizing failed")
    buffer = ctypes.create_string_buffer(size.value)
    if user32.GetRawInputData(HRAWINPUT(lparam), RID_INPUT, buffer, ctypes.byref(size), header_size) == UINT32_ERROR:
        raise OSError("GetRawInputData read failed")
    raw_bytes = buffer.raw[: size.value]
    if len(raw_bytes) < ctypes.sizeof(RAWINPUT):
        raw_bytes += b"\x00" * (ctypes.sizeof(RAWINPUT) - len(raw_bytes))
    return RAWINPUT.from_buffer_copy(raw_bytes[: ctypes.sizeof(RAWINPUT)]), raw_bytes


def _extract_raw_hid_reports(raw_bytes: bytes) -> list[bytes]:
    offset = ctypes.sizeof(RAWINPUTHEADER)
    if len(raw_bytes) < offset + ctypes.sizeof(RAWHIDHEADER):
        return []
    hid_header = RAWHIDHEADER.from_buffer_copy(raw_bytes[offset : offset + ctypes.sizeof(RAWHIDHEADER)])
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


def _raw_input_complete(
    keyboard_candidate: _RawInputCandidate | None,
    mouse_candidate: _RawInputCandidate | None,
    consumer_candidate: _RawInputCandidate | None,
) -> bool:
    return (
        (keyboard_candidate is None or keyboard_candidate.complete)
        and (mouse_candidate is None or mouse_candidate.complete)
        and (consumer_candidate is None or consumer_candidate.complete)
    )


def _raw_input_nodes(
    keyboard_candidate: _RawInputCandidate | None,
    mouse_candidate: _RawInputCandidate | None,
    consumer_candidate: _RawInputCandidate | None,
) -> GadgetNodes:
    return GadgetNodes(
        keyboard_node=(keyboard_candidate.matched_name if keyboard_candidate else None),
        mouse_node=(mouse_candidate.matched_name if mouse_candidate else None),
        consumer_node=(consumer_candidate.matched_name if consumer_candidate else None),
    )


def _raw_input_progress(
    keyboard_candidate: _RawInputCandidate | None,
    mouse_candidate: _RawInputCandidate | None,
    consumer_candidate: _RawInputCandidate | None,
) -> dict[str, list[dict[str, object]]]:
    progress: dict[str, list[dict[str, object]]] = {}
    for candidate in (keyboard_candidate, mouse_candidate, consumer_candidate):
        if candidate is None:
            continue
        progress.setdefault(candidate.role, []).append(
            candidate_progress_details(node=candidate.matched_name, matcher=candidate.matcher)
        )
    return progress


def _raw_input_failure_details(
    timeout_sec: float,
    debug: _RawInputDebug,
    windows_skipped_mouse_buttons: tuple[str, ...],
    keyboard_candidate: _RawInputCandidate | None = None,
    mouse_candidate: _RawInputCandidate | None = None,
    consumer_candidate: _RawInputCandidate | None = None,
) -> dict[str, object]:
    progress = _raw_input_progress(keyboard_candidate, mouse_candidate, consumer_candidate)
    details: dict[str, object] = {
        "capture_backend": "raw_input",
        "timeout_sec": timeout_sec,
        "nodes": _raw_input_nodes(keyboard_candidate, mouse_candidate, consumer_candidate).to_dict(),
        "raw_input_debug": debug.to_dict(),
        "windows_skipped_mouse_buttons": list(windows_skipped_mouse_buttons),
    }
    details.update(progress_summary_details(progress))
    return details


def _raw_input_success_result(
    scenario,
    timeout_sec: float,
    debug: _RawInputDebug,
    keyboard_candidate: _RawInputCandidate | None,
    mouse_candidate: _RawInputCandidate | None,
    consumer_candidate: _RawInputCandidate | None,
    windows_skipped_mouse_buttons: tuple[str, ...],
) -> LoopbackResult:
    nodes = _raw_input_nodes(keyboard_candidate, mouse_candidate, consumer_candidate)
    details: dict[str, object] = {
        "capture_backend": "raw_input",
        "timeout_sec": timeout_sec,
        "nodes": nodes.to_dict(),
        "raw_input_debug": debug.to_dict(),
    }
    if keyboard_candidate is not None:
        details["keyboard_steps_seen"] = keyboard_candidate.matcher.index
        details["keyboard_reports_seen"] = list(keyboard_candidate.matched_reports)
    if mouse_candidate is not None:
        details["mouse_rel_steps_seen"] = mouse_candidate.matcher.rel_index
        details["mouse_button_steps_seen"] = mouse_candidate.matcher.button_index
        details["mouse_reports_seen"] = list(mouse_candidate.matched_reports)
        if windows_skipped_mouse_buttons:
            details["windows_skipped_mouse_buttons"] = list(windows_skipped_mouse_buttons)
    if consumer_candidate is not None:
        details["consumer_steps_seen"] = consumer_candidate.matcher.index
        details["consumer_reports_seen"] = list(consumer_candidate.matched_reports)
    return LoopbackResult(
        command="capture",
        scenario=scenario.name,
        success=True,
        exit_code=EXIT_OK,
        message="Observed expected relay events through Windows Raw Input",
        details=details,
    )


def _pump_raw_input(
    timeout_sec: float,
    keyboard_candidate_identities: tuple[str, ...],
    mouse_candidate_identities: tuple[str, ...],
    consumer_candidate_identities: tuple[str, ...],
    scenario_name: str,
    mouse_button_steps: tuple | None = None,
    windows_skipped_mouse_buttons: tuple[str, ...] = (),
) -> LoopbackResult:
    scenario = get_scenario(scenario_name)
    expected_mouse_button_steps = scenario.mouse_button_steps if mouse_button_steps is None else mouse_button_steps
    keyboard_report_builder = RawInputKeyboardReportBuilder()
    mouse_report_builder = RawInputMouseReportBuilder()
    keyboard_candidate = (
        _RawInputCandidate("keyboard", keyboard_candidate_identities, KeyboardSequenceMatcher(scenario.keyboard_steps))
        if scenario.keyboard_enabled
        else None
    )
    mouse_candidate = (
        _RawInputCandidate(
            "mouse",
            mouse_candidate_identities,
            MouseSequenceMatcher.create(scenario.mouse_rel_steps, expected_mouse_button_steps),
        )
        if scenario.mouse_enabled
        else None
    )
    consumer_candidate = (
        _RawInputCandidate("consumer", consumer_candidate_identities, ConsumerSequenceMatcher(scenario.consumer_steps))
        if scenario.consumer_enabled
        else None
    )

    debug = _RawInputDebug()
    hwnd = None
    # Keep the ctypes callback alive for the lifetime of the message window.
    wndproc = None

    try:
        hwnd, wndproc = _create_message_window()
        _register_raw_input(hwnd)
        deadline = time.monotonic() + timeout_sec
        msg = MSG()
        debug.raw_device_list = _list_raw_input_devices()

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
                    device_identity = stable_device_identity(device_name)

                    if raw.header.dwType == RIM_TYPEKEYBOARD and keyboard_candidate:
                        matched = device_matches_candidate(device_name, keyboard_candidate.candidate_identities)
                        report = None
                        if matched:
                            report = keyboard_report_builder.report_for(
                                raw.keyboard.VKey, is_key_up=bool(raw.keyboard.Flags & RI_KEY_BREAK)
                            )
                        debug.note_event(
                            role="keyboard",
                            device_name=device_name,
                            device_identity=device_identity,
                            candidate_identities=keyboard_candidate.candidate_identities,
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
                        keyboard_candidate.matcher.handle(report)

                    elif raw.header.dwType == RIM_TYPEMOUSE and mouse_candidate:
                        matched = device_matches_candidate(device_name, mouse_candidate.candidate_identities)
                        debug.note_event(
                            role="mouse",
                            device_name=device_name,
                            device_identity=device_identity,
                            candidate_identities=mouse_candidate.candidate_identities,
                            matched=matched,
                            rel_x=raw.mouse.lLastX,
                            rel_y=raw.mouse.lLastY,
                        )
                        if not matched:
                            continue
                        mouse_candidate.matched_name = device_name
                        for report in mouse_report_builder.reports_for(raw.mouse):
                            mouse_candidate.note_report(report)
                            mouse_candidate.matcher.handle(report)
                    elif raw.header.dwType == RIM_TYPEHID and consumer_candidate:
                        matched = device_matches_candidate(device_name, consumer_candidate.candidate_identities)
                        for report in _extract_raw_hid_reports(raw_bytes):
                            debug.note_event(
                                role="consumer",
                                device_name=device_name,
                                device_identity=device_identity,
                                candidate_identities=(consumer_candidate.candidate_identities),
                                matched=matched,
                                report=report,
                            )
                            if not matched:
                                continue
                            consumer_candidate.matched_name = device_name
                            consumer_candidate.note_report(report)
                            consumer_candidate.matcher.handle(report)

                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            if _raw_input_complete(keyboard_candidate, mouse_candidate, consumer_candidate):
                return _raw_input_success_result(
                    scenario,
                    timeout_sec,
                    debug,
                    keyboard_candidate,
                    mouse_candidate,
                    consumer_candidate,
                    windows_skipped_mouse_buttons,
                )

            time.sleep(0.01)
    except CaptureMismatchError as exc:
        return LoopbackResult(
            command="capture",
            scenario=scenario.name,
            success=False,
            exit_code=exc.exit_code,
            message=str(exc),
            details=_raw_input_failure_details(
                timeout_sec,
                debug,
                windows_skipped_mouse_buttons,
                keyboard_candidate,
                mouse_candidate,
                consumer_candidate,
            ),
        )
    except OSError as exc:
        return LoopbackResult(
            command="capture",
            scenario=scenario.name,
            success=False,
            exit_code=EXIT_ACCESS,
            message=f"Windows Raw Input capture failed: {exc}",
            details=_raw_input_failure_details(
                timeout_sec,
                debug,
                windows_skipped_mouse_buttons,
                keyboard_candidate,
                mouse_candidate,
                consumer_candidate,
            ),
        )
    finally:
        if hwnd is not None:
            user32.DestroyWindow(hwnd)
        _ = wndproc

    return LoopbackResult(
        command="capture",
        scenario=scenario.name,
        success=False,
        exit_code=CaptureTimeoutError.exit_code,
        message=f"Timed out waiting for {scenario.name} events after {timeout_sec}s",
        details=_raw_input_failure_details(
            timeout_sec, debug, windows_skipped_mouse_buttons, keyboard_candidate, mouse_candidate, consumer_candidate
        ),
    )


def _missing_node_result(scenario_name: str, message: str, candidate_nodes: GadgetNodeCandidates) -> LoopbackResult:
    return LoopbackResult(
        command="capture",
        scenario=scenario_name,
        success=False,
        exit_code=MissingNodeError.exit_code,
        message=message,
        details={
            "capture_backend": "raw_input",
            "nodes": GadgetNodes(None, None, None).to_dict(),
            "candidates": candidate_nodes.to_dict(),
        },
    )


def run_raw_input_capture(
    scenario_name: str, timeout_sec: float, candidate_nodes: GadgetNodeCandidates
) -> LoopbackResult:
    if not IS_WINDOWS:
        raise RuntimeError("Windows Raw Input capture is only available on Windows")

    scenario = get_scenario(scenario_name)
    mouse_button_steps, windows_skipped_mouse_buttons = mouse_button_expectations(scenario)

    keyboard_candidate_identities: tuple[str, ...] = ()
    mouse_candidate_identities: tuple[str, ...] = ()
    consumer_candidate_identities: tuple[str, ...] = ()
    if scenario.keyboard_enabled:
        if not candidate_nodes.keyboard_nodes:
            return _missing_node_result(scenario.name, "Keyboard HID device was not found", candidate_nodes)
        keyboard_candidate_identities = extract_device_identities(
            tuple(info.node for info in candidate_nodes.keyboard_nodes)
        )
    if scenario.mouse_enabled:
        if not candidate_nodes.mouse_nodes:
            return _missing_node_result(scenario.name, "Mouse HID device was not found", candidate_nodes)
        mouse_candidate_identities = extract_device_identities(tuple(info.node for info in candidate_nodes.mouse_nodes))
    if scenario.consumer_enabled:
        if not candidate_nodes.consumer_nodes:
            return _missing_node_result(scenario.name, "Consumer-control HID device was not found", candidate_nodes)
        consumer_candidate_identities = extract_device_identities(
            tuple(info.node for info in candidate_nodes.consumer_nodes)
        )

    result = _pump_raw_input(
        timeout_sec=timeout_sec,
        keyboard_candidate_identities=keyboard_candidate_identities,
        mouse_candidate_identities=mouse_candidate_identities,
        consumer_candidate_identities=consumer_candidate_identities,
        scenario_name=scenario_name,
        mouse_button_steps=mouse_button_steps,
        windows_skipped_mouse_buttons=windows_skipped_mouse_buttons,
    )
    result.details.setdefault("candidates", candidate_nodes.to_dict())
    return result
