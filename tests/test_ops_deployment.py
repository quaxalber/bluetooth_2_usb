import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import call, patch

from bluetooth_2_usb.ops.commands import OpsError
from bluetooth_2_usb.ops.deployment import install, install_cli_links, rebuild_venv, uninstall, update
from bluetooth_2_usb.ops.paths import ManagedPaths
from bluetooth_2_usb.ops.readonly import ReadonlyConfig

BOOT_CONFIG = "bluetooth_2_usb.ops.deployment.boot_config"
OPS_DEPLOYMENT = "bluetooth_2_usb.ops.deployment"
PATHLIB_PATH = "pathlib.Path"


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
        with (
            patch(f"{PATHLIB_PATH}.mkdir", autospec=True),
            patch(f"{PATHLIB_PATH}.unlink", autospec=True) as unlink,
            patch(f"{PATHLIB_PATH}.symlink_to", autospec=True) as symlink_to,
        ):
            install_cli_links()

        symlink_to.assert_called_once_with(
            Path("/usr/local/bin/bluetooth_2_usb"), Path("/opt/bluetooth_2_usb/venv/bin/bluetooth_2_usb")
        )
        unlink.assert_any_call(Path("/usr/local/bin/bluetooth_2_usb"), missing_ok=True)

    def test_rebuild_venv_reuses_existing_valid_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv = root / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python").touch()
            (venv / "bin/pip").touch()
            (venv / "marker").write_text("previous", encoding="utf-8")

            with patch(f"{OPS_DEPLOYMENT}.recreate_venv") as recreate, patch(f"{OPS_DEPLOYMENT}.run") as run:
                rebuild_venv(venv, root)

            recreate.assert_not_called()
            self.assertEqual((venv / "marker").read_text(encoding="utf-8"), "previous")
            self.assertEqual(
                run.call_args_list[0], call([venv / "bin/pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
            )
            self.assertEqual(run.call_args_list[1], call([venv / "bin/pip", "install", "--upgrade", root]))
            self.assertEqual(
                run.call_args_list[-1], call([venv / "bin/python", "-m", "bluetooth_2_usb", "--version"], capture=True)
            )

    def test_rebuild_venv_creates_missing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv = root / "venv"

            def fake_recreate_venv(target: Path) -> None:
                (target / "bin").mkdir(parents=True)
                (target / "bin/python").touch()
                (target / "bin/pip").touch()

            with (
                patch(f"{OPS_DEPLOYMENT}.recreate_venv", side_effect=fake_recreate_venv) as recreate,
                patch(f"{OPS_DEPLOYMENT}.run"),
            ):
                rebuild_venv(venv, root)

            recreate.assert_called_once_with(venv)
            self.assertTrue((venv / "bin/python").is_file())
            self.assertTrue((venv / "bin/pip").is_file())

    def test_rebuild_venv_recreates_invalid_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv = root / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python").touch()

            def fake_recreate_venv(target: Path) -> None:
                (target / "bin").mkdir(parents=True, exist_ok=True)
                (target / "bin/python").touch()
                (target / "bin/pip").touch()

            with (
                patch(f"{OPS_DEPLOYMENT}.recreate_venv", side_effect=fake_recreate_venv) as recreate,
                patch(f"{OPS_DEPLOYMENT}.run"),
            ):
                rebuild_venv(venv, root)

            recreate.assert_called_once_with(venv)

    def test_rebuild_venv_recreate_flag_removes_existing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv = root / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python").touch()
            (venv / "bin/pip").touch()
            (venv / "marker").write_text("previous", encoding="utf-8")

            def fake_recreate_venv(target: Path) -> None:
                (target / "marker").write_text("new", encoding="utf-8")

            with (
                patch(f"{OPS_DEPLOYMENT}.recreate_venv", side_effect=fake_recreate_venv) as recreate,
                patch(f"{OPS_DEPLOYMENT}.run"),
            ):
                rebuild_venv(venv, root, recreate=True)

            recreate.assert_called_once_with(venv)
            self.assertEqual((venv / "marker").read_text(encoding="utf-8"), "new")

    def test_rebuild_venv_fails_loudly_when_package_install_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv = root / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python").touch()
            (venv / "bin/pip").touch()
            (venv / "marker").write_text("previous", encoding="utf-8")

            def fake_run(command, **_kwargs):
                if command[:2] == [venv / "bin/pip", "install"] and command[-1] == root:
                    raise OpsError("package install failed")

            with (
                patch(f"{OPS_DEPLOYMENT}.recreate_venv"),
                patch(f"{OPS_DEPLOYMENT}.run", side_effect=fake_run),
                self.assertRaisesRegex(OpsError, "package install failed"),
            ):
                rebuild_venv(venv, root)

            self.assertEqual((venv / "marker").read_text(encoding="utf-8"), "previous")

    def test_rebuild_venv_fails_loudly_when_version_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv = root / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python").touch()
            (venv / "bin/pip").touch()

            def fake_run(command, **_kwargs):
                if command[:3] == [venv / "bin/python", "-m", "bluetooth_2_usb"]:
                    raise OpsError("version check failed")

            with (
                patch(f"{OPS_DEPLOYMENT}.recreate_venv"),
                patch(f"{OPS_DEPLOYMENT}.run", side_effect=fake_run),
                self.assertRaisesRegex(OpsError, "version check failed"),
            ):
                rebuild_venv(venv, root)

            self.assertTrue(venv.is_dir())
            self.assertTrue((venv / "bin").is_dir())

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
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.PATHS", paths))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.require_commands"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.detect_boot_dir", return_value=root))
                stack.enter_context(patch(f"{BOOT_CONFIG}.boot_config_path", return_value=root / "config.txt"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.boot_cmdline_path", return_value=root / "cmdline.txt"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.current_pi_model", return_value="Raspberry Pi 4"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.dwc2_mode", return_value="module"))
                stack.enter_context(
                    patch(f"{BOOT_CONFIG}.board_overlay_line", return_value="dtoverlay=dwc2,dr_mode=peripheral")
                )
                stack.enter_context(patch(f"{BOOT_CONFIG}.required_boot_modules_csv", return_value="dwc2,libcomposite"))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.clear_bluetooth_rfkill_soft_blocks"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.normalize_dwc2_overlay"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.normalize_modules_load"))
                rebuild = stack.enter_context(
                    patch(f"{OPS_DEPLOYMENT}.rebuild_venv", side_effect=OpsError("venv failed"))
                )
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.run", side_effect=fake_run))

                with self.assertRaises(OpsError):
                    install(recreate_venv=True)

        self.assertIn(["systemctl", "stop", paths.service_unit], commands)
        self.assertNotIn(["systemctl", "start", paths.service_unit], commands)
        rebuild.assert_called_once_with(paths.install_dir / "venv", paths.install_dir, recreate=True)

    def test_install_canonicalizes_managed_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            paths = ManagedPaths(install_dir=root, env_file=root / "managed-env")
            canonicalized_paths = []
            call_order = []

            def record_normalize(path: Path) -> bool:
                call_order.append(("normalize", path))
                return True

            def record_canonicalize(path: Path) -> bool:
                call_order.append(("canonicalize", path))
                canonicalized_paths.append(path)
                return True

            def fake_run(command, *, check=True, capture=False):
                class Completed:
                    returncode = 3 if command[-1:] == ["--validate-env"] else 0
                    stdout = ""

                return Completed()

            with ExitStack() as stack:
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.PATHS", paths))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.require_commands"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.detect_boot_dir", return_value=root))
                stack.enter_context(patch(f"{BOOT_CONFIG}.boot_config_path", return_value=root / "config.txt"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.boot_cmdline_path", return_value=root / "cmdline.txt"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.current_pi_model", return_value="Raspberry Pi 4"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.dwc2_mode", return_value="module"))
                stack.enter_context(
                    patch(f"{BOOT_CONFIG}.board_overlay_line", return_value="dtoverlay=dwc2,dr_mode=peripheral")
                )
                stack.enter_context(patch(f"{BOOT_CONFIG}.required_boot_modules_csv", return_value="dwc2,libcomposite"))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.clear_bluetooth_rfkill_soft_blocks"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.normalize_dwc2_overlay"))
                stack.enter_context(patch(f"{BOOT_CONFIG}.normalize_modules_load"))
                rebuild = stack.enter_context(patch(f"{OPS_DEPLOYMENT}.rebuild_venv", return_value=None))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.install_service_unit"))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.install_cli_links"))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.activate_service_unit"))
                normalize = stack.enter_context(
                    patch(f"{OPS_DEPLOYMENT}.normalize_service_settings_file", side_effect=record_normalize)
                )
                stack.enter_context(
                    patch(f"{OPS_DEPLOYMENT}.canonicalize_service_settings_bools", side_effect=record_canonicalize)
                )
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.run", side_effect=fake_run))

                install()

        normalize.assert_called_once_with(paths.env_file)
        self.assertEqual(canonicalized_paths, [paths.env_file])
        self.assertEqual(call_order[:2], [("normalize", paths.env_file), ("canonicalize", paths.env_file)])
        rebuild.assert_called_once_with(paths.install_dir / "venv", paths.install_dir, recreate=False)

    def test_update_pulls_current_branch_then_reapplies_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            paths = ManagedPaths(install_dir=root)
            commands = []

            def fake_output(command):
                if command[:4] == ["git", "-C", root, "status"]:
                    return ""
                if command[:4] == ["git", "-C", root, "symbolic-ref"]:
                    return "staging"
                raise AssertionError(f"unexpected output command: {command}")

            def fake_run(command, **_kwargs):
                commands.append(command)

            with (
                patch(f"{OPS_DEPLOYMENT}.PATHS", paths),
                patch(f"{OPS_DEPLOYMENT}.require_commands"),
                patch(f"{OPS_DEPLOYMENT}.output", side_effect=fake_output),
                patch(f"{OPS_DEPLOYMENT}.run", side_effect=fake_run),
                patch(f"{OPS_DEPLOYMENT}.install") as managed_install,
            ):
                update(recreate_venv=True)

        self.assertEqual(commands, [["git", "-C", root, "pull", "--ff-only", "origin", "staging"]])
        managed_install.assert_called_once_with(recreate_venv=True)

    def test_update_reapplies_install_even_when_pull_has_no_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            paths = ManagedPaths(install_dir=root)

            def fake_output(command):
                if command[:4] == ["git", "-C", root, "status"]:
                    return ""
                if command[:4] == ["git", "-C", root, "symbolic-ref"]:
                    return "staging"
                raise AssertionError(f"unexpected output command: {command}")

            with (
                patch(f"{OPS_DEPLOYMENT}.PATHS", paths),
                patch(f"{OPS_DEPLOYMENT}.require_commands"),
                patch(f"{OPS_DEPLOYMENT}.output", side_effect=fake_output),
                patch(f"{OPS_DEPLOYMENT}.run"),
                patch(f"{OPS_DEPLOYMENT}.install") as managed_install,
            ):
                update()

        managed_install.assert_called_once_with(recreate_venv=False)

    def test_update_refuses_dirty_checkout_before_pull_or_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            paths = ManagedPaths(install_dir=root)

            with (
                patch(f"{OPS_DEPLOYMENT}.PATHS", paths),
                patch(f"{OPS_DEPLOYMENT}.require_commands"),
                patch(f"{OPS_DEPLOYMENT}.output", return_value=" M src/file.py"),
                patch(f"{OPS_DEPLOYMENT}.run") as run_command,
                patch(f"{OPS_DEPLOYMENT}.install") as managed_install,
                self.assertRaisesRegex(OpsError, "Refusing to update a dirty managed checkout"),
            ):
                update()

        run_command.assert_not_called()
        managed_install.assert_not_called()

    def test_update_does_not_install_when_pull_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            paths = ManagedPaths(install_dir=root)

            def fake_output(command):
                if command[:4] == ["git", "-C", root, "status"]:
                    return ""
                if command[:4] == ["git", "-C", root, "symbolic-ref"]:
                    return "staging"
                raise AssertionError(f"unexpected output command: {command}")

            with (
                patch(f"{OPS_DEPLOYMENT}.PATHS", paths),
                patch(f"{OPS_DEPLOYMENT}.require_commands"),
                patch(f"{OPS_DEPLOYMENT}.output", side_effect=fake_output),
                patch(f"{OPS_DEPLOYMENT}.run", side_effect=OpsError("pull failed")),
                patch(f"{OPS_DEPLOYMENT}.install") as managed_install,
                self.assertRaisesRegex(OpsError, "pull failed"),
            ):
                update()

        managed_install.assert_not_called()

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
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.PATHS", paths))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.load_readonly_config", return_value=config))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.service_installed", return_value=False))
                remove_owned_gadgets = stack.enter_context(patch(f"{OPS_DEPLOYMENT}.remove_owned_gadgets"))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.remove_bluetooth_persist_dropin"))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.remove_bluetooth_bind_mount_unit"))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.remove_persist_mount_unit"))
                stack.enter_context(patch(f"{OPS_DEPLOYMENT}.run", side_effect=fake_run))

                uninstall()

        remove_owned_gadgets.assert_called_once_with()
        self.assertNotIn(["systemctl", "stop", paths.service_unit], commands)
        self.assertNotIn(["systemctl", "disable", paths.service_unit], commands)
        self.assertIn(["systemctl", "daemon-reload"], commands)
