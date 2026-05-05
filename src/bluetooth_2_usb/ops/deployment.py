from __future__ import annotations

import shutil
from pathlib import Path

from bluetooth_2_usb.service_settings import canonicalize_service_settings_bools

from . import boot_config
from .bluetooth import clear_bluetooth_rfkill_soft_blocks
from .commands import fail, info, ok, output, require_commands, run, warn
from .paths import PATHS
from .readonly import (
    load_readonly_config,
    remove_bluetooth_bind_mount_unit,
    remove_bluetooth_persist_dropin,
    remove_persist_mount_unit,
)

DEFAULT_ENV_TEXT = """# Structured runtime configuration for bluetooth_2_usb.service.
B2U_AUTO_DISCOVER=true
B2U_DEVICE_IDS=
B2U_GRAB_DEVICES=true
B2U_INTERRUPT_SHORTCUT=CTRL+SHIFT+F12
B2U_LOG_TO_FILE=false
B2U_LOG_PATH=/var/log/bluetooth_2_usb/bluetooth_2_usb.log
B2U_DEBUG=false
B2U_UDC_PATH=
"""


def install_service_unit(repo_root: Path) -> None:
    shutil.copy2(repo_root / "bluetooth_2_usb.service", Path("/etc/systemd/system") / PATHS.service_unit)
    (Path("/etc/systemd/system") / PATHS.service_unit).chmod(0o644)


def activate_service_unit() -> None:
    was_active = run(["systemctl", "is-active", "--quiet", PATHS.service_unit], check=False).returncode == 0
    run(["systemctl", "enable", PATHS.service_unit])
    run(["systemctl", "restart" if was_active else "start", PATHS.service_unit])


def write_default_env_file() -> None:
    if not PATHS.env_file.exists():
        PATHS.env_file.write_text(DEFAULT_ENV_TEXT, encoding="utf-8")
        PATHS.env_file.chmod(0o644)


def install_cli_links() -> None:
    local_bin = Path("/usr/local/bin")
    local_bin.mkdir(parents=True, exist_ok=True)
    (local_bin / "bluetooth_2_usb.loopback").unlink(missing_ok=True)
    link = local_bin / "bluetooth_2_usb"
    link.unlink(missing_ok=True)
    link.symlink_to(PATHS.install_dir / "venv" / "bin" / "bluetooth_2_usb")


def recreate_venv(venv_dir: Path) -> None:
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    run(["python3", "-m", "venv", venv_dir])


