import argparse

from .evdev import ecodes


def _parse_device_ids(raw_value: str) -> list[str]:
    device_ids = [
        device_id.strip() for device_id in raw_value.split(",") if device_id.strip()
    ]
    if not device_ids:
        raise argparse.ArgumentTypeError("DEVICE_IDS must not be empty.")
    return device_ids


def _parse_interrupt_shortcut(raw_value: str) -> list[str]:
    alias_map = {
        "SHIFT": "LEFTSHIFT",
        "LSHIFT": "LEFTSHIFT",
        "RSHIFT": "RIGHTSHIFT",
        "CTRL": "LEFTCTRL",
        "LCTRL": "LEFTCTRL",
        "RCTRL": "RIGHTCTRL",
        "ALT": "LEFTALT",
        "LALT": "LEFTALT",
        "RALT": "RIGHTALT",
        "GUI": "LEFTMETA",
        "LMETA": "LEFTMETA",
        "RMETA": "RIGHTMETA",
    }
    parsed_keys = []
    for raw_key in raw_value.split("+"):
        key = raw_key.strip().upper()
        if not key:
            continue
        normalized = alias_map.get(key, key)
        key_name = normalized if normalized.startswith("KEY_") else f"KEY_{normalized}"
        if not hasattr(ecodes, key_name):
            raise argparse.ArgumentTypeError(f"Unknown shortcut key: {raw_key}")
        parsed_keys.append(key_name)

    if not parsed_keys:
        raise argparse.ArgumentTypeError("Shortcut must contain at least one key.")
    return parsed_keys


class CustomArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(
            *args,
            add_help=False,
            description="Bluetooth-2-USB HID relay. Handles Bluetooth keyboard and mouse events from multiple input devices and translates them to USB using Linux's gadget mode.",
            formatter_class=argparse.RawTextHelpFormatter,
            **kwargs,
        )
        self.register("action", "help", _HelpAction)
        self._add_arguments()

    def _add_arguments(self) -> None:
        self.add_argument(
            "--device_ids",
            "-i",
            type=_parse_device_ids,
            default=None,
            help="Comma-separated list of identifiers for input devices to be relayed.\nAn identifier is either the input device path, the MAC address or any case-insensitive substring of the device name.\nExample: --device_ids '/dev/input/event2,a1:b2:c3:d4:e5:f6,0A-1B-2C-3D-4E-5F,logi'\nDefault: None",
        )
        self.add_argument(
            "--auto_discover",
            "-a",
            action="store_true",
            default=False,
            help="Enable auto-discovery mode. All readable input devices will be relayed automatically.\nDefault: disabled",
        )
        self.add_argument(
            "--grab_devices",
            "-g",
            action="store_true",
            default=False,
            help="Grab the input devices, i.e., suppress any events on your relay device.\nDevices are not grabbed by default.",
        )
        self.add_argument(
            "--interrupt_shortcut",
            "-s",
            type=_parse_interrupt_shortcut,
            default=None,
            help=(
                "A plus-separated list of key names to press simultaneously in order to "
                "toggle relaying (pause/resume). Example: CTRL+SHIFT+Q\n"
                "Default: None (feature disabled)"
            ),
        )
        self.add_argument(
            "--list_devices",
            "-l",
            action="store_true",
            default=False,
            help="List all available input devices and exit.",
        )
        self.add_argument(
            "--log_to_file",
            "-f",
            action="store_true",
            default=False,
            help="Add a handler that logs to file, additionally to stdout.",
        )
        self.add_argument(
            "--log_path",
            "-p",
            type=str,
            default="/var/log/bluetooth_2_usb/bluetooth_2_usb.log",
            help="The path of the log file\nDefault: /var/log/bluetooth_2_usb/bluetooth_2_usb.log",
        )
        self.add_argument(
            "--debug",
            "-d",
            action="store_true",
            default=False,
            help="Enable debug mode (Increases log verbosity)\nDefault: disabled",
        )
        self.add_argument(
            "--version",
            "-v",
            action="store_true",
            default=False,
            help="Display the version number of this software and exit.",
        )
        self.add_argument(
            "--validate-env",
            action="store_true",
            default=False,
            help="Validate the gadget runtime prerequisites and exit.",
        )
        self.add_argument(
            "--output",
            choices=["text", "json"],
            default="text",
            help="Output format for --list_devices and --validate-env. Default: text",
        )
        self.add_argument(
            "--hid-profile",
            choices=["compat", "extended", "boot_keyboard"],
            default="compat",
            help="USB HID profile to expose. Default: compat",
        )
        self.add_argument(
            "--help",
            "-h",
            action="help",
            default=argparse.SUPPRESS,
            help="Show this help message and exit.",
        )


