from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .commands import OpsError, ensure_root, fail, prepare_log
from .diagnostics import SmokeTest, debug_report
from .hid_udev_rule import install_hid_udev_rule
from .loopback import loopback_capture, loopback_inject
from .paths import PATHS
from .readonly import (
    disable_readonly,
    enable_readonly,
    setup_persistent_bluetooth_state,
)
from .service_install import install, uninstall, update


def run() -> None:
    raise SystemExit(main())


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        return _main(args)
    except OpsError as exc:
        print(f"[x] {exc}", file=sys.stderr)
        return exc.exit_code


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m bluetooth_2_usb.ops")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _command_parser(subparsers, "install", "Apply the managed system install.")
    _command_parser(
        subparsers,
        "update",
        "Fast-forward and reapply the managed install when changed.",
    )
    _command_parser(subparsers, "uninstall", "Remove the managed system integration.")
    smoketest_parser = _command_parser(subparsers, "smoketest", "Run deployment health checks.")
    smoketest_parser.add_argument("--verbose", action="store_true")
    smoketest_parser.add_argument("--allow-non-pi", action="store_true")
    debug_parser = _command_parser(subparsers, "debug", "Collect a redacted diagnostics report.")
    debug_parser.add_argument("--duration", type=_positive_int)
    setup_parser = _command_parser(
        subparsers, "readonly-setup", "Prepare persistent Bluetooth state."
    )
    setup_parser.add_argument("--device", required=True)
    _command_parser(subparsers, "readonly-enable", "Enable persistent read-only mode.")
    _command_parser(subparsers, "readonly-disable", "Disable OverlayFS.")
    _command_parser(subparsers, "install-hid-udev-rule", "Install the host-side hidapi udev rule.")
    _passthrough_parser(subparsers, "loopback-inject", "Run the Pi-side loopback injector.")
    _passthrough_parser(subparsers, "loopback-capture", "Run the host-side loopback capture.")

    namespace, remainder = parser.parse_known_args(argv)
    repo_root = Path(namespace.repo_root).resolve() if namespace.repo_root else PATHS.install_dir
    if namespace.command == "loopback-capture" and namespace.repo_root is None:
        repo_root = Path.cwd()

    if namespace.command == "loopback-inject":
        return loopback_inject(remainder)
    if namespace.command == "loopback-capture":
        return loopback_capture(repo_root, remainder)

    if namespace.command not in {"install-hid-udev-rule"}:
        ensure_root()

    if namespace.command in {
        "install",
        "update",
        "uninstall",
        "smoketest",
        "debug",
        "readonly-setup",
        "readonly-enable",
        "readonly-disable",
    }:
        prepare_log(namespace.command.replace("-", "_"))

    if namespace.command == "install":
        install(repo_root)
    elif namespace.command == "update":
        update(repo_root)
    elif namespace.command == "uninstall":
        uninstall()
    elif namespace.command == "smoketest":
        return SmokeTest(verbose=namespace.verbose, allow_non_pi=namespace.allow_non_pi).run()
    elif namespace.command == "debug":
        return debug_report(namespace.duration)
    elif namespace.command == "readonly-setup":
        setup_persistent_bluetooth_state(namespace.device)
    elif namespace.command == "readonly-enable":
        enable_readonly()
    elif namespace.command == "readonly-disable":
        disable_readonly()
    elif namespace.command == "install-hid-udev-rule":
        ensure_root()
        install_hid_udev_rule(repo_root)
    else:
        fail(f"Unhandled ops command: {namespace.command}")
    return 0


def _command_parser(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
    *,
    add_help: bool = True,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text, add_help=add_help)
    parser.add_argument("--repo-root", default=None, help=argparse.SUPPRESS)
    return parser


def _passthrough_parser(
    subparsers: argparse._SubParsersAction, name: str, help_text: str
) -> argparse.ArgumentParser:
    return _command_parser(subparsers, name, help_text, add_help=False)


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value
