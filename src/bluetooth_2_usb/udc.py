from __future__ import annotations

from pathlib import Path

UDC_ROOT = Path("/sys/class/udc")


def list_udc_controllers(udc_root: Path = UDC_ROOT) -> tuple[Path, ...]:
    if not udc_root.is_dir():
        raise FileNotFoundError(f"No UDC controller was found in {udc_root}")
    try:
        return tuple(sorted((entry for entry in udc_root.iterdir() if entry.is_dir()), key=lambda entry: entry.name))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"No UDC controller was found in {udc_root}") from exc


def resolve_single_udc_controller(udc_root: Path = UDC_ROOT) -> Path:
    controllers = list_udc_controllers(udc_root)
    if not controllers:
        raise FileNotFoundError(f"No UDC controller was found in {udc_root}")
    if len(controllers) > 1:
        names = ", ".join(controller.name for controller in controllers)
        raise RuntimeError(f"Multiple UDC controllers were found in {udc_root}: {names}")
    return controllers[0]


def resolve_single_udc_name(udc_root: Path = UDC_ROOT) -> str:
    return resolve_single_udc_controller(udc_root).name


def resolve_single_udc_state_path(udc_root: Path = UDC_ROOT) -> Path:
    state_path = resolve_single_udc_controller(udc_root) / "state"
    if not state_path.is_file():
        raise FileNotFoundError(f"UDC state file not found: {state_path}")
    return state_path


def udc_states(udc_root: Path = UDC_ROOT) -> dict[str, str]:
    states: dict[str, str] = {}
    for controller in list_udc_controllers(udc_root):
        try:
            state = (controller / "state").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            state = "unknown"
        states[controller.name] = state or "unknown"
    return states