class _HelpAction(argparse._HelpAction):
    def __call__(self, parser, namespace, values, option_string=None) -> None:
        parser.print_help()
        parser.exit()


class Arguments:
    __slots__ = [
        "_device_ids",
        "_auto_discover",
        "_grab_devices",
        "_interrupt_shortcut",
        "_list_devices",
        "_log_to_file",
        "_log_path",
        "_debug",
        "_version",
        "_validate_env",
        "_output",
        "_hid_profile",
    ]

    def __init__(
        self,
        device_ids: list[str] | None,
        auto_discover: bool,
        grab_devices: bool,
        interrupt_shortcut: list[str] | None,
        list_devices: bool,
        log_to_file: bool,
        log_path: str,
        debug: bool,
        version: bool,
        validate_env: bool,
        output: str,
        hid_profile: str,
    ) -> None:
        self._device_ids = device_ids
        self._auto_discover = auto_discover
        self._grab_devices = grab_devices
        self._interrupt_shortcut = interrupt_shortcut
        self._list_devices = list_devices
        self._log_to_file = log_to_file
        self._log_path = log_path
        self._debug = debug
        self._version = version
        self._validate_env = validate_env
        self._output = output
        self._hid_profile = hid_profile

    @property
    def device_ids(self) -> list[str] | None:
        return self._device_ids

    @property
    def auto_discover(self) -> bool:
        return self._auto_discover

    @property
    def grab_devices(self) -> bool:
        return self._grab_devices

    @property
    def interrupt_shortcut(self) -> list[str] | None:
        return self._interrupt_shortcut

    @property
    def list_devices(self) -> bool:
        return self._list_devices

    @property
    def log_to_file(self) -> bool:
        return self._log_to_file

    @property
    def log_path(self) -> str:
        return self._log_path

    @property
    def debug(self) -> bool:
        return self._debug

    @property
    def version(self) -> bool:
        return self._version

    @property
    def validate_env(self) -> bool:
        return self._validate_env

    @property
    def output(self) -> str:
        return self._output

    @property
    def hid_profile(self) -> str:
        return self._hid_profile

    def __str__(self) -> str:
        slot_values = [f"{slot[1:]}={getattr(self, slot)}" for slot in self.__slots__]
        return ", ".join(slot_values)


def parse_args(argv: list[str] | None = None) -> Arguments:
    parser = CustomArgumentParser()
    args = parser.parse_args(argv)

    # Check if no arguments were provided
    if argv is None:
        from sys import argv as sys_argv

        provided_argv = sys_argv[1:]
    else:
        provided_argv = argv

    if len(provided_argv) == 0:
        parser.print_help()
        raise SystemExit(2)

    return Arguments(
        device_ids=args.device_ids,
        auto_discover=args.auto_discover,
        grab_devices=args.grab_devices,
        interrupt_shortcut=args.interrupt_shortcut,
        list_devices=args.list_devices,
        log_to_file=args.log_to_file,
        log_path=args.log_path,
        debug=args.debug,
        version=args.version,
        validate_env=args.validate_env,
        output=args.output,
        hid_profile=args.hid_profile,
    )
