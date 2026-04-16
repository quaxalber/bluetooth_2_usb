import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BLUETOOTH_LIB = REPO_ROOT / "scripts/lib/bluetooth.sh"


def _write_rfkill_entry(
    root: Path,
    index: int,
    *,
    type_name: str = "bluetooth",
    soft: str = "0",
    hard: str = "0",
    state: str = "1",
) -> Path:
    rfkill_dir = root / f"rfkill{index}"
    rfkill_dir.mkdir(parents=True, exist_ok=True)
    (rfkill_dir / "type").write_text(f"{type_name}\n", encoding="utf-8")
    (rfkill_dir / "soft").write_text(f"{soft}\n", encoding="utf-8")
    (rfkill_dir / "hard").write_text(f"{hard}\n", encoding="utf-8")
    (rfkill_dir / "state").write_text(f"{state}\n", encoding="utf-8")
    return rfkill_dir


class BluetoothRfkillLibTest(unittest.TestCase):
    def _run_helper(self, rfkill_root: Path) -> subprocess.CompletedProcess[str]:
        command = (
            f"source {shlex.quote(str(BLUETOOTH_LIB))}; "
            "clear_bluetooth_rfkill_soft_blocks"
        )
        env = os.environ.copy()
        env["B2U_RFKILL_ROOT"] = str(rfkill_root)
        return subprocess.run(
            ["bash", "-lc", command],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_clear_bluetooth_rfkill_soft_blocks_clears_soft_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rfkill_root = Path(tmpdir)
            entry = _write_rfkill_entry(rfkill_root, 0, soft="1", hard="0", state="0")

            completed = self._run_helper(rfkill_root)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual((entry / "soft").read_text(encoding="utf-8").strip(), "0")
            self.assertIn("Cleared Bluetooth rfkill soft block", completed.stdout)

    def test_clear_bluetooth_rfkill_soft_blocks_keeps_hard_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rfkill_root = Path(tmpdir)
            entry = _write_rfkill_entry(rfkill_root, 0, soft="1", hard="1", state="0")

            completed = self._run_helper(rfkill_root)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual((entry / "soft").read_text(encoding="utf-8").strip(), "1")
            self.assertIn("hard-blocked", completed.stdout)
