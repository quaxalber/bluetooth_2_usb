from functools import lru_cache

from adafruit_hid.consumer_control_code import ConsumerControlCode
from adafruit_hid.keycode import Keycode, MouseButton
from evdev import InputEvent, KeyEvent, RelEvent

from .logging import get_logger


_logger = get_logger()


# SPDX-License-Identifier: GPL-2.0-only WITH Linux-syscall-note
#
# Copyright (c) 1999-2002 Vojtech Pavlik
# Copyright (c) 2015 Hans de Goede <hdegoede@redhat.com>
# Copyright (c) 2023 Benjamin T. <evdev@quaxalber.de>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
class ecodes:
    """
    Input event codes

    (Converted C header to Python class. See: https://github.com/torvalds/linux/blob/master/include/uapi/linux/input-event-codes.h)
    """

    # Device properties and quirks
    INPUT_PROP_POINTER = 0x00
    """needs a pointer"""
    INPUT_PROP_DIRECT = 0x01
    """direct input devices"""
    INPUT_PROP_BUTTONPAD = 0x02
    """has button(s) under pad"""
    INPUT_PROP_SEMI_MT = 0x03
    """touch rectangle only"""
    INPUT_PROP_TOPBUTTONPAD = 0x04
    """softbuttons at top of pad"""
    INPUT_PROP_POINTING_STICK = 0x05
    """is a pointing stick"""
    INPUT_PROP_ACCELEROMETER = 0x06
    """has accelerometer"""
    INPUT_PROP_MAX = 0x1F
    INPUT_PROP_CNT = INPUT_PROP_MAX + 1
    # Event types
    EV_SYN = 0x00
    EV_KEY = 0x01
    EV_REL = 0x02
    EV_ABS = 0x03
    EV_MSC = 0x04
    EV_SW = 0x05
    EV_LED = 0x11
    EV_SND = 0x12
    EV_REP = 0x14
    EV_FF = 0x15
    EV_PWR = 0x16
    EV_FF_STATUS = 0x17
    EV_MAX = 0x1F
    EV_CNT = EV_MAX + 1
    # Synchronization events.
    SYN_REPORT = 0x0
    SYN_CONFIG = 0x1
    SYN_MT_REPORT = 0x2
    SYN_DROPPED = 0x3
    SYN_MAX = 0xF
    SYN_CNT = SYN_MAX + 1
    # Keys and buttons
    # Most of the keys/buttons are modeled after USB HUT 1.12
    # (see http://www.usb.org/developers/hidpage).
    # Abbreviations in the comments:
    # AC - Application Control
    # AL - Application Launch Button
    # SC - System Control
    KEY_RESERVED = 0x0
    KEY_ESC = 0x1
    KEY_1 = 0x2
    KEY_2 = 0x3
    KEY_3 = 0x4
    KEY_4 = 0x5
    KEY_5 = 0x6
    KEY_6 = 0x7
    KEY_7 = 0x8
    KEY_8 = 0x9
    KEY_9 = 0xA
    KEY_0 = 0xB
    KEY_MINUS = 0xC
    KEY_EQUAL = 0xD
    KEY_BACKSPACE = 0xE
    KEY_TAB = 0xF
    KEY_Q = 0x10
    KEY_W = 0x11
    KEY_E = 0x12
    KEY_R = 0x13
    KEY_T = 0x14
    KEY_Y = 0x15
    KEY_U = 0x16
    KEY_I = 0x17
    KEY_O = 0x18
    KEY_P = 0x19
    KEY_LEFTBRACE = 0x1A
    KEY_RIGHTBRACE = 0x1B
    KEY_ENTER = 0x1C
    KEY_LEFTCTRL = 0x1D
    KEY_A = 0x1E
    KEY_S = 0x1F
    KEY_D = 0x20
    KEY_F = 0x21
    KEY_G = 0x22
    KEY_H = 0x23
    KEY_J = 0x24
    KEY_K = 0x25
    KEY_L = 0x26
    KEY_SEMICOLON = 0x27
    KEY_APOSTROPHE = 0x28
    KEY_GRAVE = 0x29
    KEY_LEFTSHIFT = 0x2A
    KEY_BACKSLASH = 0x2B
    KEY_Z = 0x2C
    KEY_X = 0x2D
    KEY_C = 0x2E
    KEY_V = 0x2F
    KEY_B = 0x30
    KEY_N = 0x31
    KEY_M = 0x32
    KEY_COMMA = 0x33
    KEY_DOT = 0x34
    KEY_SLASH = 0x35
    KEY_RIGHTSHIFT = 0x36
    KEY_KPASTERISK = 0x37
    KEY_LEFTALT = 0x38
    KEY_SPACE = 0x39
    KEY_CAPSLOCK = 0x3A
    KEY_F1 = 0x3B
    KEY_F2 = 0x3C
    KEY_F3 = 0x3D
    KEY_F4 = 0x3E
    KEY_F5 = 0x3F
    KEY_F6 = 0x40
    KEY_F7 = 0x41
    KEY_F8 = 0x42
    KEY_F9 = 0x43
    KEY_F10 = 0x44
    KEY_NUMLOCK = 0x45
    KEY_SCROLLLOCK = 0x46
    KEY_KP7 = 0x47
    KEY_KP8 = 0x48
    KEY_KP9 = 0x49
    KEY_KPMINUS = 0x4A
    KEY_KP4 = 0x4B
    KEY_KP5 = 0x4C
    KEY_KP6 = 0x4D
    KEY_KPPLUS = 0x4E
    KEY_KP1 = 0x4F
    KEY_KP2 = 0x50
    KEY_KP3 = 0x51
    KEY_KP0 = 0x52
    KEY_KPDOT = 0x53
    KEY_ZENKAKUHANKAKU = 0x55
    KEY_102ND = 0x56
    KEY_F11 = 0x57
    KEY_F12 = 0x58
    KEY_RO = 0x59
    KEY_KATAKANA = 0x5A
    KEY_HIRAGANA = 0x5B
    KEY_HENKAN = 0x5C
    KEY_KATAKANAHIRAGANA = 0x5D
    KEY_MUHENKAN = 0x5E
    KEY_KPJPCOMMA = 0x5F
    KEY_KPENTER = 0x60
    KEY_RIGHTCTRL = 0x61
    KEY_KPSLASH = 0x62
    KEY_SYSRQ = 0x63
    KEY_RIGHTALT = 0x64
    KEY_LINEFEED = 0x65
    KEY_HOME = 0x66
    KEY_UP = 0x67
    KEY_PAGEUP = 0x68
    KEY_LEFT = 0x69
    KEY_RIGHT = 0x6A
    KEY_END = 0x6B
    KEY_DOWN = 0x6C
    KEY_PAGEDOWN = 0x6D
    KEY_INSERT = 0x6E
    KEY_DELETE = 0x6F
    KEY_MACRO = 0x70
    KEY_MUTE = 0x71
    KEY_VOLUMEDOWN = 0x72
    KEY_VOLUMEUP = 0x73
    KEY_POWER = 0x74
    """SC System Power Down"""
    KEY_KPEQUAL = 0x75
    KEY_KPPLUSMINUS = 0x76
    KEY_PAUSE = 0x77
    KEY_SCALE = 0x78
    """AL Compiz Scale (Expose)"""
    KEY_KPCOMMA = 0x79
    KEY_HANGEUL = 0x7A
    KEY_HANGUEL = KEY_HANGEUL
    KEY_HANJA = 0x7B
    KEY_YEN = 0x7C
    KEY_LEFTMETA = 0x7D
    KEY_RIGHTMETA = 0x7E
    KEY_COMPOSE = 0x7F
    KEY_STOP = 0x80
    """AC Stop"""
    KEY_AGAIN = 0x81
    KEY_PROPS = 0x82
    """AC Properties"""
    KEY_UNDO = 0x83
    """AC Undo"""
    KEY_FRONT = 0x84
    KEY_COPY = 0x85
    """AC Copy"""
    KEY_OPEN = 0x86
    """AC Open"""
    KEY_PASTE = 0x87
    """AC Paste"""
    KEY_FIND = 0x88
    """AC Search"""
    KEY_CUT = 0x89
    """AC Cut"""
    KEY_HELP = 0x8A
    """AL Integrated Help Center"""
    KEY_MENU = 0x8B
    """Menu (show menu)"""
    KEY_CALC = 0x8C
    """AL Calculator"""
    KEY_SETUP = 0x8D
    KEY_SLEEP = 0x8E
    """SC System Sleep"""
    KEY_WAKEUP = 0x8F
    """System Wake Up"""
    KEY_FILE = 0x90
    """AL Local Machine Browser"""
    KEY_SENDFILE = 0x91
    KEY_DELETEFILE = 0x92
    KEY_XFER = 0x93
    KEY_PROG1 = 0x94
    KEY_PROG2 = 0x95
    KEY_WWW = 0x96
    """AL Internet Browser"""
    KEY_MSDOS = 0x97
    KEY_COFFEE = 0x98
    """AL Terminal Lock/Screensaver"""
    KEY_SCREENLOCK = KEY_COFFEE
    KEY_ROTATE_DISPLAY = 0x99
    """Display orientation for e.g. tablets"""
    KEY_DIRECTION = KEY_ROTATE_DISPLAY
    KEY_CYCLEWINDOWS = 0x9A
    KEY_MAIL = 0x9B
    KEY_BOOKMARKS = 0x9C
    """AC Bookmarks"""
    KEY_COMPUTER = 0x9D
    KEY_BACK = 0x9E
    """AC Back"""
    KEY_FORWARD = 0x9F
    """AC Forward"""
    KEY_CLOSECD = 0xA0
    KEY_EJECTCD = 0xA1
    KEY_EJECTCLOSECD = 0xA2
    KEY_NEXTSONG = 0xA3
    KEY_PLAYPAUSE = 0xA4
    KEY_PREVIOUSSONG = 0xA5
    KEY_STOPCD = 0xA6
    KEY_RECORD = 0xA7
    KEY_REWIND = 0xA8
    KEY_PHONE = 0xA9
    """Media Select Telephone"""
    KEY_ISO = 0xAA
    KEY_CONFIG = 0xAB
    """AL Consumer Control Configuration"""
    KEY_HOMEPAGE = 0xAC
    """AC Home"""
    KEY_REFRESH = 0xAD
    """AC Refresh"""
    KEY_EXIT = 0xAE
    """AC Exit"""
    KEY_MOVE = 0xAF
    KEY_EDIT = 0xB0
    KEY_SCROLLUP = 0xB1
    KEY_SCROLLDOWN = 0xB2
    KEY_KPLEFTPAREN = 0xB3
    KEY_KPRIGHTPAREN = 0xB4
    KEY_NEW = 0xB5
    """AC New"""
    KEY_REDO = 0xB6
    """AC Redo/Repeat"""
    KEY_F13 = 0xB7
    KEY_F14 = 0xB8
    KEY_F15 = 0xB9
    KEY_F16 = 0xBA
    KEY_F17 = 0xBB
    KEY_F18 = 0xBC
    KEY_F19 = 0xBD
    KEY_F20 = 0xBE
    KEY_F21 = 0xBF
    KEY_F22 = 0xC0
    KEY_F23 = 0xC1
    KEY_F24 = 0xC2
    KEY_PLAYCD = 0xC8
    KEY_PAUSECD = 0xC9
    KEY_PROG3 = 0xCA
    KEY_PROG4 = 0xCB
    KEY_ALL_APPLICATIONS = 0xCC
    """AC Desktop Show All Applications"""
    KEY_DASHBOARD = KEY_ALL_APPLICATIONS
    KEY_SUSPEND = 0xCD
    KEY_CLOSE = 0xCE
    """AC Close"""
    KEY_PLAY = 0xCF
    KEY_FASTFORWARD = 0xD0
    KEY_BASSBOOST = 0xD1
    KEY_PRINT = 0xD2
    """AC Print"""
    KEY_HP = 0xD3
    KEY_CAMERA = 0xD4
    KEY_SOUND = 0xD5
    KEY_QUESTION = 0xD6
    KEY_EMAIL = 0xD7
    KEY_CHAT = 0xD8
    KEY_SEARCH = 0xD9
    KEY_CONNECT = 0xDA
    KEY_FINANCE = 0xDB
    """AL Checkbook/Finance"""
    KEY_SPORT = 0xDC
    KEY_SHOP = 0xDD
    KEY_ALTERASE = 0xDE
    KEY_CANCEL = 0xDF
    """AC Cancel"""
    KEY_BRIGHTNESSDOWN = 0xE0
    KEY_BRIGHTNESSUP = 0xE1
    KEY_MEDIA = 0xE2
    KEY_SWITCHVIDEOMODE = 0xE3
    """Cycle between available video outputs (Monitor/LCD/TV-out/etc)"""
    KEY_KBDILLUMTOGGLE = 0xE4
    KEY_KBDILLUMDOWN = 0xE5
    KEY_KBDILLUMUP = 0xE6
    KEY_SEND = 0xE7
    """AC Send"""
    KEY_REPLY = 0xE8
    """AC Reply"""
    KEY_FORWARDMAIL = 0xE9
    """AC Forward Msg"""
    KEY_SAVE = 0xEA
    """AC Save"""
    KEY_DOCUMENTS = 0xEB
    KEY_BATTERY = 0xEC
    KEY_BLUETOOTH = 0xED
    KEY_WLAN = 0xEE
    KEY_UWB = 0xEF
    KEY_UNKNOWN = 0xF0
    KEY_VIDEO_NEXT = 0xF1
    """drive next video source"""
    KEY_VIDEO_PREV = 0xF2
    """drive previous video source"""
    KEY_BRIGHTNESS_CYCLE = 0xF3
    """brightness up, after max is min"""
    KEY_BRIGHTNESS_AUTO = 0xF4
    """Set Auto Brightness: manual brightness control is off, rely on ambient"""
    KEY_BRIGHTNESS_ZERO = KEY_BRIGHTNESS_AUTO
    KEY_DISPLAY_OFF = 0xF5
    """display device to off state"""
    KEY_WWAN = 0xF6
    """Wireless WAN (LTE, UMTS, GSM, etc.)"""
    KEY_WIMAX = KEY_WWAN
    KEY_RFKILL = 0xF7
    """Key that controls all radios"""
    KEY_MICMUTE = 0xF8
    """Mute / unmute the microphone"""
    # Code 255 is reserved for special needs of AT keyboard driver
    BTN_MISC = 0x100
    BTN_0 = 0x100
    BTN_1 = 0x101
    BTN_2 = 0x102
    BTN_3 = 0x103
    BTN_4 = 0x104
    BTN_5 = 0x105
    BTN_6 = 0x106
    BTN_7 = 0x107
    BTN_8 = 0x108
    BTN_9 = 0x109
    BTN_MOUSE = 0x110
    BTN_LEFT = 0x110
    BTN_RIGHT = 0x111
    BTN_MIDDLE = 0x112
    BTN_SIDE = 0x113
    BTN_EXTRA = 0x114
    BTN_FORWARD = 0x115
    BTN_BACK = 0x116
    BTN_TASK = 0x117
    BTN_JOYSTICK = 0x120
    BTN_TRIGGER = 0x120
    BTN_THUMB = 0x121
    BTN_THUMB2 = 0x122
    BTN_TOP = 0x123
    BTN_TOP2 = 0x124
    BTN_PINKIE = 0x125
    BTN_BASE = 0x126
    BTN_BASE2 = 0x127
    BTN_BASE3 = 0x128
    BTN_BASE4 = 0x129
    BTN_BASE5 = 0x12A
    BTN_BASE6 = 0x12B
    BTN_DEAD = 0x12F
    BTN_GAMEPAD = 0x130
    BTN_SOUTH = 0x130
    BTN_A = BTN_SOUTH
    BTN_EAST = 0x131
    BTN_B = BTN_EAST
    BTN_C = 0x132
    BTN_NORTH = 0x133
    BTN_X = BTN_NORTH
    BTN_WEST = 0x134
    BTN_Y = BTN_WEST
    BTN_Z = 0x135
    BTN_TL = 0x136
    BTN_TR = 0x137
    BTN_TL2 = 0x138
    BTN_TR2 = 0x139
    BTN_SELECT = 0x13A
    BTN_START = 0x13B
    BTN_MODE = 0x13C
    BTN_THUMBL = 0x13D
    BTN_THUMBR = 0x13E
    BTN_DIGI = 0x140
    BTN_TOOL_PEN = 0x140
    BTN_TOOL_RUBBER = 0x141
    BTN_TOOL_BRUSH = 0x142
    BTN_TOOL_PENCIL = 0x143
    BTN_TOOL_AIRBRUSH = 0x144
    BTN_TOOL_FINGER = 0x145
    BTN_TOOL_MOUSE = 0x146
    BTN_TOOL_LENS = 0x147
    BTN_TOOL_QUINTTAP = 0x148
    """Five fingers on trackpad"""
    BTN_STYLUS3 = 0x149
    BTN_TOUCH = 0x14A
    BTN_STYLUS = 0x14B
    BTN_STYLUS2 = 0x14C
    BTN_TOOL_DOUBLETAP = 0x14D
    BTN_TOOL_TRIPLETAP = 0x14E
    BTN_TOOL_QUADTAP = 0x14F
    """Four fingers on trackpad"""
    BTN_WHEEL = 0x150
    BTN_GEAR_DOWN = 0x150
    BTN_GEAR_UP = 0x151
    KEY_OK = 0x160
    KEY_SELECT = 0x161
    KEY_GOTO = 0x162
    KEY_CLEAR = 0x163
    KEY_POWER2 = 0x164
    KEY_OPTION = 0x165
    KEY_INFO = 0x166
    """AL OEM Features/Tips/Tutorial"""
    KEY_TIME = 0x167
    KEY_VENDOR = 0x168
    KEY_ARCHIVE = 0x169
    KEY_PROGRAM = 0x16A
    """Media Select Program Guide"""
    KEY_CHANNEL = 0x16B
    KEY_FAVORITES = 0x16C
    KEY_EPG = 0x16D
    KEY_PVR = 0x16E
    """Media Select Home"""
    KEY_MHP = 0x16F
    KEY_LANGUAGE = 0x170
    KEY_TITLE = 0x171
    KEY_SUBTITLE = 0x172
    KEY_ANGLE = 0x173
    KEY_FULL_SCREEN = 0x174
    """AC View Toggle"""
    KEY_ZOOM = KEY_FULL_SCREEN
    KEY_MODE = 0x175
    KEY_KEYBOARD = 0x176
    KEY_ASPECT_RATIO = 0x177
    """HUTRR37: Aspect"""
    KEY_SCREEN = KEY_ASPECT_RATIO
    KEY_PC = 0x178
    """Media Select Computer"""
    KEY_TV = 0x179
    """Media Select TV"""
    KEY_TV2 = 0x17A
    """Media Select Cable"""
    KEY_VCR = 0x17B
    """Media Select VCR"""
    KEY_VCR2 = 0x17C
    """VCR Plus"""
    KEY_SAT = 0x17D
    """Media Select Satellite"""
    KEY_SAT2 = 0x17E
    KEY_CD = 0x17F
    """Media Select CD"""
    KEY_TAPE = 0x180
    """Media Select Tape"""
    KEY_RADIO = 0x181
    KEY_TUNER = 0x182
    """Media Select Tuner"""
    KEY_PLAYER = 0x183
    KEY_TEXT = 0x184
    KEY_DVD = 0x185
    """Media Select DVD"""
    KEY_AUX = 0x186
    KEY_MP3 = 0x187
    KEY_AUDIO = 0x188
    """AL Audio Browser"""
    KEY_VIDEO = 0x189
    """AL Movie Browser"""
    KEY_DIRECTORY = 0x18A
    KEY_LIST = 0x18B
    KEY_MEMO = 0x18C
    """Media Select Messages"""
    KEY_CALENDAR = 0x18D
    KEY_RED = 0x18E
    KEY_GREEN = 0x18F
    KEY_YELLOW = 0x190
    KEY_BLUE = 0x191
    KEY_CHANNELUP = 0x192
    """Channel Increment"""
    KEY_CHANNELDOWN = 0x193
    """Channel Decrement"""
    KEY_FIRST = 0x194
    KEY_LAST = 0x195
    """Recall Last"""
    KEY_AB = 0x196
    KEY_NEXT = 0x197
    KEY_RESTART = 0x198
    KEY_SLOW = 0x199
    KEY_SHUFFLE = 0x19A
    KEY_BREAK = 0x19B
    KEY_PREVIOUS = 0x19C
    KEY_DIGITS = 0x19D
    KEY_TEEN = 0x19E
    KEY_TWEN = 0x19F
    KEY_VIDEOPHONE = 0x1A0
    """Media Select Video Phone"""
    KEY_GAMES = 0x1A1
    """Media Select Games"""
    KEY_ZOOMIN = 0x1A2
    """AC Zoom In"""
    KEY_ZOOMOUT = 0x1A3
    """AC Zoom Out"""
    KEY_ZOOMRESET = 0x1A4
    """AC Zoom"""
    KEY_WORDPROCESSOR = 0x1A5
    """AL Word Processor"""
    KEY_EDITOR = 0x1A6
    """AL Text Editor"""
    KEY_SPREADSHEET = 0x1A7
    """AL Spreadsheet"""
    KEY_GRAPHICSEDITOR = 0x1A8
    """AL Graphics Editor"""
    KEY_PRESENTATION = 0x1A9
    """AL Presentation App"""
    KEY_DATABASE = 0x1AA
    """AL Database App"""
    KEY_NEWS = 0x1AB
    """AL Newsreader"""
    KEY_VOICEMAIL = 0x1AC
    """AL Voicemail"""
    KEY_ADDRESSBOOK = 0x1AD
    """AL Contacts/Address Book"""
    KEY_MESSENGER = 0x1AE
    """AL Instant Messaging"""
    KEY_DISPLAYTOGGLE = 0x1AF
    """Turn display (LCD) on and off"""
    KEY_BRIGHTNESS_TOGGLE = KEY_DISPLAYTOGGLE
    KEY_SPELLCHECK = 0x1B0
    """AL Spell Check"""
    KEY_LOGOFF = 0x1B1
    """AL Logoff"""
    KEY_DOLLAR = 0x1B2
    KEY_EURO = 0x1B3
    KEY_FRAMEBACK = 0x1B4
    """Consumer - transport controls"""
    KEY_FRAMEFORWARD = 0x1B5
    KEY_CONTEXT_MENU = 0x1B6
    """GenDesc - system context menu"""
    KEY_MEDIA_REPEAT = 0x1B7
    """Consumer - transport control"""
    KEY_10CHANNELSUP = 0x1B8
    """10 channels up (10+)"""
    KEY_10CHANNELSDOWN = 0x1B9
    """10 channels down (10-)"""
    KEY_IMAGES = 0x1BA
    """AL Image Browser"""
    KEY_NOTIFICATION_CENTER = 0x1BC
    """Show/hide the notification center"""
    KEY_PICKUP_PHONE = 0x1BD
    """Answer incoming call"""
    KEY_HANGUP_PHONE = 0x1BE
    """Decline incoming call"""
    KEY_DEL_EOL = 0x1C0
    KEY_DEL_EOS = 0x1C1
    KEY_INS_LINE = 0x1C2
    KEY_DEL_LINE = 0x1C3
    KEY_FN = 0x1D0
    KEY_FN_ESC = 0x1D1
    KEY_FN_F1 = 0x1D2
    KEY_FN_F2 = 0x1D3
    KEY_FN_F3 = 0x1D4
    KEY_FN_F4 = 0x1D5
    KEY_FN_F5 = 0x1D6
    KEY_FN_F6 = 0x1D7
    KEY_FN_F7 = 0x1D8
    KEY_FN_F8 = 0x1D9
    KEY_FN_F9 = 0x1DA
    KEY_FN_F10 = 0x1DB
    KEY_FN_F11 = 0x1DC
    KEY_FN_F12 = 0x1DD
    KEY_FN_1 = 0x1DE
    KEY_FN_2 = 0x1DF
    KEY_FN_D = 0x1E0
    KEY_FN_E = 0x1E1
    KEY_FN_F = 0x1E2
    KEY_FN_S = 0x1E3
    KEY_FN_B = 0x1E4
    KEY_FN_RIGHT_SHIFT = 0x1E5
    KEY_BRL_DOT1 = 0x1F1
    KEY_BRL_DOT2 = 0x1F2
    KEY_BRL_DOT3 = 0x1F3
    KEY_BRL_DOT4 = 0x1F4
    KEY_BRL_DOT5 = 0x1F5
    KEY_BRL_DOT6 = 0x1F6
    KEY_BRL_DOT7 = 0x1F7
    KEY_BRL_DOT8 = 0x1F8
    KEY_BRL_DOT9 = 0x1F9
    KEY_BRL_DOT10 = 0x1FA
    KEY_NUMERIC_0 = 0x200
    """used by phones, remote controls,"""
    KEY_NUMERIC_1 = 0x201
    """and other keypads"""
    KEY_NUMERIC_2 = 0x202
    KEY_NUMERIC_3 = 0x203
    KEY_NUMERIC_4 = 0x204
    KEY_NUMERIC_5 = 0x205
    KEY_NUMERIC_6 = 0x206
    KEY_NUMERIC_7 = 0x207
    KEY_NUMERIC_8 = 0x208
    KEY_NUMERIC_9 = 0x209
    KEY_NUMERIC_STAR = 0x20A
    KEY_NUMERIC_POUND = 0x20B
    KEY_NUMERIC_A = 0x20C
    """Phone key A - HUT Telephony 0xb9"""
    KEY_NUMERIC_B = 0x20D
    KEY_NUMERIC_C = 0x20E
    KEY_NUMERIC_D = 0x20F
    KEY_CAMERA_FOCUS = 0x210
    KEY_WPS_BUTTON = 0x211
    """WiFi Protected Setup key"""
    KEY_TOUCHPAD_TOGGLE = 0x212
    """Request switch touchpad on or off"""
    KEY_TOUCHPAD_ON = 0x213
    KEY_TOUCHPAD_OFF = 0x214
    KEY_CAMERA_ZOOMIN = 0x215
    KEY_CAMERA_ZOOMOUT = 0x216
    KEY_CAMERA_UP = 0x217
    KEY_CAMERA_DOWN = 0x218
    KEY_CAMERA_LEFT = 0x219
    KEY_CAMERA_RIGHT = 0x21A
    KEY_ATTENDANT_ON = 0x21B
    KEY_ATTENDANT_OFF = 0x21C
    KEY_ATTENDANT_TOGGLE = 0x21D
    """Attendant call on or off"""
    KEY_LIGHTS_TOGGLE = 0x21E
    """Reading light on or off"""
    BTN_DPAD_UP = 0x220
    BTN_DPAD_DOWN = 0x221
    BTN_DPAD_LEFT = 0x222
    BTN_DPAD_RIGHT = 0x223
    KEY_ALS_TOGGLE = 0x230
    """Ambient light sensor"""
    KEY_ROTATE_LOCK_TOGGLE = 0x231
    """Display rotation lock"""
    KEY_BUTTONCONFIG = 0x240
    """AL Button Configuration"""
    KEY_TASKMANAGER = 0x241
    """AL Task/Project Manager"""
    KEY_JOURNAL = 0x242
    """AL Log/Journal/Timecard"""
    KEY_CONTROLPANEL = 0x243
    """AL Control Panel"""
    KEY_APPSELECT = 0x244
    """AL Select Task/Application"""
    KEY_SCREENSAVER = 0x245
    """AL Screen Saver"""
    KEY_VOICECOMMAND = 0x246
    """Listening Voice Command"""
    KEY_ASSISTANT = 0x247
    """AL Context-aware desktop assistant"""
    KEY_KBD_LAYOUT_NEXT = 0x248
    """AC Next Keyboard Layout Select"""
    KEY_EMOJI_PICKER = 0x249
    """Show/hide emoji picker (HUTRR101)"""
    KEY_DICTATE = 0x24A
    """Start or Stop Voice Dictation Session (HUTRR99)"""
    KEY_CAMERA_ACCESS_ENABLE = 0x24B
    """Enables programmatic access to camera devices. (HUTRR72)"""
    KEY_CAMERA_ACCESS_DISABLE = 0x24C
    """Disables programmatic access to camera devices. (HUTRR72)"""
    KEY_CAMERA_ACCESS_TOGGLE = 0x24D
    """Toggles the current state of the camera access control. (HUTRR72)"""
    KEY_BRIGHTNESS_MIN = 0x250
    """Set Brightness to Minimum"""
    KEY_BRIGHTNESS_MAX = 0x251
    """Set Brightness to Maximum"""
    KEY_KBDINPUTASSIST_PREV = 0x260
    KEY_KBDINPUTASSIST_NEXT = 0x261
    KEY_KBDINPUTASSIST_PREVGROUP = 0x262
    KEY_KBDINPUTASSIST_NEXTGROUP = 0x263
    KEY_KBDINPUTASSIST_ACCEPT = 0x264
    KEY_KBDINPUTASSIST_CANCEL = 0x265
    # Diagonal movement keys
    KEY_RIGHT_UP = 0x266
    KEY_RIGHT_DOWN = 0x267
    KEY_LEFT_UP = 0x268
    KEY_LEFT_DOWN = 0x269
    KEY_ROOT_MENU = 0x26A
    """Show Device's Root Menu"""
    KEY_MEDIA_TOP_MENU = 0x26B
    """Show Top Menu of the Media (e.g. DVD)"""
    KEY_NUMERIC_11 = 0x26C
    KEY_NUMERIC_12 = 0x26D
    KEY_AUDIO_DESC = 0x26E
    """
    Toggle Audio Description: refers to an audio service that helps blind and
    visually impaired consumers understand the action in a program. Note: in
    some countries this is referred to as "Video Description".
    """
    KEY_3D_MODE = 0x26F
    KEY_NEXT_FAVORITE = 0x270
    KEY_STOP_RECORD = 0x271
    KEY_PAUSE_RECORD = 0x272
    KEY_VOD = 0x273
    """Video on Demand"""
    KEY_UNMUTE = 0x274
    KEY_FASTREVERSE = 0x275
    KEY_SLOWREVERSE = 0x276
    KEY_DATA = 0x277
    """
    Control a data application associated with the currently viewed channel,
    e.g. teletext or data broadcast application (MHEG, MHP, HbbTV, etc.)
    """
    KEY_ONSCREEN_KEYBOARD = 0x278
    KEY_PRIVACY_SCREEN_TOGGLE = 0x279
    """Electronic privacy screen control"""
    KEY_SELECTIVE_SCREENSHOT = 0x27A
    """Select an area of screen to be copied"""
    KEY_NEXT_ELEMENT = 0x27B
    """Move the focus to the next user controllable element within a UI container"""
    KEY_PREVIOUS_ELEMENT = 0x27C
    """Move the focus to the previous user controllable element within a UI container"""
    KEY_AUTOPILOT_ENGAGE_TOGGLE = 0x27D
    """Toggle Autopilot engagement"""
    # Shortcut Keys
    KEY_MARK_WAYPOINT = 0x27E
    KEY_SOS = 0x27F
    KEY_NAV_CHART = 0x280
    KEY_FISHING_CHART = 0x281
    KEY_SINGLE_RANGE_RADAR = 0x282
    KEY_DUAL_RANGE_RADAR = 0x283
    KEY_RADAR_OVERLAY = 0x284
    KEY_TRADITIONAL_SONAR = 0x285
    KEY_CLEARVU_SONAR = 0x286
    KEY_SIDEVU_SONAR = 0x287
    KEY_NAV_INFO = 0x288
    KEY_BRIGHTNESS_MENU = 0x289
    # Some keyboards have keys which do not have a defined meaning, these keys
    # are intended to be programmed / bound to macros by the user. For most
    # keyboards with these macro-keys the key-sequence to inject, or action to
    # take, is all handled by software on the host side. So from the kernel's
    # point of view these are just normal keys.
    # The KEY_MACRO# codes below are intended for such keys, which may be labeled
    # e.g. G1-G18, or S1 - S30. The KEY_MACRO# codes MUST NOT be used for keys
    # where the marking on the key does indicate a defined meaning / purpose.
    # The KEY_MACRO# codes MUST also NOT be used as fallback for when no existing
    # KEY_FOO define matches the marking / purpose. In this case a new KEY_FOO
    # define MUST be added.
    KEY_MACRO1 = 0x290
    KEY_MACRO2 = 0x291
    KEY_MACRO3 = 0x292
    KEY_MACRO4 = 0x293
    KEY_MACRO5 = 0x294
    KEY_MACRO6 = 0x295
    KEY_MACRO7 = 0x296
    KEY_MACRO8 = 0x297
    KEY_MACRO9 = 0x298
    KEY_MACRO10 = 0x299
    KEY_MACRO11 = 0x29A
    KEY_MACRO12 = 0x29B
    KEY_MACRO13 = 0x29C
    KEY_MACRO14 = 0x29D
    KEY_MACRO15 = 0x29E
    KEY_MACRO16 = 0x29F
    KEY_MACRO17 = 0x2A0
    KEY_MACRO18 = 0x2A1
    KEY_MACRO19 = 0x2A2
    KEY_MACRO20 = 0x2A3
    KEY_MACRO21 = 0x2A4
    KEY_MACRO22 = 0x2A5
    KEY_MACRO23 = 0x2A6
    KEY_MACRO24 = 0x2A7
    KEY_MACRO25 = 0x2A8
    KEY_MACRO26 = 0x2A9
    KEY_MACRO27 = 0x2AA
    KEY_MACRO28 = 0x2AB
    KEY_MACRO29 = 0x2AC
    KEY_MACRO30 = 0x2AD
    # Some keyboards with the macro-keys described above have some extra keys
    # for controlling the host-side software responsible for the macro handling:
    # -A macro recording start/stop key. Note that not all keyboards which emit
    # KEY_MACRO_RECORD_START will also emit KEY_MACRO_RECORD_STOP if
    # KEY_MACRO_RECORD_STOP is not advertised, then KEY_MACRO_RECORD_START
    # should be interpreted as a recording start/stop toggle;
    # -Keys for switching between different macro (pre)sets, either a key for
    # cycling through the configured presets or keys to directly select a preset.
    KEY_MACRO_RECORD_START = 0x2B0
    KEY_MACRO_RECORD_STOP = 0x2B1
    KEY_MACRO_PRESET_CYCLE = 0x2B2
    KEY_MACRO_PRESET1 = 0x2B3
    KEY_MACRO_PRESET2 = 0x2B4
    KEY_MACRO_PRESET3 = 0x2B5
    # Some keyboards have a buildin LCD panel where the contents are controlled
    # by the host. Often these have a number of keys directly below the LCD
    # intended for controlling a menu shown on the LCD. These keys often don't
    # have any labeling so we just name them KEY_KBD_LCD_MENU#
    KEY_KBD_LCD_MENU1 = 0x2B8
    KEY_KBD_LCD_MENU2 = 0x2B9
    KEY_KBD_LCD_MENU3 = 0x2BA
    KEY_KBD_LCD_MENU4 = 0x2BB
    KEY_KBD_LCD_MENU5 = 0x2BC
    BTN_TRIGGER_HAPPY = 0x2C0
    BTN_TRIGGER_HAPPY1 = 0x2C0
    BTN_TRIGGER_HAPPY2 = 0x2C1
    BTN_TRIGGER_HAPPY3 = 0x2C2
    BTN_TRIGGER_HAPPY4 = 0x2C3
    BTN_TRIGGER_HAPPY5 = 0x2C4
    BTN_TRIGGER_HAPPY6 = 0x2C5
    BTN_TRIGGER_HAPPY7 = 0x2C6
    BTN_TRIGGER_HAPPY8 = 0x2C7
    BTN_TRIGGER_HAPPY9 = 0x2C8
    BTN_TRIGGER_HAPPY10 = 0x2C9
    BTN_TRIGGER_HAPPY11 = 0x2CA
    BTN_TRIGGER_HAPPY12 = 0x2CB
    BTN_TRIGGER_HAPPY13 = 0x2CC
    BTN_TRIGGER_HAPPY14 = 0x2CD
    BTN_TRIGGER_HAPPY15 = 0x2CE
    BTN_TRIGGER_HAPPY16 = 0x2CF
    BTN_TRIGGER_HAPPY17 = 0x2D0
    BTN_TRIGGER_HAPPY18 = 0x2D1
    BTN_TRIGGER_HAPPY19 = 0x2D2
    BTN_TRIGGER_HAPPY20 = 0x2D3
    BTN_TRIGGER_HAPPY21 = 0x2D4
    BTN_TRIGGER_HAPPY22 = 0x2D5
    BTN_TRIGGER_HAPPY23 = 0x2D6
    BTN_TRIGGER_HAPPY24 = 0x2D7
    BTN_TRIGGER_HAPPY25 = 0x2D8
    BTN_TRIGGER_HAPPY26 = 0x2D9
    BTN_TRIGGER_HAPPY27 = 0x2DA
    BTN_TRIGGER_HAPPY28 = 0x2DB
    BTN_TRIGGER_HAPPY29 = 0x2DC
    BTN_TRIGGER_HAPPY30 = 0x2DD
    BTN_TRIGGER_HAPPY31 = 0x2DE
    BTN_TRIGGER_HAPPY32 = 0x2DF
    BTN_TRIGGER_HAPPY33 = 0x2E0
    BTN_TRIGGER_HAPPY34 = 0x2E1
    BTN_TRIGGER_HAPPY35 = 0x2E2
    BTN_TRIGGER_HAPPY36 = 0x2E3
    BTN_TRIGGER_HAPPY37 = 0x2E4
    BTN_TRIGGER_HAPPY38 = 0x2E5
    BTN_TRIGGER_HAPPY39 = 0x2E6
    BTN_TRIGGER_HAPPY40 = 0x2E7
    # We avoid low common keys in module aliases so they don't get huge.
    KEY_MIN_INTERESTING = KEY_MUTE
    KEY_MAX = 0x2FF
    KEY_CNT = KEY_MAX + 1
    # Relative axes
    REL_X = 0x00
    REL_Y = 0x01
    REL_Z = 0x02
    REL_RX = 0x03
    REL_RY = 0x04
    REL_RZ = 0x05
    REL_HWHEEL = 0x06
    REL_DIAL = 0x07
    REL_WHEEL = 0x08
    REL_MISC = 0x09
    REL_RESERVED = 0x0A
    """
    0x0a is reserved and should not be used in input drivers.
    It was used by HID as REL_MISC+1 and userspace needs to detect if
    the next REL_* event is correct or is just REL_MISC + n.
    We define here REL_RESERVED so userspace can rely on it and detect
    the situation described above.
    """
    REL_WHEEL_HI_RES = 0x0B
    REL_HWHEEL_HI_RES = 0x0C
    REL_MAX = 0x0F
    REL_CNT = REL_MAX + 1
    # Absolute axes
    ABS_X = 0x00
    ABS_Y = 0x01
    ABS_Z = 0x02
    ABS_RX = 0x03
    ABS_RY = 0x04
    ABS_RZ = 0x05
    ABS_THROTTLE = 0x06
    ABS_RUDDER = 0x07
    ABS_WHEEL = 0x08
    ABS_GAS = 0x09
    ABS_BRAKE = 0x0A
    ABS_HAT0X = 0x10
    ABS_HAT0Y = 0x11
    ABS_HAT1X = 0x12
    ABS_HAT1Y = 0x13
    ABS_HAT2X = 0x14
    ABS_HAT2Y = 0x15
    ABS_HAT3X = 0x16
    ABS_HAT3Y = 0x17
    ABS_PRESSURE = 0x18
    ABS_DISTANCE = 0x19
    ABS_TILT_X = 0x1A
    ABS_TILT_Y = 0x1B
    ABS_TOOL_WIDTH = 0x1C
    ABS_VOLUME = 0x20
    ABS_PROFILE = 0x21
    ABS_MISC = 0x28
    ABS_RESERVED = 0x2E
    """
    0x2e is reserved and should not be used in input drivers.
    It was used by HID as ABS_MISC+6 and userspace needs to detect if
    the next ABS_* event is correct or is just ABS_MISC + n.
    We define here ABS_RESERVED so userspace can rely on it and detect
    the situation described above.
    """
    ABS_MT_SLOT = 0x2F
    """MT slot being modified"""
    ABS_MT_TOUCH_MAJOR = 0x30
    """Major axis of touching ellipse"""
    ABS_MT_TOUCH_MINOR = 0x31
    """Minor axis (omit if circular)"""
    ABS_MT_WIDTH_MAJOR = 0x32
    """Major axis of approaching ellipse"""
    ABS_MT_WIDTH_MINOR = 0x33
    """Minor axis (omit if circular)"""
    ABS_MT_ORIENTATION = 0x34
    """Ellipse orientation"""
    ABS_MT_POSITION_X = 0x35
    """Center X touch position"""
    ABS_MT_POSITION_Y = 0x36
    """Center Y touch position"""
    ABS_MT_TOOL_TYPE = 0x37
    """Type of touching device"""
    ABS_MT_BLOB_ID = 0x38
    """Group a set of packets as a blob"""
    ABS_MT_TRACKING_ID = 0x39
    """Unique ID of initiated contact"""
    ABS_MT_PRESSURE = 0x3A
    """Pressure on contact area"""
    ABS_MT_DISTANCE = 0x3B
    """Contact hover distance"""
    ABS_MT_TOOL_X = 0x3C
    """Center X tool position"""
    ABS_MT_TOOL_Y = 0x3D
    """Center Y tool position"""
    ABS_MAX = 0x3F
    ABS_CNT = ABS_MAX + 1
    # Switch events
    SW_LID = 0x00
    """set = lid shut"""
    SW_TABLET_MODE = 0x01
    """set = tablet mode"""
    SW_HEADPHONE_INSERT = 0x02
    """set = inserted"""
    SW_RFKILL_ALL = 0x03
    """rfkill master switch, type "any"\n\nset = radio enabled"""
    SW_RADIO = SW_RFKILL_ALL
    """deprecated"""
    SW_MICROPHONE_INSERT = 0x04
    """set = inserted"""
    SW_DOCK = 0x05
    """set = plugged into dock"""
    SW_LINEOUT_INSERT = 0x06
    """set = inserted"""
    SW_JACK_PHYSICAL_INSERT = 0x07
    """set = mechanical switch set"""
    SW_VIDEOOUT_INSERT = 0x08
    """set = inserted"""
    SW_CAMERA_LENS_COVER = 0x09
    """set = lens covered"""
    SW_KEYPAD_SLIDE = 0x0A
    """set = keypad slide out"""
    SW_FRONT_PROXIMITY = 0x0B
    """set = front proximity sensor active"""
    SW_ROTATE_LOCK = 0x0C
    """set = rotate locked/disabled"""
    SW_LINEIN_INSERT = 0x0D
    """set = inserted"""
    SW_MUTE_DEVICE = 0x0E
    """set = device disabled"""
    SW_PEN_INSERTED = 0x0F
    """set = pen inserted"""
    SW_MACHINE_COVER = 0x10
    """set = cover closed"""
    SW_MAX = 0x10
    SW_CNT = SW_MAX + 1
    # Misc events
    MSC_SERIAL = 0x00
    MSC_PULSELED = 0x01
    MSC_GESTURE = 0x02
    MSC_RAW = 0x03
    MSC_SCAN = 0x04
    MSC_TIMESTAMP = 0x05
    MSC_MAX = 0x07
    MSC_CNT = MSC_MAX + 1
    # LEDs
    LED_NUML = 0x00
    LED_CAPSL = 0x01
    LED_SCROLLL = 0x02
    LED_COMPOSE = 0x03
    LED_KANA = 0x04
    LED_SLEEP = 0x05
    LED_SUSPEND = 0x06
    LED_MUTE = 0x07
    LED_MISC = 0x08
    LED_MAIL = 0x09
    LED_CHARGING = 0x0A
    LED_MAX = 0x0F
    LED_CNT = LED_MAX + 1
    # Autorepeat values
    REP_DELAY = 0x00
    REP_PERIOD = 0x01
    REP_MAX = 0x01
    REP_CNT = REP_MAX + 1
    # Sounds
    SND_CLICK = 0x00
    SND_BELL = 0x01
    SND_TONE = 0x02
    SND_MAX = 0x07
    SND_CNT = SND_MAX + 1