def rebuild_venv(venv_dir: Path, package_dir: Path) -> None:
    shutil.rmtree(venv_dir, ignore_errors=True)
    recreate_venv(venv_dir)
    run([venv_dir / "bin/pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run([venv_dir / "bin/pip", "install", "--upgrade", package_dir])
    run([venv_dir / "bin/python", "-m", "bluetooth_2_usb", "--version"], capture=True)


def service_installed() -> bool | None:
    completed = run(
        ["systemctl", "list-unit-files", "--type=service", "--no-legend", "--no-pager"], check=False, capture=True
    )
    if completed.returncode != 0:
        warn(
            f"systemctl list-unit-files failed (rc={completed.returncode}); "
            + f"cannot determine state of {PATHS.service_unit}"
        )
        return None
    return any(line.split(None, 1)[0] == PATHS.service_unit for line in completed.stdout.splitlines() if line.split())


def install(repo_root: Path) -> None:
    require_commands(["apt-get", "awk", "grep", "git", "install", "python3", "sed", "systemctl"])
    if repo_root != PATHS.install_dir:
        fail(f"Clone this repository to {PATHS.install_dir} and rerun install from there.")
    if not (PATHS.install_dir / ".git").is_dir():
        fail(f"Expected a git checkout at {PATHS.install_dir}.")

    boot_dir = boot_config.detect_boot_dir()
    config_txt = boot_config.boot_config_path()
    cmdline_txt = boot_config.boot_cmdline_path()
    model = boot_config.current_pi_model()
    dwc2_mode = boot_config.dwc2_mode()
    overlay_line = boot_config.board_overlay_line(model)
    modules = boot_config.required_boot_modules_csv(dwc2_mode)

    info(f"Detected model: {model}")
    info(f"Using boot directory: {boot_dir}")
    info(f"Detected dwc2 mode: {dwc2_mode}")
    run(["apt-get", "update", "-y"])
    run(
        [
            "apt-get",
            "install",
            "-y",
            "--no-install-recommends",
            "git",
            "python3",
            "python3-pip",
            "python3-venv",
            "python3-dev",
        ]
    )
    clear_bluetooth_rfkill_soft_blocks()
    boot_config.normalize_dwc2_overlay(config_txt, overlay_line)
    boot_config.normalize_modules_load(cmdline_txt, modules)
    ok("Boot configuration updated")

    was_active = run(["systemctl", "is-active", "--quiet", PATHS.service_unit], check=False).returncode == 0
    if was_active:
        info(f"Stopping {PATHS.service_unit} before rebuilding the managed installation")
        run(["systemctl", "stop", PATHS.service_unit])

    info(f"Rebuilding virtual environment at {PATHS.install_dir / 'venv'}")
    rebuild_venv(PATHS.install_dir / "venv", PATHS.install_dir)
    ok(f"Virtual environment updated at {PATHS.install_dir / 'venv'}")

    install_service_unit(repo_root)
    write_default_env_file()
    canonicalize_service_settings_bools(PATHS.env_file)
    run([PATHS.venv_python, "-m", "bluetooth_2_usb.service_settings", "--check"], capture=True)
    install_cli_links()
    run(["systemctl", "daemon-reload"])
    activate_service_unit()
    ok(f"Service {PATHS.service_unit} enabled and started")
    run([PATHS.venv_python, "-m", "bluetooth_2_usb", "--version"], capture=True)
    ok("CLI version check succeeded")

    validate = run([PATHS.venv_python, "-m", "bluetooth_2_usb", "--validate-env"], check=False)
    if validate.returncode == 0:
        ok("Environment validation passed")
    elif validate.returncode == 3:
        warn("Environment validation reports missing runtime prerequisites until after reboot")
    else:
        fail(f"Environment validation failed with exit code {validate.returncode}")
    info("Next steps")
    info("1. Reboot the Pi so the updated boot configuration takes effect.")
    info("2. After reboot, run: sudo bluetooth_2_usb smoketest")
    info("3. For read-only operation, run: sudo bluetooth_2_usb readonly setup --device /dev/YOUR-PARTITION")
    info("   Then run: sudo bluetooth_2_usb readonly enable")


def update(repo_root: Path) -> None:
    require_commands(["git"])
    if repo_root != PATHS.install_dir:
        fail(f"Clone this repository to {PATHS.install_dir} and rerun update from there.")
    if not (PATHS.install_dir / ".git").is_dir():
        fail(f"Expected a git checkout at {PATHS.install_dir}.")
    if output(["git", "-C", PATHS.install_dir, "status", "--porcelain", "--untracked-files=all"]):
        fail(
            f"Refusing to update a dirty managed checkout at {PATHS.install_dir}. "
            + "Commit, stash, or remove local changes first."
        )
    branch = output(["git", "-C", PATHS.install_dir, "symbolic-ref", "--quiet", "--short", "HEAD"])
    info(f"Pulling latest {branch}")
    run(["git", "-C", PATHS.install_dir, "pull", "--ff-only", "origin", branch])
    info("Reapplying managed install")
    install(repo_root)


def uninstall() -> None:
    config = load_readonly_config()
    installed = service_installed()
    manage_b2u_service = bool(installed)
    if installed is None:
        fail(f"Unable to query systemd for {PATHS.service_unit}")
    if not installed:
        load_state = run(
            ["systemctl", "show", "-P", "LoadState", PATHS.service_unit], check=False, capture=True
        ).stdout.strip()
        manage_b2u_service = load_state != "not-found"

    if manage_b2u_service:
        run(["systemctl", "stop", PATHS.service_unit])
        if run(["systemctl", "is-active", "--quiet", PATHS.service_unit], check=False).returncode == 0:
            run(["systemctl", "kill", "--kill-who=all", PATHS.service_unit])
        run(["systemctl", "disable", PATHS.service_unit])
        run(["systemctl", "reset-failed", PATHS.service_unit], check=False)

    (Path("/etc/systemd/system") / PATHS.service_unit).unlink(missing_ok=True)
    PATHS.env_file.unlink(missing_ok=True)
    PATHS.readonly_env_file.unlink(missing_ok=True)
    Path("/usr/local/bin/bluetooth_2_usb").unlink(missing_ok=True)
    Path("/usr/local/bin/bluetooth_2_usb.loopback").unlink(missing_ok=True)
    remove_bluetooth_persist_dropin()
    remove_bluetooth_bind_mount_unit()
    remove_persist_mount_unit(config.persist_mount)
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "disable", "--now", "var-lib-bluetooth.mount"], check=False)

    bluetooth_was_active = run(["systemctl", "is-active", "--quiet", "bluetooth.service"], check=False).returncode == 0
    try:
        if run(["findmnt", "-rn", "/var/lib/bluetooth"], check=False, capture=True).returncode == 0:
            run(["systemctl", "stop", "bluetooth.service"])
            if run(["findmnt", "-rn", "/var/lib/bluetooth"], check=False, capture=True).returncode == 0:
                run(["umount", "/var/lib/bluetooth"])
        if run(["findmnt", "-rn", config.persist_mount], check=False, capture=True).returncode == 0:
            unit = output(["systemd-escape", "--path", "--suffix=mount", config.persist_mount])
            run(["systemctl", "disable", "--now", unit], check=False)
            if run(["findmnt", "-rn", config.persist_mount], check=False, capture=True).returncode == 0:
                run(["umount", config.persist_mount])
    finally:
        if bluetooth_was_active:
            run(["systemctl", "start", "bluetooth.service"], check=False)
    remove_owned_gadgets()
    run(["systemctl", "daemon-reload"])
    _assert_absent(Path("/etc/systemd/system") / PATHS.service_unit, "Service unit file still exists after uninstall")
    _assert_absent(PATHS.env_file, "Runtime settings file still exists after uninstall")
    _assert_absent(PATHS.readonly_env_file, "Read-only config file still exists after uninstall")
    _assert_absent(Path("/usr/local/bin/bluetooth_2_usb"), "bluetooth_2_usb CLI link still exists after uninstall")
    _assert_absent(
        Path("/usr/local/bin/bluetooth_2_usb.loopback"),
        "bluetooth_2_usb.loopback stale CLI link still exists after uninstall",
    )
    _assert_absent(PATHS.bluetooth_bind_mount_unit, "Bluetooth bind-mount unit still exists after uninstall")
    _assert_absent(PATHS.bluetooth_service_dropin, "bluetooth.service drop-in still exists after uninstall")
    if run(["systemctl", "is-enabled", PATHS.service_unit], check=False, capture=True).returncode == 0:
        fail(f"{PATHS.service_unit} is still enabled after uninstall")
    ok("Uninstall complete")
    info(f"The checkout at {PATHS.install_dir} was left in place.")


def remove_owned_gadgets() -> None:
    from bluetooth_2_usb.gadgets.config import remove_owned_gadgets as remove_gadgets

    remove_gadgets()


def _assert_absent(path: Path, message: str) -> None:
    if path.exists():
        fail(message)
