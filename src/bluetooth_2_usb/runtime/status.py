from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..logging import get_logger

if TYPE_CHECKING:
    from ..relay.gate import RelayGate, RelayGateState
    from ..relay.jiggler import MouseJiggler

logger = get_logger(__name__)

STATUS_FILE_NAME = "status.json"
STATUS_FORMAT_VERSION = 1


class StatusPublisher:
    """
    Publishes relay and jiggler state as a small world-readable JSON file so
    unprivileged desktop tools (e.g. the tray indicator) can display it.

    The file is replaced atomically on every state change and removed on
    shutdown. Write failures are logged and never affect relaying.
    """

    def __init__(self, path: Path, relay_gate: RelayGate, mouse_jiggler: MouseJiggler | None) -> None:
        self._path = path
        self._relay_gate = relay_gate
        self._mouse_jiggler = mouse_jiggler
        self._started = False

    @classmethod
    def from_environment(cls, relay_gate: RelayGate, mouse_jiggler: MouseJiggler | None) -> StatusPublisher | None:
        """
        Build a publisher writing into systemd's ``RuntimeDirectory=``.

        Returns None outside the managed service (``$RUNTIME_DIRECTORY`` unset),
        so ad-hoc CLI runs and tests never touch ``/run``.
        """
        runtime_directory = os.environ.get("RUNTIME_DIRECTORY", "").split(":")[0]
        if not runtime_directory:
            return None
        return cls(Path(runtime_directory) / STATUS_FILE_NAME, relay_gate, mouse_jiggler)

    @property
    def path(self) -> Path:
        return self._path

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._relay_gate.add_state_listener(self._handle_gate_state)
        if self._mouse_jiggler is not None:
            self._mouse_jiggler.add_listener(self._handle_jiggler_toggled)
        self.publish()

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._relay_gate.remove_state_listener(self._handle_gate_state)
        if self._mouse_jiggler is not None:
            self._mouse_jiggler.remove_listener(self._handle_jiggler_toggled)
        try:
            self._path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Could not remove status file %s: %s", self._path, exc)

    def publish(self) -> None:
        try:
            self._write(self._snapshot())
        except OSError as exc:
            logger.warning("Could not write status file %s: %s", self._path, exc)

    def _handle_gate_state(self, state: RelayGateState) -> None:
        del state
        self.publish()

    def _handle_jiggler_toggled(self, enabled: bool) -> None:
        del enabled
        self.publish()

    def _snapshot(self) -> dict[str, object]:
        state = self._relay_gate.state
        return {
            "version": STATUS_FORMAT_VERSION,
            "pid": os.getpid(),
            "updated": time.time(),
            "relay": {
                "active": state.active,
                "host_configured": state.host_configured,
                "user_enabled": state.user_enabled,
                "write_suspended": state.write_suspended,
            },
            "jiggler": {
                "available": self._mouse_jiggler is not None,
                "enabled": self._mouse_jiggler is not None and self._mouse_jiggler.enabled,
            },
        }

    def _write(self, snapshot: dict[str, object]) -> None:
        directory = self._path.parent
        fd, tmp_name = tempfile.mkstemp(prefix=".status-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle)
            os.chmod(tmp_name, 0o644)
            os.replace(tmp_name, self._path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
