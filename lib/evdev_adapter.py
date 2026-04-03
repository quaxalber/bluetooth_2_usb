from functools import lru_cache

from adafruit_hid.consumer_control import ConsumerControl
from adafruit_hid.consumer_control_code import ConsumerControlCode
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode, MouseButton
from adafruit_hid.mouse import Mouse
from evdev import InputEvent, KeyEvent

from lib.device_link import DeviceLink, DummyGadget
from lib.ecodes import ecodes
import lib.logger


_logger = lib.logger.get_logger()


_EVDEV_TO_HID: dict[int, int] = {
    ecodes.KEY_A: Keycode.A,
    ecodes.KEY_B: Keycode.B,
    ecodes.KEY_C: Keycode.C,
    ecodes.KEY_D: Keycode.D,
    ecodes.KEY_E: Keycode.E,
    ecodes.KEY_F: Keycode.F,
    ecodes.KEY_G: Keycode.G,
    ecodes.KEY_H: Keycode.H,
    ecodes.KEY_I: Keycode.I,
    ecodes.KEY_J: Keycode.J,
    ecodes.KEY_K: Keycode.K,
    ecodes.KEY_L: Keycode.L,
    ecodes.KEY_M: Keycode.M,
    ecodes.KEY_N: Keycode.N,
    ecodes.KEY_O: Keycode.O,
    ecodes.KEY_P: Keycode.P,
    ecodes.KEY_Q: Keycode.Q,
    ecodes.KEY_R: Keycode.R,
    ecodes.KEY_S: Keycode.S,
    ecodes.KEY_T: Keycode.T,
    ecodes.KEY_U: Keycode.U,
    ecodes.KEY_V: Keycode.V,
    ecodes.KEY_W: Keycode.W,
    ecodes.KEY_X: Keycode.X,
    ecodes.KEY_Y: Keycode.Y,
    ecodes.KEY_Z: Keycode.Z,
    ecodes.KEY_1: Keycode.ONE,
    ecodes.KEY_2: Keycode.TWO,
    ecodes.KEY_3: Keycode.THREE,
    ecodes.KEY_4: Keycode.FOUR,
    ecodes.KEY_5: Keycode.FIVE,
    ecodes.KEY_6: Keycode.SIX,
    ecodes.KEY_7: Keycode.SEVEN,
    ecodes.KEY_8: Keycode.EIGHT,
    ecodes.KEY_9: Keycode.NINE,
    ecodes.KEY_0: Keycode.ZERO,
    ecodes.KEY_ENTER: Keycode.ENTER,
    ecodes.KEY_ESC: Keycode.ESCAPE,
    ecodes.KEY_BACKSPACE: Keycode.BACKSPACE,
    ecodes.KEY_TAB: Keycode.TAB,
    ecodes.KEY_SPACE: Keycode.SPACEBAR,
    ecodes.KEY_MINUS: Keycode.MINUS,
    ecodes.KEY_EQUAL: Keycode.EQUALS,
    ecodes.KEY_LEFTBRACE: Keycode.LEFT_BRACKET,
    ecodes.KEY_RIGHTBRACE: Keycode.RIGHT_BRACKET,
    ecodes.KEY_BACKSLASH: Keycode.POUND,
    ecodes.KEY_SEMICOLON: Keycode.SEMICOLON,
    ecodes.KEY_APOSTROPHE: Keycode.QUOTE,
    ecodes.KEY_GRAVE: Keycode.GRAVE_ACCENT,
    ecodes.KEY_COMMA: Keycode.COMMA,
    ecodes.KEY_DOT: Keycode.PERIOD,
    ecodes.KEY_SLASH: Keycode.FORWARD_SLASH,
    ecodes.KEY_CAPSLOCK: Keycode.CAPS_LOCK,
    ecodes.KEY_F1: Keycode.F1,
    ecodes.KEY_F2: Keycode.F2,
    ecodes.KEY_F3: Keycode.F3,
    ecodes.KEY_F4: Keycode.F4,
    ecodes.KEY_F5: Keycode.F5,
    ecodes.KEY_F6: Keycode.F6,
    ecodes.KEY_F7: Keycode.F7,
    ecodes.KEY_F8: Keycode.F8,
    ecodes.KEY_F9: Keycode.F9,
    ecodes.KEY_F10: Keycode.F10,
    ecodes.KEY_F11: Keycode.F11,
    ecodes.KEY_F12: Keycode.F12,
    ecodes.KEY_SYSRQ: Keycode.PRINT_SCREEN,
    ecodes.KEY_SCROLLLOCK: Keycode.SCROLL_LOCK,
    ecodes.KEY_PAUSE: Keycode.PAUSE,
    ecodes.KEY_INSERT: Keycode.INSERT,
    ecodes.KEY_HOME: Keycode.HOME,
    ecodes.KEY_PAGEUP: Keycode.PAGE_UP,
    ecodes.KEY_DELETE: Keycode.DELETE,
    ecodes.KEY_END: Keycode.END,
    ecodes.KEY_PAGEDOWN: Keycode.PAGE_DOWN,
    ecodes.KEY_RIGHT: Keycode.RIGHT_ARROW,
    ecodes.KEY_LEFT: Keycode.LEFT_ARROW,
    ecodes.KEY_DOWN: Keycode.DOWN_ARROW,
    ecodes.KEY_UP: Keycode.UP_ARROW,
    ecodes.KEY_NUMLOCK: Keycode.KEYPAD_NUMLOCK,
    ecodes.KEY_KPSLASH: Keycode.KEYPAD_FORWARD_SLASH,
    ecodes.KEY_KPASTERISK: Keycode.KEYPAD_ASTERISK,
    ecodes.KEY_KPMINUS: Keycode.KEYPAD_MINUS,
    ecodes.KEY_KPPLUS: Keycode.KEYPAD_PLUS,
    ecodes.KEY_KPENTER: Keycode.KEYPAD_ENTER,
    ecodes.KEY_KP1: Keycode.KEYPAD_ONE,
    ecodes.KEY_KP2: Keycode.KEYPAD_TWO,
    ecodes.KEY_KP3: Keycode.KEYPAD_THREE,
    ecodes.KEY_KP4: Keycode.KEYPAD_FOUR,
    ecodes.KEY_KP5: Keycode.KEYPAD_FIVE,
    ecodes.KEY_KP6: Keycode.KEYPAD_SIX,
    ecodes.KEY_KP7: Keycode.KEYPAD_SEVEN,
    ecodes.KEY_KP8: Keycode.KEYPAD_EIGHT,
    ecodes.KEY_KP9: Keycode.KEYPAD_NINE,
    ecodes.KEY_KP0: Keycode.KEYPAD_ZERO,
    ecodes.KEY_KPDOT: Keycode.KEYPAD_PERIOD,
    ecodes.KEY_102ND: Keycode.KEYPAD_BACKSLASH,
    ecodes.KEY_COMPOSE: Keycode.APPLICATION,
    ecodes.KEY_POWER: Keycode.POWER,
    ecodes.KEY_KPEQUAL: Keycode.KEYPAD_EQUALS,
    ecodes.KEY_KPCOMMA: Keycode.KEYPAD_COMMA,
    ecodes.KEY_F13: Keycode.F13,
    ecodes.KEY_F14: Keycode.F14,
    ecodes.KEY_F15: Keycode.F15,
    ecodes.KEY_F16: Keycode.F16,
    ecodes.KEY_F17: Keycode.F17,
    ecodes.KEY_F18: Keycode.F18,
    ecodes.KEY_F19: Keycode.F19,
    ecodes.KEY_F20: Keycode.F20,
    ecodes.KEY_F21: Keycode.F21,
    ecodes.KEY_F22: Keycode.F22,
    ecodes.KEY_F23: Keycode.F23,
    ecodes.KEY_F24: Keycode.F24,
    ecodes.KEY_LEFTCTRL: Keycode.LEFT_CONTROL,
    ecodes.KEY_LEFTSHIFT: Keycode.LEFT_SHIFT,
    ecodes.KEY_LEFTALT: Keycode.LEFT_ALT,
    ecodes.KEY_LEFTMETA: Keycode.LEFT_GUI,
    ecodes.KEY_RIGHTCTRL: Keycode.RIGHT_CONTROL,
    ecodes.KEY_RIGHTSHIFT: Keycode.RIGHT_SHIFT,
    ecodes.KEY_RIGHTALT: Keycode.RIGHT_ALT,
    ecodes.KEY_RIGHTMETA: Keycode.RIGHT_GUI,
    #
    # Mouse buttons
    #
    ecodes.BTN_LEFT: MouseButton.LEFT,
    ecodes.BTN_RIGHT: MouseButton.RIGHT,
    ecodes.BTN_MIDDLE: MouseButton.MIDDLE,
    #
    # Mapping from evdev ecodes to HID UsageIDs from consumer page (0x0C): https://github.com/torvalds/linux/blob/11d3f72613957cba0783938a1ceddffe7dbbf5a1/drivers/hid/hid-input.c#L1069
    #
    ecodes.KEY_POWER: ConsumerControlCode.POWER,
    ecodes.KEY_RESTART: ConsumerControlCode.RESET,
    ecodes.KEY_SLEEP: ConsumerControlCode.SLEEP,
    ecodes.BTN_MISC: ConsumerControlCode.FUNCTION_BUTTONS,
    ecodes.KEY_MENU: ConsumerControlCode.MENU,
    ecodes.KEY_SELECT: ConsumerControlCode.MENU_PICK,
    ecodes.KEY_INFO: ConsumerControlCode.AL_OEM_FEATURES_TIPS_TUTORIAL_BROWSER,
    ecodes.KEY_SUBTITLE: ConsumerControlCode.CLOSED_CAPTION,
    ecodes.KEY_VCR: ConsumerControlCode.MEDIA_SELECT_VCR,
    ecodes.KEY_CAMERA: ConsumerControlCode.SNAPSHOT,
    ecodes.KEY_RED: ConsumerControlCode.RED_MENU_BUTTON,
    ecodes.KEY_GREEN: ConsumerControlCode.GREEN_MENU_BUTTON,
    ecodes.KEY_BLUE: ConsumerControlCode.BLUE_MENU_BUTTON,
    ecodes.KEY_YELLOW: ConsumerControlCode.YELLOW_MENU_BUTTON,
    ecodes.KEY_ASPECT_RATIO: ConsumerControlCode.ASPECT,
    ecodes.KEY_BRIGHTNESSUP: ConsumerControlCode.DISPLAY_BRIGHTNESS_INCREMENT,
    ecodes.KEY_BRIGHTNESSDOWN: ConsumerControlCode.DISPLAY_BRIGHTNESS_DECREMENT,
    ecodes.KEY_BRIGHTNESS_TOGGLE: ConsumerControlCode.DISPLAY_BACKLIGHT_TOGGLE,
    ecodes.KEY_BRIGHTNESS_MIN: ConsumerControlCode.DISPLAY_SET_BRIGHTNESS_TO_MINIMUM,
    ecodes.KEY_BRIGHTNESS_MAX: ConsumerControlCode.DISPLAY_SET_BRIGHTNESS_TO_MAXIMUM,
    ecodes.KEY_BRIGHTNESS_AUTO: ConsumerControlCode.DISPLAY_SET_AUTO_BRIGHTNESS,
    ecodes.KEY_CAMERA_ACCESS_ENABLE: ConsumerControlCode.CAMERA_ACCESS_ENABLED,
    ecodes.KEY_CAMERA_ACCESS_DISABLE: ConsumerControlCode.CAMERA_ACCESS_DISABLED,
    ecodes.KEY_CAMERA_ACCESS_TOGGLE: ConsumerControlCode.CAMERA_ACCESS_TOGGLE,
    ecodes.KEY_KBDILLUMUP: ConsumerControlCode.KEYBOARD_BRIGHTNESS_INCREMENT,
    ecodes.KEY_KBDILLUMDOWN: ConsumerControlCode.KEYBOARD_BRIGHTNESS_DECREMENT,
    ecodes.KEY_KBDILLUMTOGGLE: ConsumerControlCode.KEYBOARD_BACKLIGHT_OOC,
    ecodes.KEY_VIDEO_NEXT: ConsumerControlCode.MODE_STEP,
    ecodes.KEY_LAST: ConsumerControlCode.RECALL_LAST,
    ecodes.KEY_PC: ConsumerControlCode.MEDIA_SELECT_COMPUTER,
    ecodes.KEY_TV: ConsumerControlCode.MEDIA_SELECT_TV,
    ecodes.KEY_WWW: ConsumerControlCode.AL_INTERNET_BROWSER,
    ecodes.KEY_DVD: ConsumerControlCode.MEDIA_SELECT_DVD,
    ecodes.KEY_PHONE: ConsumerControlCode.MEDIA_SELECT_TELEPHONE,
    ecodes.KEY_PROGRAM: ConsumerControlCode.MEDIA_SELECT_PROGRAM_GUIDE,
    ecodes.KEY_VIDEOPHONE: ConsumerControlCode.MEDIA_SELECT_VIDEO_PHONE,
    ecodes.KEY_GAMES: ConsumerControlCode.MEDIA_SELECT_GAMES,
    ecodes.KEY_MEMO: ConsumerControlCode.MEDIA_SELECT_MESSAGES,
    ecodes.KEY_CD: ConsumerControlCode.MEDIA_SELECT_CD,
    ecodes.KEY_TUNER: ConsumerControlCode.MEDIA_SELECT_TUNER,
    ecodes.KEY_EXIT: ConsumerControlCode.AC_EXIT,
    ecodes.KEY_HELP: ConsumerControlCode.AL_INTEGRATED_HELP_CENTER,
    ecodes.KEY_TAPE: ConsumerControlCode.MEDIA_SELECT_TAPE,
    ecodes.KEY_TV2: ConsumerControlCode.MEDIA_SELECT_CABLE,
    ecodes.KEY_SAT: ConsumerControlCode.MEDIA_SELECT_SATELLITE,
    ecodes.KEY_PVR: ConsumerControlCode.MEDIA_SELECT_HOME,
    ecodes.KEY_CHANNELUP: ConsumerControlCode.CHANNEL_INCREMENT,
    ecodes.KEY_CHANNELDOWN: ConsumerControlCode.CHANNEL_DECREMENT,
    ecodes.KEY_VCR2: ConsumerControlCode.VCR_PLUS,
    ecodes.KEY_PLAY: ConsumerControlCode.PLAY,
    ecodes.KEY_PAUSE: ConsumerControlCode.PAUSE,
    ecodes.KEY_RECORD: ConsumerControlCode.RECORD,
    ecodes.KEY_FASTFORWARD: ConsumerControlCode.FAST_FORWARD,
    ecodes.KEY_REWIND: ConsumerControlCode.REWIND,
    ecodes.KEY_NEXTSONG: ConsumerControlCode.SCAN_NEXT_TRACK,
    ecodes.KEY_PREVIOUSSONG: ConsumerControlCode.SCAN_PREVIOUS_TRACK,
    ecodes.KEY_STOPCD: ConsumerControlCode.STOP,
    ecodes.KEY_EJECTCD: ConsumerControlCode.EJECT,
    ecodes.KEY_MEDIA_REPEAT: ConsumerControlCode.REPEAT,
    ecodes.KEY_SHUFFLE: ConsumerControlCode.RANDOM_PLAY,
    ecodes.KEY_SLOW: ConsumerControlCode.SLOW,
    ecodes.KEY_PLAYPAUSE: ConsumerControlCode.PLAY_PAUSE,
    ecodes.KEY_VOICECOMMAND: ConsumerControlCode.VOICE_COMMAND,
    ecodes.KEY_DICTATE: ConsumerControlCode.START_OR_STOP_VOICE_DICTATION_SESSION,
    ecodes.KEY_EMOJI_PICKER: ConsumerControlCode.INVOKE_OR_DISMISS_EMOJI_PICKER,
    ecodes.KEY_MUTE: ConsumerControlCode.MUTE,
    ecodes.KEY_BASSBOOST: ConsumerControlCode.BASS_BOOST,
    ecodes.KEY_VOLUMEUP: ConsumerControlCode.VOLUME_INCREMENT,
    ecodes.KEY_VOLUMEDOWN: ConsumerControlCode.VOLUME_DECREMENT,
    ecodes.KEY_BUTTONCONFIG: ConsumerControlCode.AL_LAUNCH_BUTTON_CONFIGURATION_TOOL,
    ecodes.KEY_BOOKMARKS: ConsumerControlCode.AC_BOOKMARKS,
    ecodes.KEY_CONFIG: ConsumerControlCode.AL_CONSUMER_CONTROL_CONFIGURATION_TOOL,
    ecodes.KEY_WORDPROCESSOR: ConsumerControlCode.AL_WORD_PROCESSOR,
    ecodes.KEY_EDITOR: ConsumerControlCode.AL_TEXT_EDITOR,
    ecodes.KEY_SPREADSHEET: ConsumerControlCode.AL_SPREADSHEET,
    ecodes.KEY_GRAPHICSEDITOR: ConsumerControlCode.AL_GRAPHICS_EDITOR,
    ecodes.KEY_PRESENTATION: ConsumerControlCode.AL_PRESENTATION_APP,
    ecodes.KEY_DATABASE: ConsumerControlCode.AL_DATABASE_APP,
    ecodes.KEY_MAIL: ConsumerControlCode.AL_EMAIL_READER,
    ecodes.KEY_NEWS: ConsumerControlCode.AL_NEWSREADER,
    ecodes.KEY_VOICEMAIL: ConsumerControlCode.AL_VOICEMAIL,
    ecodes.KEY_ADDRESSBOOK: ConsumerControlCode.AL_CONTACTS_ADDRESS_BOOK,
    ecodes.KEY_CALENDAR: ConsumerControlCode.AL_CALENDAR_SCHEDULE,
    ecodes.KEY_TASKMANAGER: ConsumerControlCode.AL_TASK_PROJECT_MANAGER,
    ecodes.KEY_JOURNAL: ConsumerControlCode.AL_LOG_JOURNAL_TIMECARD,
    ecodes.KEY_FINANCE: ConsumerControlCode.AL_CHECKBOOK_FINANCE,
    ecodes.KEY_CALC: ConsumerControlCode.AL_CALCULATOR,
    ecodes.KEY_PLAYER: ConsumerControlCode.AL_AV_CAPTURE_PLAYBACK,
    ecodes.KEY_FILE: ConsumerControlCode.AL_FILE_BROWSER,
    ecodes.KEY_CHAT: ConsumerControlCode.AL_NETWORK_CHAT,
    ecodes.KEY_LOGOFF: ConsumerControlCode.AL_LOGOFF,
    ecodes.KEY_COFFEE: ConsumerControlCode.AL_TERMINAL_LOCK_SCREENSAVER,
    ecodes.KEY_CONTROLPANEL: ConsumerControlCode.AL_CONTROL_PANEL,
    ecodes.KEY_APPSELECT: ConsumerControlCode.AL_SELECT_TASK_APPLICATION,
    ecodes.KEY_NEXT: ConsumerControlCode.AL_NEXT_TASK_APPLICATION,
    ecodes.KEY_PREVIOUS: ConsumerControlCode.AL_PREVIOUS_TASK_APPLICATION,
    ecodes.KEY_DOCUMENTS: ConsumerControlCode.AL_DOCUMENTS,
    ecodes.KEY_SPELLCHECK: ConsumerControlCode.AL_SPELL_CHECK,
    ecodes.KEY_KEYBOARD: ConsumerControlCode.AL_KEYBOARD_LAYOUT,
    ecodes.KEY_SCREENSAVER: ConsumerControlCode.AL_SCREEN_SAVER,
    ecodes.KEY_IMAGES: ConsumerControlCode.AL_IMAGE_BROWSER,
    ecodes.KEY_AUDIO: ConsumerControlCode.AL_AUDIO_BROWSER,
    ecodes.KEY_VIDEO: ConsumerControlCode.AL_MOVIE_BROWSER,
    ecodes.KEY_MESSENGER: ConsumerControlCode.AL_INSTANT_MESSAGING,
    ecodes.KEY_ASSISTANT: ConsumerControlCode.AL_CONTEXT_AWARE_DESKTOP_ASSISTANT,
    ecodes.KEY_NEW: ConsumerControlCode.AC_NEW,
    ecodes.KEY_OPEN: ConsumerControlCode.AC_OPEN,
    ecodes.KEY_CLOSE: ConsumerControlCode.AC_CLOSE,
    ecodes.KEY_SAVE: ConsumerControlCode.AC_SAVE,
    ecodes.KEY_PRINT: ConsumerControlCode.AC_PRINT,
    ecodes.KEY_PROPS: ConsumerControlCode.AC_PROPERTIES,
    ecodes.KEY_UNDO: ConsumerControlCode.AC_UNDO,
    ecodes.KEY_COPY: ConsumerControlCode.AC_COPY,
    ecodes.KEY_CUT: ConsumerControlCode.AC_CUT,
    ecodes.KEY_PASTE: ConsumerControlCode.AC_PASTE,
    ecodes.KEY_FIND: ConsumerControlCode.AC_FIND,
    ecodes.KEY_SEARCH: ConsumerControlCode.AC_SEARCH,
    ecodes.KEY_GOTO: ConsumerControlCode.AC_GO_TO,
    ecodes.KEY_HOMEPAGE: ConsumerControlCode.AC_HOME,
    ecodes.KEY_BACK: ConsumerControlCode.AC_BACK,
    ecodes.KEY_FORWARD: ConsumerControlCode.AC_FORWARD,
    ecodes.KEY_STOP: ConsumerControlCode.AC_STOP,
    ecodes.KEY_REFRESH: ConsumerControlCode.AC_REFRESH,
    ecodes.KEY_ZOOMIN: ConsumerControlCode.AC_ZOOM_IN,
    ecodes.KEY_ZOOMOUT: ConsumerControlCode.AC_ZOOM_OUT,
    ecodes.KEY_ZOOMRESET: ConsumerControlCode.AC_ZOOM,
    ecodes.KEY_FULL_SCREEN: ConsumerControlCode.AC_VIEW_TOGGLE,
    ecodes.KEY_SCROLLUP: ConsumerControlCode.AC_SCROLL_UP,
    ecodes.KEY_SCROLLDOWN: ConsumerControlCode.AC_SCROLL_DOWN,
    ecodes.KEY_EDIT: ConsumerControlCode.AC_EDIT,
    ecodes.KEY_CANCEL: ConsumerControlCode.AC_CANCEL,
    ecodes.KEY_INSERT: ConsumerControlCode.AC_INSERT_MODE,
    ecodes.KEY_DELETE: ConsumerControlCode.AC_DELETE,
    ecodes.KEY_REDO: ConsumerControlCode.AC_REDO_REPEAT,
    ecodes.KEY_REPLY: ConsumerControlCode.AC_REPLY,
    ecodes.KEY_FORWARDMAIL: ConsumerControlCode.AC_FORWARD_MSG,
    ecodes.KEY_SEND: ConsumerControlCode.AC_SEND,
    ecodes.KEY_KBD_LAYOUT_NEXT: ConsumerControlCode.AC_NEXT_KEYBOARD_LAYOUT_SELECT,
    ecodes.KEY_ALL_APPLICATIONS: ConsumerControlCode.AC_DESKTOP_SHOW_ALL_APPLICATIONS,
    ecodes.KEY_KBDINPUTASSIST_PREV: ConsumerControlCode.KEYBOARD_INPUT_ASSIST_PREVIOUS,
    ecodes.KEY_KBDINPUTASSIST_NEXT: ConsumerControlCode.KEYBOARD_INPUT_ASSIST_NEXT,
    ecodes.KEY_KBDINPUTASSIST_PREVGROUP: ConsumerControlCode.KEYBOARD_INPUT_ASSIST_PREVIOUS_GROUP,
    ecodes.KEY_KBDINPUTASSIST_NEXTGROUP: ConsumerControlCode.KEYBOARD_INPUT_ASSIST_NEXT_GROUP,
    ecodes.KEY_KBDINPUTASSIST_ACCEPT: ConsumerControlCode.KEYBOARD_INPUT_ASSIST_ACCEPT,
    ecodes.KEY_KBDINPUTASSIST_CANCEL: ConsumerControlCode.KEYBOARD_INPUT_ASSIST_CANCEL,
    ecodes.KEY_SCALE: ConsumerControlCode.AC_DESKTOP_SHOW_ALL_WINDOWS,
}
"""Mapping from evdev ecode to HID UsageID"""


