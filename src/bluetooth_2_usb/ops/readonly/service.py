from __future__ import annotations

from ..commands import fail, run
from ..paths import PATHS


def _systemctl_active(unit: str) -> bool:
    """Return whether a systemd unit is currently active.

    :param unit: Systemd unit name to query.
    :return: True when `systemctl is-active --quiet` reports success.
    """
    return run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def _stop_b2u_if_installed(context: str) -> bool:
    """Stop the managed service if it is installed and currently active.

    :param context: Human-readable context appended to failure messages.
    :return: True when the service was active and was stopped.
    :raises OpsError: If systemd service state cannot be queried.
    """
    from ..deployment import service_installed

    state = service_installed()
    if state is None:
        fail(f"Unable to query systemd for {PATHS.service_unit} {context}")
    was_active = state and _systemctl_active(PATHS.service_unit)
    if was_active:
        run(["systemctl", "stop", PATHS.service_unit])
    return bool(was_active)


def _restart_b2u_if_installed(was_active: bool, context: str) -> None:
    """Restart the managed service after a temporary stop when appropriate.

    :param was_active: Whether the service was active before the protected operation.
    :param context: Human-readable context appended to failure messages.
    :return: None.
    :raises OpsError: If systemd state cannot be queried or restart verification fails.
    """
    from ..deployment import service_installed

    state = service_installed()
    if state is None:
        fail(f"Unable to query systemd for {PATHS.service_unit} {context}")
    if was_active and state:
        run(["systemctl", "restart", PATHS.service_unit])
        if not _systemctl_active(PATHS.service_unit):
            fail(f"{PATHS.service_unit} did not come back up {context}")
