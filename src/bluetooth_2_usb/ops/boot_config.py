from __future__ import annotations

import gzip
import os
import platform
import re
from pathlib import Path

from .commands import backup_file, fail, output, require_commands, run


def detect_boot_dir() -> Path:
    return Path("/boot/firmware") if Path("/boot/firmware").is_dir() else Path("/boot")


def boot_config_path() -> Path:
    return detect_boot_dir() / "config.txt"


def boot_cmdline_path() -> Path:
    return detect_boot_dir() / "cmdline.txt"


def current_pi_model() -> str:
    model_file = Path("/proc/device-tree/model")
    if not model_file.is_file():
        fail("Could not determine Raspberry Pi model from /proc/device-tree/model.")
    return model_file.read_bytes().replace(b"\0", b"").decode("utf-8", "replace")


def current_root_filesystem_type() -> str:
    value = output(["findmnt", "-n", "-o", "FSTYPE", "--target", "/"])
    if not value:
        fail("Could not determine the live root filesystem type.")
    return value


def root_overlay_state() -> str:
    try:
        return "yes" if current_root_filesystem_type() == "overlay" else "no"
    except Exception:
        return "unknown"


def root_overlay_report() -> str:
    completed = run(["findmnt", "-n", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS", "--target", "/"], check=False, capture=True)
    return completed.stdout.strip()


def boot_config_model_filters(model: str | None = None) -> list[str]:
    resolved = current_pi_model() if model is None else model
    cases: list[tuple[str, list[str]]] = [
        ("Raspberry Pi 500", ["pi5", "pi500"]),
        ("Raspberry Pi 5", ["pi5"]),
        ("Compute Module 5", ["pi5", "cm5"]),
        ("Raspberry Pi 400", ["pi4", "pi400"]),
        ("Compute Module 4S", ["pi4", "cm4s"]),
        ("Compute Module 4", ["pi4", "cm4"]),
        ("Raspberry Pi 4", ["pi4"]),
        ("Compute Module 3 Plus", ["pi3", "pi3+", "cm3+"]),
        ("Compute Module 3+", ["pi3", "pi3+", "cm3+"]),
        ("Compute Module 3", ["pi3", "cm3"]),
        ("Raspberry Pi 3 Model A Plus", ["pi3", "pi3+"]),
        ("Raspberry Pi 3 Model B Plus", ["pi3", "pi3+"]),
        ("Raspberry Pi 3", ["pi3"]),
        ("Raspberry Pi Zero 2", ["pi0", "pi0w", "pi02"]),
        ("Raspberry Pi Zero W", ["pi0", "pi0w"]),
        ("Raspberry Pi Zero", ["pi0"]),
        ("Raspberry Pi 2", ["pi2"]),
        ("Compute Module 1", ["pi1", "cm1"]),
        ("Compute Module 0", ["pi0", "cm0"]),
        ("Raspberry Pi 1", ["pi1"]),
    ]
    for needle, filters in cases:
        if needle in resolved:
            return filters
    return []


def boot_config_assignment_value(
    key: str, config_file: Path | None = None, model_filters: list[str] | None = None
) -> str:
    path = boot_config_path() if config_file is None else config_file
    if not path.is_file():
        return ""

    allowed = {"", "all"}
    allowed.update(section.lower() for section in (model_filters or boot_config_model_filters()))
    value = ""
    current_section = ""
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip().lower()
            continue
        if "=" not in line or current_section not in allowed:
            continue
        current_key, current_value = line.split("=", 1)
        if current_key.strip() == key:
            value = current_value.strip()
    return value


def effective_arm_64bit() -> str:
    configured = boot_config_assignment_value("arm_64bit")
    if configured in {"0", "1"}:
        return configured
    return "1" if platform.machine() == "aarch64" else "0"


def default_kernel_image(model: str | None = None) -> str:
    resolved_model = model if model is not None else _try_current_pi_model()
    arm_64bit = effective_arm_64bit()
    if any(value in resolved_model for value in ("Raspberry Pi 500", "Raspberry Pi 5", "Compute Module 5")):
        return "kernel_2712.img"
    if any(value in resolved_model for value in ("Raspberry Pi 400", "Raspberry Pi 4", "Compute Module 4")):
        return "kernel8.img" if arm_64bit == "1" else "kernel7l.img"
    if any(
        value in resolved_model
        for value in ("Raspberry Pi 2", "Raspberry Pi 3", "Raspberry Pi Zero 2", "Compute Module 3")
    ):
        return "kernel8.img" if arm_64bit == "1" else "kernel7.img"
    if platform.machine() == "aarch64":
        return "kernel8.img"
    if platform.machine() == "armv7l":
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        return "kernel7l.img" if re.search(r"^Features.*\blpae\b", cpuinfo, re.MULTILINE) else "kernel7.img"
    return "kernel.img"


def _try_current_pi_model() -> str:
    try:
        return current_pi_model()
    except Exception:
        return ""


def configured_kernel_image(config_file: Path | None = None) -> str:
    value = boot_config_assignment_value("kernel", config_file)
    return value or default_kernel_image()


def configured_initramfs_file(config_file: Path | None = None) -> str:
    path = boot_config_path() if config_file is None else config_file
    if not path.is_file():
        return ""
    allowed = {"", "all"}
    allowed.update(section.lower() for section in boot_config_model_filters())
    value = ""
    current_section = ""
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip().lower()
            continue
        if current_section not in allowed or not line.startswith("initramfs "):
            continue
        parts = line.split()
        if len(parts) >= 2:
            value = parts[1]
    return value


def auto_initramfs_enabled(config_file: Path | None = None) -> bool:
    return boot_config_assignment_value("auto_initramfs", config_file) == "1"


def expected_auto_initramfs_name(kernel_image: str | None = None) -> str:
    resolved = configured_kernel_image() if not kernel_image else kernel_image
    base_name = Path(resolved).name.rsplit(".", 1)[0]
    return f"initramfs{base_name.removeprefix('kernel')}" if base_name.startswith("kernel") else ""


def expected_boot_initramfs_file(config_file: Path | None = None) -> str:
    explicit = configured_initramfs_file(config_file)
    if explicit:
        return explicit
    if auto_initramfs_enabled(config_file):
        return expected_auto_initramfs_name(configured_kernel_image(config_file))
    return ""


def boot_initramfs_target_path(target_file: str | None = None) -> Path:
    resolved = expected_boot_initramfs_file() if not target_file else target_file
    if not resolved:
        fail(
            "Boot initramfs target is not configured. Set auto_initramfs=1 or add an "
            + f"initramfs entry to {boot_config_path()}."
        )
    if resolved.startswith("/") or "/" in resolved or ".." in resolved:
        fail(f"Unsafe initramfs target file in {boot_config_path()}: {resolved}")
    return detect_boot_dir() / resolved


def current_kernel_release() -> str:
    return output(["uname", "-r"])


def versioned_initrd_candidates(kernel_release: str | None = None) -> list[Path]:
    resolved = current_kernel_release() if kernel_release is None else kernel_release
    boot_dir = detect_boot_dir()
    candidates = [Path(f"/boot/initrd.img-{resolved}")]
    if boot_dir != Path("/boot"):
        candidates.append(boot_dir / f"initrd.img-{resolved}")
    return candidates


def find_versioned_initramfs_image(kernel_release: str | None = None) -> Path | None:
    for candidate in versioned_initrd_candidates(kernel_release):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def ensure_initramfs_tools_ready() -> None:
    require_commands(["install", "python3", "update-initramfs"])
    if not any(Path(path, "mkinitramfs").exists() for path in os.environ.get("PATH", "").split(os.pathsep)):
        fail("mkinitramfs is missing. Install initramfs-tools before enabling read-only mode.")


def ensure_kernel_artifacts_present_for_initramfs(kernel_release: str) -> None:
    if not Path(f"/lib/modules/{kernel_release}").is_dir():
        fail(f"Kernel modules for {kernel_release} are missing at /lib/modules/{kernel_release}.")
    if not Path(f"/boot/config-{kernel_release}").is_file() and not Path("/proc/config.gz").is_file():
        fail(
            f"Kernel configuration for {kernel_release} is unavailable. "
            + f"Expected /boot/config-{kernel_release} or /proc/config.gz."
        )


def run_update_initramfs(action: str, kernel_release: str) -> bool:
    completed = run(["update-initramfs", action, "-k", kernel_release], check=False, capture=True)
    filtered = [
        line
        for line in (completed.stdout + completed.stderr).splitlines()
        if not line.startswith("WARNING:") and not line.startswith("NOTE:")
    ]
    if filtered:
        print("\n".join(filtered))
    return completed.returncode == 0


def build_or_refresh_initramfs_for_running_kernel(kernel_release: str, target_path: Path) -> Path:
    existing = find_versioned_initramfs_image(kernel_release)
    if existing and existing == target_path and target_path.is_file():
        backup_file(target_path)
    if existing:
        if not run_update_initramfs("-u", kernel_release) and not run_update_initramfs("-c", kernel_release):
            fail(f"update-initramfs failed for kernel {kernel_release}.")
    elif not run_update_initramfs("-c", kernel_release):
        fail(f"update-initramfs failed for kernel {kernel_release}.")
    image = find_versioned_initramfs_image(kernel_release)
    if image is None:
        fail(f"update-initramfs completed, but no initramfs image was found for kernel {kernel_release}.")
    return image


def install_expected_boot_initramfs(source_image: Path, target_path: Path) -> Path:
    if not source_image.is_file() or source_image.stat().st_size == 0:
        fail(f"Initramfs source image is missing or empty: {source_image}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if source_image != target_path:
        if target_path.is_file():
            backup_file(target_path)
        run(["install", "-m", "0644", source_image, target_path])
    if not target_path.is_file() or target_path.stat().st_size == 0:
        fail(f"Boot initramfs target is missing or empty after install: {target_path}")
    return target_path


def ensure_bootable_initramfs_for_current_kernel() -> Path:
    kernel_release = current_kernel_release()
    target_path = boot_initramfs_target_path()
    overlay_state = root_overlay_state()
    if overlay_state == "yes":
        if not target_path.is_file() or target_path.stat().st_size == 0:
            fail(
                f"Boot initramfs target {target_path} is missing while the live root overlay is active. "
                + "Disable read-only mode before rebuilding initramfs."
            )
        return target_path
    if overlay_state != "no":
        fail("Unable to determine live root overlay state; aborting initramfs operations.")
    ensure_initramfs_tools_ready()
    ensure_kernel_artifacts_present_for_initramfs(kernel_release)
    image = build_or_refresh_initramfs_for_running_kernel(kernel_release, target_path)
    return install_expected_boot_initramfs(image, target_path)


def kernel_config_snippet() -> str:
    kernel_config = Path(f"/boot/config-{current_kernel_release()}")
    if kernel_config.is_file():
        text = kernel_config.read_text(encoding="utf-8", errors="replace")
    elif Path("/proc/config.gz").is_file():
        text = gzip.decompress(Path("/proc/config.gz").read_bytes()).decode("utf-8", "replace")
    else:
        return ""
    return "\n".join(
        line for line in text.splitlines() if line.startswith(("CONFIG_USB_DWC2=", "CONFIG_USB_LIBCOMPOSITE="))
    )


def dwc2_mode() -> str:
    snippet = kernel_config_snippet()
    if "CONFIG_USB_DWC2=y" in snippet:
        return "builtin"
    if "CONFIG_USB_DWC2=m" in snippet:
        return "module"
    if run(["modinfo", "dwc2"], check=False, capture=True).returncode == 0:
        return "module"
    if Path("/sys/module/dwc2").is_dir():
        return "builtin"
    return "unknown"


def required_boot_modules_csv(mode: str | None = None) -> str:
    if mode is None:
        mode = dwc2_mode()
    if mode == "module":
        return "dwc2,libcomposite"
    if mode == "builtin":
        return "libcomposite"
    fail(
        "Could not determine whether dwc2 is built in or modular. "
        + "Refusing to rewrite modules-load= with an ambiguous boot configuration."
    )
    raise AssertionError("unreachable")


def board_overlay_line(model: str) -> str:
    if "Raspberry Pi 4" in model or "Raspberry Pi 5" in model:
        return "dtoverlay=dwc2,dr_mode=peripheral"
    return "dtoverlay=dwc2"


def expected_dwc2_overlay_line() -> str:
    return board_overlay_line(current_pi_model())


def normalize_dwc2_overlay(config_file: Path, overlay_line: str) -> None:
    if not config_file.is_file():
        fail(f"Boot config file not found: {config_file}")
    if not os.access(config_file, os.W_OK):
        fail(f"Boot config file is not writable: {config_file}")
    backup_file(config_file)
    lines = config_file.read_text(encoding="utf-8", errors="replace").splitlines()
    filtered = [line for line in lines if not line.lstrip().startswith("dtoverlay=dwc2")]
    result: list[str] = []
    inserted = False
    for line in filtered:
        result.append(line)
        if not inserted and line.strip() == "[all]":
            result.append(overlay_line)
            inserted = True
    if not inserted:
        if result and result[-1] != "":
            result.append("")
        result.extend(["[all]", overlay_line])
    config_file.write_text("\n".join(result) + "\n", encoding="utf-8")


def normalize_modules_load(cmdline_file: Path, modules: str) -> None:
    if not cmdline_file.is_file():
        fail(f"Boot cmdline file not found: {cmdline_file}")
    if not os.access(cmdline_file, os.W_OK):
        fail(f"Boot cmdline file is not writable: {cmdline_file}")
    backup_file(cmdline_file)
    tokens = cmdline_file.read_text(encoding="utf-8", errors="replace").strip().split()
    existing: list[str] = []
    for token in tokens:
        if token.startswith("modules-load="):
            existing.extend(value for value in token.split("=", 1)[1].split(",") if value)
    merged: list[str] = []
    for value in [*existing, *modules.split(",")]:
        if value and value not in merged:
            merged.append(value)
    tokens = [token for token in tokens if not token.startswith("modules-load=")]
    tokens.append("modules-load=" + ",".join(merged))
    cmdline_file.write_text(" ".join(tokens) + "\n", encoding="utf-8")