_CONSUMER_KEYS = set(
    (
        ecodes.KEY_POWER,
        ecodes.KEY_RESTART,
        ecodes.KEY_SLEEP,
        ecodes.BTN_MISC,
        ecodes.KEY_MENU,
        ecodes.KEY_SELECT,
        ecodes.KEY_INFO,
        ecodes.KEY_SUBTITLE,
        ecodes.KEY_VCR,
        ecodes.KEY_CAMERA,
        ecodes.KEY_RED,
        ecodes.KEY_GREEN,
        ecodes.KEY_BLUE,
        ecodes.KEY_YELLOW,
        ecodes.KEY_ASPECT_RATIO,
        ecodes.KEY_BRIGHTNESSUP,
        ecodes.KEY_BRIGHTNESSDOWN,
        ecodes.KEY_BRIGHTNESS_TOGGLE,
        ecodes.KEY_BRIGHTNESS_MIN,
        ecodes.KEY_BRIGHTNESS_MAX,
        ecodes.KEY_BRIGHTNESS_AUTO,
        ecodes.KEY_CAMERA_ACCESS_ENABLE,
        ecodes.KEY_CAMERA_ACCESS_DISABLE,
        ecodes.KEY_CAMERA_ACCESS_TOGGLE,
        ecodes.KEY_KBDILLUMUP,
        ecodes.KEY_KBDILLUMDOWN,
        ecodes.KEY_KBDILLUMTOGGLE,
        ecodes.KEY_VIDEO_NEXT,
        ecodes.KEY_LAST,
        ecodes.KEY_PC,
        ecodes.KEY_TV,
        ecodes.KEY_WWW,
        ecodes.KEY_DVD,
        ecodes.KEY_PHONE,
        ecodes.KEY_PROGRAM,
        ecodes.KEY_VIDEOPHONE,
        ecodes.KEY_GAMES,
        ecodes.KEY_MEMO,
        ecodes.KEY_CD,
        ecodes.KEY_TUNER,
        ecodes.KEY_EXIT,
        ecodes.KEY_HELP,
        ecodes.KEY_TAPE,
        ecodes.KEY_TV2,
        ecodes.KEY_SAT,
        ecodes.KEY_PVR,
        ecodes.KEY_CHANNELUP,
        ecodes.KEY_CHANNELDOWN,
        ecodes.KEY_VCR2,
        ecodes.KEY_PLAY,
        ecodes.KEY_PAUSE,
        ecodes.KEY_RECORD,
        ecodes.KEY_FASTFORWARD,
        ecodes.KEY_REWIND,
        ecodes.KEY_NEXTSONG,
        ecodes.KEY_PREVIOUSSONG,
        ecodes.KEY_STOPCD,
        ecodes.KEY_EJECTCD,
        ecodes.KEY_MEDIA_REPEAT,
        ecodes.KEY_SHUFFLE,
        ecodes.KEY_SLOW,
        ecodes.KEY_PLAYPAUSE,
        ecodes.KEY_VOICECOMMAND,
        ecodes.KEY_DICTATE,
        ecodes.KEY_EMOJI_PICKER,
        ecodes.KEY_MUTE,
        ecodes.KEY_BASSBOOST,
        ecodes.KEY_VOLUMEUP,
        ecodes.KEY_VOLUMEDOWN,
        ecodes.KEY_BUTTONCONFIG,
        ecodes.KEY_BOOKMARKS,
        ecodes.KEY_CONFIG,
        ecodes.KEY_WORDPROCESSOR,
        ecodes.KEY_EDITOR,
        ecodes.KEY_SPREADSHEET,
        ecodes.KEY_GRAPHICSEDITOR,
        ecodes.KEY_PRESENTATION,
        ecodes.KEY_DATABASE,
        ecodes.KEY_MAIL,
        ecodes.KEY_NEWS,
        ecodes.KEY_VOICEMAIL,
        ecodes.KEY_ADDRESSBOOK,
        ecodes.KEY_CALENDAR,
        ecodes.KEY_TASKMANAGER,
        ecodes.KEY_JOURNAL,
        ecodes.KEY_FINANCE,
        ecodes.KEY_CALC,
        ecodes.KEY_PLAYER,
        ecodes.KEY_FILE,
        ecodes.KEY_CHAT,
        ecodes.KEY_LOGOFF,
        ecodes.KEY_COFFEE,
        ecodes.KEY_CONTROLPANEL,
        ecodes.KEY_APPSELECT,
        ecodes.KEY_NEXT,
        ecodes.KEY_PREVIOUS,
        ecodes.KEY_DOCUMENTS,
        ecodes.KEY_SPELLCHECK,
        ecodes.KEY_KEYBOARD,
        ecodes.KEY_SCREENSAVER,
        ecodes.KEY_IMAGES,
        ecodes.KEY_AUDIO,
        ecodes.KEY_VIDEO,
        ecodes.KEY_MESSENGER,
        ecodes.KEY_ASSISTANT,
        ecodes.KEY_NEW,
        ecodes.KEY_OPEN,
        ecodes.KEY_CLOSE,
        ecodes.KEY_SAVE,
        ecodes.KEY_PRINT,
        ecodes.KEY_PROPS,
        ecodes.KEY_UNDO,
        ecodes.KEY_COPY,
        ecodes.KEY_CUT,
        ecodes.KEY_PASTE,
        ecodes.KEY_FIND,
        ecodes.KEY_SEARCH,
        ecodes.KEY_GOTO,
        ecodes.KEY_HOMEPAGE,
        ecodes.KEY_BACK,
        ecodes.KEY_FORWARD,
        ecodes.KEY_STOP,
        ecodes.KEY_REFRESH,
        ecodes.KEY_ZOOMIN,
        ecodes.KEY_ZOOMOUT,
        ecodes.KEY_ZOOMRESET,
        ecodes.KEY_FULL_SCREEN,
        ecodes.KEY_SCROLLUP,
        ecodes.KEY_SCROLLDOWN,
        ecodes.KEY_EDIT,
        ecodes.KEY_CANCEL,
        ecodes.KEY_INSERT,
        ecodes.KEY_DELETE,
        ecodes.KEY_REDO,
        ecodes.KEY_REPLY,
        ecodes.KEY_FORWARDMAIL,
        ecodes.KEY_SEND,
        ecodes.KEY_KBD_LAYOUT_NEXT,
        ecodes.KEY_ALL_APPLICATIONS,
        ecodes.KEY_KBDINPUTASSIST_PREV,
        ecodes.KEY_KBDINPUTASSIST_NEXT,
        ecodes.KEY_KBDINPUTASSIST_PREVGROUP,
        ecodes.KEY_KBDINPUTASSIST_NEXTGROUP,
        ecodes.KEY_KBDINPUTASSIST_ACCEPT,
        ecodes.KEY_KBDINPUTASSIST_CANCEL,
        ecodes.KEY_SCALE,
    )
)
"""evdev ecodes that are mapped to HID UsageIDs from consumer page (0x0C)"""


