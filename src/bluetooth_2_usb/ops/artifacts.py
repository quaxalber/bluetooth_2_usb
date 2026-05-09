from __future__ import annotations

import os
from pathlib import Path

from .commands import warn


def make_user_copyable(path: Path, *, file_mode: int = 0o644, created_parent: Path | None = None) -> None:
    """Best-effort handoff for artifacts written by sudo commands."""
    uid, gid = _sudo_owner()
    _chmod(path, file_mode)
    if uid is not None and gid is not None:
        _chown(path, uid, gid)

    if created_parent is not None:
        _chmod(created_parent, 0o755)
        if uid is not None and gid is not None:
            _chown(created_parent, uid, gid)


def _sudo_owner() -> tuple[int, int] | tuple[None, None]:
    raw_uid = os.environ.get("SUDO_UID")
    raw_gid = os.environ.get("SUDO_GID")
    if raw_uid is None or raw_gid is None:
        return None, None
    try:
        return int(raw_uid), int(raw_gid)
    except ValueError:
        warn("Ignoring invalid SUDO_UID/SUDO_GID while setting artifact ownership.")
        return None, None


def _chmod(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError as exc:
        warn(f"Could not chmod {path}: {exc}")


def _chown(path: Path, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid)
    except OSError as exc:
        warn(f"Could not chown {path}: {exc}")
