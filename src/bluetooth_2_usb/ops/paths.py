from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ManagedPaths:
    install_dir: Path = Path("/opt/bluetooth_2_usb")
    service_unit: str = "bluetooth_2_usb.service"
    log_dir: Path = Path("/var/log/bluetooth_2_usb")
    state_dir: Path = Path("/var/lib/bluetooth_2_usb")
    env_file: Path = Path("/etc/default/bluetooth_2_usb")
    readonly_env_file: Path = Path("/etc/default/bluetooth_2_usb_readonly")
    persist_mount: Path = Path("/mnt/b2u-persist")
    persist_bluetooth_dir: Path = field(init=False)
    bluetooth_bind_mount_unit: Path = Path("/etc/systemd/system/var-lib-bluetooth.mount")
    bluetooth_service_dropin_dir: Path = Path("/etc/systemd/system/bluetooth.service.d")
    bluetooth_service_dropin: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "persist_bluetooth_dir", self.persist_mount / "bluetooth")
        object.__setattr__(
            self,
            "bluetooth_service_dropin",
            self.bluetooth_service_dropin_dir / "bluetooth_2_usb_persist.conf",
        )

    @property
    def venv_python(self) -> Path:
        return self.install_dir / "venv/bin/python"


PATHS = ManagedPaths()
