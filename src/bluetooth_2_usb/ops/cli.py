from __future__ import annotations

import argparse
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

from .commands import OpsError, close_log, ensure_root, fail, prepare_log
from .deployment import install, uninstall, update
from .diagnostics import SmokeTest, debug_report
from .hid_udev_rule import install_hid_udev_rule
from .paths import PATHS
from .readonly import (
    disable_readonly,
    enable_readonly,
    print_readonly_status,
    setup_persistent_bluetooth_state,
)

OPERATIONAL_COMMANDS = frozenset(
    {
        "install",
        "update",
        "uninstall",
        "smoketest",
        "debug",
        "readonly",
        "udev",
    }
)


def run() -> None:
    raise SystemExit(main())


def main(argv: list[str] | None = None, *, prog: str = "bluetooth_2_usb") -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        return _main(args, prog=prog)
    except OpsError as exc:
        print(f"[x] {exc}", file=sys.stderr)
        return exc.exit_code
    finally:
        close_log()


def _main(argv: list[str], *, prog: str) -> int:
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command", required=True)

    _command_parser(subparsers, "install", "Apply the managed system install.")
    _command_parser(
        subparsers, "update", "Fast-forward and reapply the managed install when changed."
    )
    _command_parser(subparsers, "uninstall", "Remove the managed system integration.")
    smoketest_parser = _command_parser(subparsers, "smoketest", "Run deployment health checks.")
    smoketest_parser.add_argument("--verbose", action="store_true")
    smoketest_parser.add_argument("--allow-non-pi", action="store_true")
    smoketest_parser.add_argument(
        "--output", choices=["text", "json"], default="text", help="Default: text"
    )
    debug_parser = _command_parser(subparsers, "debug", "Collect a redacted diagnostics report.")
    debug_parser.add_argument("--duration", type=_positive_int)
    readonly_parser = _command_parser(
        subparsers, "readonly", "Manage persistent read-only operation."
    )
    readonly_subparsers = readonly_parser.add_subparsers(dest="readonly_command", required=True)
    setup_parser = _command_parser(
        readonly_subparsers, "setup", "Prepare persistent Bluetooth state."
    )
    setup_parser.add_argument("--device", required=True)
    _command_parser(readonly_subparsers, "status", "Show persistent read-only status.")
    _command_parser(readonly_subparsers, "enable", "Enable persistent read-only mode.")
    _command_parser(readonly_subparsers, "disable", "Disable OverlayFS.")

    udev_parser = _command_parser(subparsers, "udev", "Manage host-side hidapi udev rules.")
    udev_subparsers = udev_parser.add_subparsers(dest="udev_command", required=True)
    _command_parser(udev_subparsers, "install", "Install the host-side hidapi udev rule.")

    namespace, remainder = parser.parse_known_args(argv)
    if remainder:
        parser.error(f"unrecognized arguments: {' '.join(remainder)}")
    repo_root = Path(namespace.repo_root).resolve() if namespace.repo_root else PATHS.install_dir

    command_path = _command_path(namespace)

    if command_path not in {("udev", "install"), ("readonly", "status")}:
        ensure_root()

    log_name = "_".join(command_path)
    if command_path in {
        ("install",),
        ("update",),
        ("uninstall",),
        ("smoketest",),
        ("debug",),
        ("readonly", "setup"),
        ("readonly", "enable"),
        ("readonly", "disable"),
    }:
        prepare_log(log_name)

    if command_path == ("install",):
        install(repo_root)
    elif command_path == ("update",):
        update(repo_root)
    elif command_path == ("uninstall",):
        uninstall()
    elif command_path == ("smoketest",):
        smoke_test = SmokeTest(verbose=namespace.verbose, allow_non_pi=namespace.allow_non_pi)
        if namespace.output == "json":
            with redirect_stdout(sys.stderr):
                exit_code = smoke_test.run()
            print(json.dumps(smoke_test.result_dict(), sort_keys=True))
        else:
            exit_code = smoke_test.run()
        return exit_code
    elif command_path == ("debug",):
        return debug_report(namespace.duration)
    elif command_path == ("readonly", "setup"):
        setup_persistent_bluetooth_state(namespace.device)
    elif command_path == ("readonly", "status"):
        print_readonly_status()
    elif command_path == ("readonly", "enable"):
        enable_readonly()
    elif command_path == ("readonly", "disable"):
        disable_readonly()
    elif command_path == ("udev", "install"):
        ensure_root()
        install_hid_udev_rule(repo_root)
    else:
        fail(f"Unhandled operational command: {' '.join(command_path)}")
    return 0


def _command_path(namespace: argparse.Namespace) -> tuple[str, ...]:
    if namespace.command == "readonly":
        return (namespace.command, namespace.readonly_command)
    if namespace.command == "udev":
        return (namespace.command, namespace.udev_command)
    return (namespace.command,)


def _command_parser(
    subparsers: argparse._SubParsersAction, name: str, help_text: str, *, add_help: bool = True
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text, add_help=add_help)
    parser.add_argument("--repo-root", default=None, help=argparse.SUPPRESS)
    return parser


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value
