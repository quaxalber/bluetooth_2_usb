import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bluetooth_2_usb.relay.gate import RelayGate
from bluetooth_2_usb.relay.jiggler import MouseJiggler
from bluetooth_2_usb.runtime.status import STATUS_FILE_NAME, StatusPublisher


class StatusPublisherTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / STATUS_FILE_NAME
        self.gate = RelayGate()
        self.jiggler = MouseJiggler(hid_gadgets=Mock(), relay_gate=self.gate)

    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_start_publishes_initial_state(self) -> None:
        publisher = StatusPublisher(self.path, self.gate, self.jiggler)

        publisher.start()

        status = self._read()
        self.assertEqual(status["version"], 1)
        self.assertEqual(status["pid"], os.getpid())
        self.assertEqual(status["jiggler"], {"available": True, "enabled": True})
        self.assertEqual(
            status["relay"], {"active": False, "host_configured": False, "user_enabled": True, "write_suspended": False}
        )

    def test_status_file_is_world_readable(self) -> None:
        StatusPublisher(self.path, self.gate, self.jiggler).start()

        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)

    def test_jiggler_toggle_updates_status(self) -> None:
        StatusPublisher(self.path, self.gate, self.jiggler).start()

        self.jiggler.toggle()

        self.assertEqual(self._read()["jiggler"]["enabled"], False)

    def test_gate_change_without_active_flip_updates_status(self) -> None:
        StatusPublisher(self.path, self.gate, self.jiggler).start()

        # Relay stays inactive (no host), but the reason changes to user-paused too.
        self.gate.set_user_enabled(False)

        relay = self._read()["relay"]
        self.assertFalse(relay["active"])
        self.assertFalse(relay["user_enabled"])

    def test_gate_activation_updates_status(self) -> None:
        StatusPublisher(self.path, self.gate, self.jiggler).start()

        self.gate.set_host_configured(True)

        self.assertTrue(self._read()["relay"]["active"])

    def test_without_jiggler_reports_unavailable(self) -> None:
        StatusPublisher(self.path, self.gate, None).start()

        self.assertEqual(self._read()["jiggler"], {"available": False, "enabled": False})

    def test_stop_removes_file_and_listeners(self) -> None:
        publisher = StatusPublisher(self.path, self.gate, self.jiggler)
        publisher.start()

        publisher.stop()
        self.jiggler.toggle()
        self.gate.set_host_configured(True)

        self.assertFalse(self.path.exists())

    def test_write_failure_is_logged_not_raised(self) -> None:
        missing_dir_path = Path(self._tmp.name) / "missing" / STATUS_FILE_NAME
        publisher = StatusPublisher(missing_dir_path, self.gate, self.jiggler)

        with self.assertLogs("bluetooth_2_usb.runtime.status", level="WARNING"):
            publisher.start()
        self.jiggler.toggle()

        self.assertFalse(missing_dir_path.exists())

    def test_no_temp_files_left_behind(self) -> None:
        StatusPublisher(self.path, self.gate, self.jiggler).start()
        self.jiggler.toggle()

        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [STATUS_FILE_NAME])


class StatusPublisherFromEnvironmentTest(unittest.TestCase):
    def test_returns_none_outside_systemd_runtime_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(StatusPublisher.from_environment(RelayGate(), None))

    def test_uses_first_runtime_directory(self) -> None:
        with patch.dict(os.environ, {"RUNTIME_DIRECTORY": "/run/bluetooth_2_usb:/run/other"}):
            publisher = StatusPublisher.from_environment(RelayGate(), None)

        self.assertIsNotNone(publisher)
        self.assertEqual(publisher.path, Path("/run/bluetooth_2_usb") / STATUS_FILE_NAME)


class RelayGateStateListenerTest(unittest.TestCase):
    def test_state_listener_fires_on_every_change_with_snapshot(self) -> None:
        gate = RelayGate()
        states = []
        gate.add_state_listener(states.append)

        gate.set_user_enabled(False)  # inactive -> inactive
        gate.set_user_enabled(False)  # no change
        gate.set_host_configured(True)  # still inactive (paused)

        self.assertEqual([(s.user_enabled, s.host_configured) for s in states], [(False, False), (False, True)])

    def test_removed_state_listener_is_not_called(self) -> None:
        gate = RelayGate()
        listener = Mock()
        gate.add_state_listener(listener)
        gate.remove_state_listener(listener)

        gate.set_host_configured(True)

        listener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