_MOUSE_BUTTONS = set(
    (
        ecodes.BTN_LEFT,
        ecodes.BTN_RIGHT,
        ecodes.BTN_MIDDLE,
    )
)
"""Mouse button ecodes"""


def to_hid_usage_id(event: InputEvent) -> int | None:
    ecode: int = event.code
    hid_usage_id = _EVDEV_TO_HID.get(ecode, None)

    key_name = find_key_name(event)
    hid_usage_name = find_usage_name(event, hid_usage_id)

    if hid_usage_id is None:
        _logger.debug(f"Unsupported key pressed: 0x{ecode:02X} ({key_name})")
    else:
        _logger.debug(
            f"Converted evdev ecode 0x{ecode:02X} ({key_name}) to HID UsageID 0x{hid_usage_id:02X} ({hid_usage_name})"
        )

    return hid_usage_id


def find_key_name(event: InputEvent) -> str | None:
    ecode: int = event.code

    for attribute in _cached_dir(ecodes):
        if _cached_getattr(ecodes, attribute) == ecode and attribute.startswith(
            ("KEY_", "BTN_")
        ):
            return attribute

    return None


def find_usage_name(event: InputEvent, hid_usage_id: int) -> str | None:
    code_type = get_hid_code_type(event)

    for attribute in _cached_dir(code_type):
        if _cached_getattr(code_type, attribute) == hid_usage_id:
            return attribute

    return None


