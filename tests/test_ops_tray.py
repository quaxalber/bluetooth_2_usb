import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops import cli
from bluetooth_2_usb.ops.commands import OpsError, close_log
from bluetooth_2_usb.ops.paths import ManagedPaths
from bluetooth_2_usb.ops.tray import (
    TRAY_APT_PACKAGES,
    install_tray,
    refresh_tray_autostart,
    tray_installed,
    uninstall_tray,
)

OPS_TRAY = "bluetooth_2_usb.ops.tray"
OPS_CLI = "bluetooth_2_usb.ops.cli"
REPO_ROOT = Path(__file__).resolve().parents[1]


class OpsTrayTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.install_dir = root / "opt"
        (self.install_dir / "desktop").mkdir(parents=True)
        (self.install_dir / "desktop/bluetooth_2_usb_tray.py").write_text("# tray\n", encoding="utf-8")
        (self.install_dir / "desktop/bluetooth_2_usb-tray.desktop").write_text("[Desktop Entry]\n", encoding="utf-8")
        self.paths = ManagedPaths(install_dir=self.install_dir, tray_autostart=root / "xdg/autostart/b2u.desktop")
        paths_patch = patch(f"{OPS_TRAY}.PATHS", self.paths)
        paths_patch.start()
        self.addCleanup(paths_patch.stop)

    def test_install_installs_packages_and_world_readable_autostart(self) -> None:
        with patch(f"{OPS_TRAY}.run") as run:
            install_tray()

        run.assert_called_once_with(["apt-get", "install", "-y", "--no-install-recommends", *TRAY_APT_PACKAGES])
        self.assertEqual(self.paths.tray_autostart.read_text(encoding="utf-8"), "[Desktop Entry]\n")
        self.assertEqual(self.paths.tray_autostart.stat().st_mode & 0o777, 0o644)
        self.assertTrue(tray_installed())

    def test_install_fails_when_checkout_lacks_tray_files(self) -> None:
        (self.install_dir / "desktop/bluetooth_2_usb_tray.py").unlink()

        with patch(f"{OPS_TRAY}.run") as run, self.assertRaises(OpsError):
            install_tray()

        run.assert_not_called()
        self.assertFalse(tray_installed())

    def test_refresh_is_noop_when_not_installed(self) -> None:
        refresh_tray_autostart()

        self.assertFalse(tray_installed())

    def test_refresh_updates_existing_autostart_entry(self) -> None:
        self.paths.tray_autostart.parent.mkdir(parents=True)
        self.paths.tray_autostart.write_text("stale\n", encoding="utf-8")

        refresh_tray_autostart()

        self.assertEqual(self.paths.tray_autostart.read_text(encoding="utf-8"), "[Desktop Entry]\n")

    def test_uninstall_removes_autostart_entry_and_tolerates_absence(self) -> None:
        with patch(f"{OPS_TRAY}.run"):
            install_tray()

        uninstall_tray()
        uninstall_tray()

        self.assertFalse(tray_installed())


class OpsTrayCliTest(unittest.TestCase):
    def tearDown(self) -> None:
        close_log()

    def test_tray_commands_require_root_and_dispatch(self) -> None:
        for subcommand, target in (("install", "install_tray"), ("uninstall", "uninstall_tray")):
            with self.subTest(subcommand=subcommand):
                with (
                    patch(f"{OPS_CLI}.ensure_root") as ensure_root,
                    patch(f"{OPS_CLI}.prepare_log"),
                    patch(f"{OPS_CLI}.{target}") as command,
                ):
                    self.assertEqual(cli.main(["tray", subcommand]), 0)

                ensure_root.assert_called_once()
                command.assert_called_once_with()

    def test_tray_is_routed_as_operational_command(self) -> None:
        self.assertIn("tray", cli.OPERATIONAL_COMMANDS)


class TrayDesktopEntryTest(unittest.TestCase):
    def test_desktop_entry_launches_managed_tray_script_with_system_python(self) -> None:
        entry = (REPO_ROOT / "desktop/bluetooth_2_usb-tray.desktop").read_text(encoding="utf-8")
        paths = ManagedPaths()

        self.assertIn(f"Exec=/usr/bin/python3 {paths.tray_script}\n", entry)
        self.assertTrue((REPO_ROOT / "desktop/bluetooth_2_usb_tray.py").is_file())


if __name__ == "__main__":
    unittest.main()
