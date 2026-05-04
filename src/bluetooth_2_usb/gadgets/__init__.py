from __future__ import annotations

__all__ = [
    "GadgetHidDevice",
    "GadgetLayout",
    "HidGadgets",
    "build_default_layout",
    "rebuild_gadget",
    "remove_owned_gadgets",
]


def __getattr__(name: str):
    if name in {"GadgetHidDevice", "GadgetLayout", "build_default_layout"}:
        from .layout import GadgetHidDevice, GadgetLayout, build_default_layout

        return {
            "GadgetHidDevice": GadgetHidDevice,
            "GadgetLayout": GadgetLayout,
            "build_default_layout": build_default_layout,
        }[name]
    if name == "HidGadgets":
        from .manager import HidGadgets

        return HidGadgets
    if name in {"rebuild_gadget", "remove_owned_gadgets"}:
        from .config import rebuild_gadget, remove_owned_gadgets

        return {"rebuild_gadget": rebuild_gadget, "remove_owned_gadgets": remove_owned_gadgets}[name]
    raise AttributeError(name)