@lru_cache(maxsize=512)
def _cached_getattr(class_type, attribute):
    return getattr(class_type, attribute, None)


@lru_cache()
def _cached_dir(
    class_type: type,
) -> list[str]:
    return dir(class_type)


def get_hid_code_type(
    event: InputEvent,
) -> type[ConsumerControlCode] | type[Keycode] | type[MouseButton]:
    if is_consumer_key(event):
        return ConsumerControlCode
    elif is_mouse_button(event):
        return MouseButton
    else:
        return Keycode


def get_output_device(
    event: InputEvent, device_link: DeviceLink
) -> ConsumerControl | Keyboard | Mouse | DummyGadget | None:
    output_device = None

    if is_consumer_key(event):
        output_device = device_link.consumer_gadget
    elif is_mouse_button(event):
        output_device = device_link.mouse_gadget
    else:
        output_device = device_link.keyboard_gadget

    if output_device is None:
        _logger.debug("Output device not available!")

    return output_device


def is_mouse_button(event: InputEvent) -> bool:
    return event.code in _MOUSE_BUTTONS


def is_consumer_key(event: InputEvent) -> bool:
    return event.code in _CONSUMER_KEYS


def is_key_event(event: InputEvent) -> bool:
    return event.type == ecodes.EV_KEY


def is_key_up(event: InputEvent) -> bool:
    return is_key_event(event) and event.value == KeyEvent.key_up


def is_key_down(event: InputEvent) -> bool:
    return is_key_event(event) and event.value == KeyEvent.key_down


def is_mouse_movement(event: InputEvent) -> bool:
    return event.type == ecodes.EV_REL


def get_mouse_movement(event: InputEvent) -> tuple[int, int, int]:
    x, y, mwheel = 0, 0, 0

    if event.code == ecodes.REL_X:
        x = event.value
    elif event.code == ecodes.REL_Y:
        y = event.value
    elif event.code == ecodes.REL_WHEEL:
        mwheel = event.value

    return x, y, mwheel
