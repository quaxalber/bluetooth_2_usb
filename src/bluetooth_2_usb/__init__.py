from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .version import get_version

if TYPE_CHECKING:
    from .args import Arguments
else:
    Arguments = Any

__version__ = get_version()


def parse_args(*args: Any, **kwargs: Any) -> Arguments:
    """Parse command-line arguments into an immutable argument object.

    :return: The requested value or status result.
    """
    from .args import parse_args as _parse_args

    return _parse_args(*args, **kwargs)


def run(*args: Any, **kwargs: Any) -> int:
    """Run the command entrypoint and return a process-style exit code.

    :return: The requested value or status result.
    """
    from .cli import run as _run

    return _run(*args, **kwargs)


__all__ = ["Arguments", "parse_args", "run", "__version__"]
