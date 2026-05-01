from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

PACKAGE_NAME = "bluetooth_2_usb"
UNKNOWN_VERSION = "unknown"

try:
    from ._version import version as SCM_VERSION
except ImportError:
    SCM_VERSION = None


def get_version() -> str:
    """Return the installed package version string.

    :return: The requested value or status result.
    """
    try:
        return package_version(PACKAGE_NAME)
    except PackageNotFoundError:
        if SCM_VERSION:
            return SCM_VERSION
        return UNKNOWN_VERSION


def get_versioned_name() -> str:
    """Return the user-facing package name and version string.

    :return: The requested value or status result.
    """
    version = get_version()
    if version == UNKNOWN_VERSION:
        return "Bluetooth-2-USB"
    return f"Bluetooth-2-USB v{version}"
