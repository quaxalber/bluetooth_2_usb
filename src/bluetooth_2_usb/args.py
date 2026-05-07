import argparse
from dataclasses import dataclass, fields

from .inputs.filter import parse_devices


def _parse_devices(raw_value: str) -> list[str]:
    try:
        return parse_devices(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("DEVICES must not be empty.") from exc


def _parse_shortcut(raw_value: str) -> list[str]:
    from .evdev import ecodes

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
            description=(
                "Bluetooth-2-USB HID relay. Handles Bluetooth keyboard and mouse events from multiple "
                + "input devices and translates them to USB using Linux's gadget mode."
            ),
            formatter_class=argparse.RawTextHelpFormatter,
            **kwargs,
        )
        self.register("action", "help", _HelpAction)
        self._add_arguments()

    def _add_arguments(self) -> None:
        self.add_argument(
            "--auto",
            "-a",
            action="store_true",
            default=False,
            help=(
                "Enable auto relay. All readable input devices will be relayed automatically "
                + "except known excluded platform devices.\n"
                + "Default: disabled"
            ),
        )
        self.add_argument(
            "--devices",
            type=_parse_devices,
            default=None,
            help=(
                "Comma-separated list of devices to be relayed.\n"
                + "Each value may match an input device path, uniq, phys, Bluetooth MAC address, "
                + "or case-insensitive substring of the device name.\n"
                + "Example: --devices '/dev/input/event2,a1:b2:c3:d4:e5:f6,0A-1B-2C-3D-4E-5F,logi'\n"
                + "Default: None"
            ),
        )
        self.add_argument(
            "--grab",
            "-g",
            action="store_true",
            default=False,
            help=(
                "Grab the input devices, suppressing local events on the Pi while the devices are relayed.\n"
                + "Devices are not grabbed by default."
            ),
        )
        self.add_argument(
            "--shortcut",
            "-s",
            type=_parse_shortcut,
            default=None,
            help=(
                "A plus-separated list of key names to press simultaneously in order to "
                + "toggle relaying (pause/resume). Example: CTRL+SHIFT+Q\n"
                + "Default: None (feature disabled)"
            ),
        )
        self.add_argument(
            "--list", "-l", action="store_true", default=False, help="List all available input devices and exit."
        )
        self.add_argument(
            "--debug",
            "-d",
            action="store_true",
            default=False,
            help="Enable debug mode and increase log verbosity.\nDefault: disabled",
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
            help="Output format for --list and --validate-env. Default: text",
        )
        self.add_argument(
            "--help", "-h", action="help", default=argparse.SUPPRESS, help="Show this help message and exit."
        )


class _HelpAction(argparse._HelpAction):
    def __call__(self, parser, namespace, values, option_string=None) -> None:
        parser.print_help()
        parser.exit()


@dataclass(frozen=True, slots=True)
class Arguments:
    devices: list[str] | None
    auto: bool
    grab: bool
    shortcut: list[str] | None
    list: bool
    debug: bool
    version: bool
    validate_env: bool
    output: str

    def __str__(self) -> str:
        return ", ".join(f"{field.name}={getattr(self, field.name)}" for field in fields(self))


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
        devices=args.devices,
        auto=args.auto,
        grab=args.grab,
        shortcut=args.shortcut,
        list=args.list,
        debug=args.debug,
        version=args.version,
        validate_env=args.validate_env,
        output=args.output,
    )
