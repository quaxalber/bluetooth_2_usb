import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.deployment import install
from bluetooth_2_usb.ops.paths import ManagedPaths

BOOT_CONFIG = "bluetooth_2_usb.ops.deployment.boot_config"


class OpsDeploymentTest(unittest.TestCase):
    def test_install_restores_active_service_when_rebuild_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            paths = ManagedPaths(install_dir=root)
            commands = []

            def fake_run(command, *, check=True, capture=False):
                commands.append(command)

                class Completed:
                    returncode = 0 if command[:3] == ["systemctl", "is-active", "--quiet"] else 0
                    stdout = ""

                return Completed()

            with ExitStack() as stack:
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.PATHS", paths))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.require_commands"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.detect_boot_dir", return_value=root))
                stack.enter_context(
                    patch(f"{BOOT_CONFIG}.boot_config_path", return_value=root / "config.txt")
                )
                stack.enter_context(
                    patch(f"{BOOT_CONFIG}.boot_cmdline_path", return_value=root / "cmdline.txt")
                )
                stack.enter_context(
                    patch(f"{BOOT_CONFIG}.current_pi_model", return_value="Raspberry Pi 4")
                )
                stack.enter_context(patch(f"{BOOT_CONFIG}.dwc2_mode", return_value="module"))
                stack.enter_context(
                    patch(
                        f"{BOOT_CONFIG}.board_overlay_line",
                        return_value="dtoverlay=dwc2,dr_mode=peripheral",
                    )
                )
                stack.enter_context(
                    patch(
                        f"{BOOT_CONFIG}.required_boot_modules_csv", return_value="dwc2,libcomposite"
                    )
                )
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.deployment.clear_bluetooth_rfkill_soft_blocks")
                )
                stack.enter_context(patch(f"{BOOT_CONFIG}.normalize_dwc2_overlay"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.normalize_modules_load"))
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.deployment.rebuild_venv_atomically",
                        side_effect=OpsError("venv failed"),
                    )
                )
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.deployment.run", side_effect=fake_run)
                )

                with self.assertRaises(OpsError):
                    install(root)

        self.assertIn(["systemctl", "stop", paths.service_unit], commands)
        self.assertIn(["systemctl", "start", paths.service_unit], commands)
