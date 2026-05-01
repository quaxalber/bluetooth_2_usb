import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, call, patch

from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.deployment import RollbackStack, install, install_cli_links, uninstall
from bluetooth_2_usb.ops.paths import ManagedPaths
from bluetooth_2_usb.ops.readonly import ReadonlyConfig

BOOT_CONFIG = "bluetooth_2_usb.ops.deployment.boot_config"


class OpsDeploymentTest(unittest.TestCase):
    def test_rollback_stack_runs_callbacks_in_reverse_order(self) -> None:
        calls = []
        rollback = RollbackStack()

        rollback.push("first", lambda: calls.append("first"))
        rollback.push("second", lambda: calls.append("second"))
        rollback.rollback()

        self.assertEqual(calls, ["second", "first"])

    def test_rollback_stack_commit_discards_callbacks(self) -> None:
        callback = Mock()
        rollback = RollbackStack()

        rollback.push("unused", callback)
        rollback.commit()
        rollback.rollback()

        callback.assert_not_called()

    def test_install_cli_links_exposes_main_command(self) -> None:
        with patch("pathlib.Path.mkdir"):
            with patch("pathlib.Path.unlink") as unlink:
                with patch("pathlib.Path.symlink_to") as symlink_to:
                    install_cli_links()

        linked_commands = [call.args[0].name for call in symlink_to.call_args_list]
        self.assertEqual(linked_commands, ["bluetooth_2_usb"])
        self.assertEqual(unlink.call_args_list, [call(missing_ok=True), call(missing_ok=True)])

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

    def test_install_canonicalizes_managed_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            paths = ManagedPaths(install_dir=root, env_file=root / "managed-env")
            canonicalized_paths = []

            def fake_run(command, *, check=True, capture=False):
                class Completed:
                    returncode = 3 if command[-1:] == ["--validate-env"] else 0
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
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.rebuild_venv_atomically"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.install_service_unit"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.install_cli_links"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.activate_service_unit"))
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.deployment.canonicalize_service_settings_bools",
                        side_effect=lambda path: canonicalized_paths.append(path) or True,
                    )
                )
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.deployment.run", side_effect=fake_run)
                )

                install(root)

        self.assertEqual(canonicalized_paths, [paths.env_file])

    def test_uninstall_cleans_owned_gadgets_without_managing_missing_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ManagedPaths(
                install_dir=root,
                env_file=root / "env",
                readonly_env_file=root / "readonly-env",
                bluetooth_bind_mount_unit=root / "var-lib-bluetooth.mount",
                bluetooth_service_dropin=root / "bluetooth_2_usb_persist.conf",
            )
            config = ReadonlyConfig(
                mode="disabled",
                persist_mount=root / "persist",
                persist_bluetooth_dir=root / "persist" / "bluetooth",
                persist_spec="",
                persist_device="",
            )
            commands = []

            def fake_run(command, *, check=True, capture=False):
                commands.append(command)

                class Completed:
                    returncode = 0
                    stdout = ""

                if command[:4] == ["systemctl", "show", "-P", "LoadState"]:
                    Completed.stdout = "not-found\n"
                elif command[:2] == ["findmnt", "-rn"]:
                    Completed.returncode = 1
                elif command[:2] == ["systemctl", "is-enabled"]:
                    Completed.returncode = 1
                elif command[:3] == ["systemctl", "is-active", "--quiet"]:
                    Completed.returncode = 1
                return Completed()

            with ExitStack() as stack:
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.PATHS", paths))
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.deployment.load_readonly_config", return_value=config
                    )
                )
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.deployment.service_installed", return_value=False)
                )
                remove_owned_gadgets = stack.enter_context(
                    patch("bluetooth_2_usb.ops.deployment.remove_owned_gadgets")
                )
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.deployment.remove_bluetooth_persist_dropin")
                )
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.deployment.remove_bluetooth_bind_mount_unit")
                )
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.deployment.remove_persist_mount_unit")
                )
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.deployment.run", side_effect=fake_run)
                )

                uninstall()

        remove_owned_gadgets.assert_called_once_with()
        self.assertNotIn(["systemctl", "stop", paths.service_unit], commands)
        self.assertNotIn(["systemctl", "disable", paths.service_unit], commands)
        self.assertIn(["systemctl", "daemon-reload"], commands)