_EVDEV_TO_USB_HID: dict[int, int] = {
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
    # Mouse buttons
    ecodes.BTN_LEFT: MouseButton.LEFT,
    ecodes.BTN_RIGHT: MouseButton.RIGHT,
    ecodes.BTN_MIDDLE: MouseButton.MIDDLE,
    # Mapping from evdev ecodes to HID UsageIDs from consumer page (0x0C): https://github.com/torvalds/linux/blob/11d3f72613957cba0783938a1ceddffe7dbbf5a1/drivers/hid/hid-input.c#L1069
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
"""evdev scancodes that are mapped to USB HUT (HID Uage Table) UsageIDs from consumer page (0x0C)"""


_MOUSE_BUTTONS = set(
    (
        ecodes.BTN_LEFT,
        ecodes.BTN_RIGHT,
        ecodes.BTN_MIDDLE,
    )
)
"""Mouse button ecodes"""


def evdev_to_usb_hid(event: KeyEvent) -> int | None:
    scancode: int = event.scancode
    hid_usage_id = _EVDEV_TO_USB_HID.get(scancode, None)
    key_name = find_key_name(event)
    hid_usage_name = find_usage_name(event, hid_usage_id)
    if hid_usage_id is None:
        _logger.debug(f"Unsupported key pressed: 0x{scancode:02X}")
    else:
        _logger.debug(
            f"Converted evdev scancode 0x{scancode:02X} ({key_name}) to HID UsageID 0x{hid_usage_id:02X} ({hid_usage_name})"
        )
    return hid_usage_id, hid_usage_name


def find_key_name(event: KeyEvent) -> str | None:
    scancode: int = event.scancode
    for attribute in _cached_dir(ecodes):
        if _cached_getattr(ecodes, attribute) == scancode and attribute.startswith(
            ("KEY_", "BTN_")
        ):
            return attribute
    return None


def find_usage_name(event: KeyEvent, hid_usage_id: int) -> str | None:
    code_type = _get_hid_code_type(event)
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


def _get_hid_code_type(
    event: KeyEvent,
) -> type[ConsumerControlCode] | type[Keycode] | type[MouseButton]:
    if is_consumer_key(event):
        return ConsumerControlCode
    elif is_mouse_button(event):
        return MouseButton
    return Keycode


def is_mouse_button(event: KeyEvent) -> bool:
    return event.scancode in _MOUSE_BUTTONS


def is_consumer_key(event: KeyEvent) -> bool:
    return event.scancode in _CONSUMER_KEYS


def get_mouse_movement(event: RelEvent) -> tuple[int, int, int]:
    input_event: InputEvent = event.event
    x, y, mwheel = 0, 0, 0
    if input_event.code == ecodes.REL_X:
        x = input_event.value
    elif input_event.code == ecodes.REL_Y:
        y = input_event.value
    elif input_event.code == ecodes.REL_WHEEL:
        mwheel = input_event.value
    return x, y, mwheel
