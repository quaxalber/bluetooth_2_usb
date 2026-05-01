from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .version import get_version

if TYPE_CHECKING:
    from .args import Arguments
else:
    Arguments = Any

__version__ = get_version()


def parse_args(*args: Any, **kwargs: Any) -> Arguments:
    """Parse Bluetooth-2-USB runtime CLI arguments.

    :param args: Positional arguments forwarded to :func:`bluetooth_2_usb.args.parse_args`.
    :param kwargs: Keyword arguments forwarded to :func:`bluetooth_2_usb.args.parse_args`.
    :return: Normalized runtime arguments.
    :raises SystemExit: If argument parsing fails or no runtime arguments were supplied.
    """
    from .args import parse_args as _parse_args

    return _parse_args(*args, **kwargs)


def run(*args: Any, **kwargs: Any) -> int:
    """Run the installed Bluetooth-2-USB CLI entrypoint.

    :param args: Positional arguments forwarded to :func:`bluetooth_2_usb.cli.run`.
    :param kwargs: Keyword arguments forwarded to :func:`bluetooth_2_usb.cli.run`.
    :return: Process-style exit code.
    """
    from .cli import run as _run

    return _run(*args, **kwargs)


__all__ = ["Arguments", "parse_args", "run", "__version__"]
