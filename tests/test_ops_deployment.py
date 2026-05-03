import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import call, patch

from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.deployment import install, install_cli_links, rebuild_venv, uninstall
from bluetooth_2_usb.ops.paths import ManagedPaths
from bluetooth_2_usb.ops.readonly import ReadonlyConfig

BOOT_CONFIG = "bluetooth_2_usb.ops.deployment.boot_config"


class OpsDeploymentTest(unittest.TestCase):
    def test_managed_paths_derives_paths_from_overrides(self) -> None:
        paths = ManagedPaths(
            persist_mount=Path("/tmp/persist"),
            persist_bluetooth_subdir="bt-state",
            bluetooth_service_dropin_dir=Path("/tmp/dropins"),
        )

        self.assertEqual(paths.default_persist_bluetooth_dir, Path("/tmp/persist/bt-state"))
        self.assertEqual(paths.bluetooth_service_dropin, Path("/tmp/dropins/bluetooth_2_usb_persist.conf"))

    def test_install_cli_links_exposes_main_command(self) -> None:
        with patch("pathlib.Path.mkdir", autospec=True):
            with patch("pathlib.Path.unlink", autospec=True) as unlink:
                with patch("pathlib.Path.symlink_to", autospec=True) as symlink_to:
                    install_cli_links()

        symlink_to.assert_called_once_with(
            Path("/usr/local/bin/bluetooth_2_usb"), Path("/opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb")
        )
        unlinked_paths = {call_args.args[0] for call_args in unlink.call_args_list}
        self.assertEqual(
            unlinked_paths, {Path("/usr/local/bin/bluetooth_2_usb"), Path("/usr/local/bin/bluetooth_2_usb.loopback")}
        )
        self.assertTrue(all(call_args.kwargs == {"missing_ok": True} for call_args in unlink.call_args_list))

    def test_rebuild_venv_recreates_existing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv = root / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "marker").write_text("previous", encoding="utf-8")

            def fake_recreate_venv(target: Path) -> None:
                (target / "bin").mkdir(parents=True)
                (target / "marker").write_text("new", encoding="utf-8")

            with patch("bluetooth_2_usb.ops.deployment.recreate_venv", side_effect=fake_recreate_venv):
                with patch("bluetooth_2_usb.ops.deployment.run") as run:
                    rebuild_venv(venv, root)

            self.assertEqual((venv / "marker").read_text(encoding="utf-8"), "new")
            self.assertEqual(
                run.call_args_list[-1], call([venv / "bin/python", "-m", "bluetooth_2_usb", "--version"], capture=True)
            )

    def test_rebuild_venv_fails_loudly_when_package_install_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv = root / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "marker").write_text("previous", encoding="utf-8")

            def fake_recreate_venv(target: Path) -> None:
                (target / "bin").mkdir(parents=True)
                (target / "marker").write_text("new", encoding="utf-8")

            def fake_run(command, **_kwargs):
                if command[:2] == [venv / "bin/pip", "install"] and command[-1] == root:
                    raise OpsError("package install failed")

            with patch("bluetooth_2_usb.ops.deployment.recreate_venv", side_effect=fake_recreate_venv):
                with patch("bluetooth_2_usb.ops.deployment.run", side_effect=fake_run):
                    with self.assertRaisesRegex(OpsError, "package install failed"):
                        rebuild_venv(venv, root)

            self.assertEqual((venv / "marker").read_text(encoding="utf-8"), "new")

    def test_rebuild_venv_fails_loudly_when_version_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv = root / "venv"

            def fake_recreate_venv(target: Path) -> None:
                (target / "bin").mkdir(parents=True)

            def fake_run(command, **_kwargs):
                if command[:3] == [venv / "bin/python", "-m", "bluetooth_2_usb"]:
                    raise OpsError("version check failed")

            with patch("bluetooth_2_usb.ops.deployment.recreate_venv", side_effect=fake_recreate_venv):
                with patch("bluetooth_2_usb.ops.deployment.run", side_effect=fake_run):
                    with self.assertRaisesRegex(OpsError, "version check failed"):
                        rebuild_venv(venv, root)

    def test_install_stops_active_service_before_rebuild_failure(self) -> None:
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
                stack.enter_context(patch(f"{BOOT_CONFIG}.boot_config_path", return_value=root / "config.txt"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.boot_cmdline_path", return_value=root / "cmdline.txt"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.current_pi_model", return_value="Raspberry Pi 4"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.dwc2_mode", return_value="module"))
                stack.enter_context(
                    patch(f"{BOOT_CONFIG}.board_overlay_line", return_value="dtoverlay=dwc2,dr_mode=peripheral")
                )
                stack.enter_context(patch(f"{BOOT_CONFIG}.required_boot_modules_csv", return_value="dwc2,libcomposite"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.clear_bluetooth_rfkill_soft_blocks"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.normalize_dwc2_overlay"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.normalize_modules_load"))
                stack.enter_context(
                    patch("bluetooth_2_usb.ops.deployment.rebuild_venv", side_effect=OpsError("venv failed"))
                )
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.run", side_effect=fake_run))

                with self.assertRaises(OpsError):
                    install(root)

        self.assertIn(["systemctl", "stop", paths.service_unit], commands)
        self.assertNotIn(["systemctl", "start", paths.service_unit], commands)

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
                stack.enter_context(patch(f"{BOOT_CONFIG}.boot_config_path", return_value=root / "config.txt"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.boot_cmdline_path", return_value=root / "cmdline.txt"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.current_pi_model", return_value="Raspberry Pi 4"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.dwc2_mode", return_value="module"))
                stack.enter_context(
                    patch(f"{BOOT_CONFIG}.board_overlay_line", return_value="dtoverlay=dwc2,dr_mode=peripheral")
                )
                stack.enter_context(patch(f"{BOOT_CONFIG}.required_boot_modules_csv", return_value="dwc2,libcomposite"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.clear_bluetooth_rfkill_soft_blocks"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.normalize_dwc2_overlay"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.normalize_modules_load"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.rebuild_venv", return_value=None))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.install_service_unit"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.install_cli_links"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.activate_service_unit"))
                stack.enter_context(
                    patch(
                        "bluetooth_2_usb.ops.deployment.canonicalize_service_settings_bools",
                        side_effect=lambda path: canonicalized_paths.append(path) or True,
                    )
                )
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.run", side_effect=fake_run))

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
                bluetooth_service_dropin_dir=root,
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
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.load_readonly_config", return_value=config))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.service_installed", return_value=False))
                remove_owned_gadgets = stack.enter_context(patch("bluetooth_2_usb.ops.deployment.remove_owned_gadgets"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.remove_bluetooth_persist_dropin"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.remove_bluetooth_bind_mount_unit"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.remove_persist_mount_unit"))
                stack.enter_context(patch("bluetooth_2_usb.ops.deployment.run", side_effect=fake_run))

                uninstall()

        remove_owned_gadgets.assert_called_once_with()
        self.assertNotIn(["systemctl", "stop", paths.service_unit], commands)
        self.assertNotIn(["systemctl", "disable", paths.service_unit], commands)
        self.assertIn(["systemctl", "daemon-reload"], commands)
