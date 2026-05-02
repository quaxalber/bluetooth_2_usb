from __future__ import annotations

import shutil
from pathlib import Path

from .commands import fail, info, ok, run

RULE_DST = Path("/etc/udev/rules.d/70-bluetooth_2_usb_hidapi.rules")
VENDOR_ID = "1d6b"
PRODUCT_ID = "0104"


def install_hid_udev_rule(repo_root: Path) -> None:
    rule_src = repo_root / "udev/70-bluetooth_2_usb_hidapi.rules"
    if not rule_src.is_file():
        fail(f"Rule source not found: {rule_src}")
    if run(["getent", "group", "input"], check=False, capture=True).returncode != 0:
        fail("The 'input' group does not exist on this host.")
    shutil.copy2(rule_src, RULE_DST)
    RULE_DST.chmod(0o644)
    run(["udevadm", "control", "--reload-rules"])
    run(
        [
            "udevadm",
            "trigger",
            "--subsystem-match=usb",
            f"--attr-match=idVendor={VENDOR_ID}",
            f"--attr-match=idProduct={PRODUCT_ID}",
        ]
    )
    ok(f"Installed udev rule: {RULE_DST}")
    info("Reconnect the Pi gadget or replug the OTG cable if the USB device permissions do not update immediately.")
