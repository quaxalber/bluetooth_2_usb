import errno
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import usb_hid

from bluetooth_2_usb.gadgets.config import CONFIG_NAME, LANGUAGE_ID, rebuild_gadget, remove_owned_gadgets
from bluetooth_2_usb.gadgets.layout import (
    COMBO_BM_ATTRIBUTES,
    DEFAULT_BCD_DEVICE,
    GadgetHidDevice,
    build_default_layout,
)
from bluetooth_2_usb.gadgets.manager import HidGadgets
from bluetooth_2_usb.hid.descriptors import (
    DEFAULT_KEYBOARD_DESCRIPTOR,
    DEFAULT_MOUSE_DESCRIPTOR,
    MOUSE_CONFIGFS_REPORT_LENGTH,
    MOUSE_IN_REPORT_LENGTH,
)


class _FakeKeyboard:
    def __init__(self) -> None:
        self.release_all_calls = 0
        self.presses = []
        self.releases = []

    async def release_all(self) -> None:
        self.release_all_calls += 1

    async def press(self, key_id) -> None:
        self.presses.append(key_id)

    async def release(self, key_id) -> None:
        self.releases.append(key_id)


class _FakeMouse:
    def __init__(self) -> None:
        self.release_all_calls = 0
        self.moves = []
        self.presses = []
        self.releases = []

    async def release_all(self) -> None:
        self.release_all_calls += 1

    async def move(self, x=0, y=0, wheel=0, pan=0) -> None:
        self.moves.append((x, y, wheel, pan))

    async def press(self, key_id) -> None:
        self.presses.append(key_id)

    async def release(self, key_id) -> None:
        self.releases.append(key_id)


class _FakeConsumer:
    def __init__(self) -> None:
        self.presses = []
        self.release_calls = 0

    async def press(self, key_id) -> None:
        self.presses.append(key_id)

    async def release(self) -> None:
        self.release_calls += 1


class _FakeHidGadgets:
    def __init__(self) -> None:
        self.keyboard = _FakeKeyboard()
        self.mouse = _FakeMouse()
        self.consumer = _FakeConsumer()
        self.release_all_calls = 0

    async def release_all(self) -> None:
        self.release_all_calls += 1
        await self.keyboard.release_all()
        await self.mouse.release_all()
        await self.consumer.release()


class HidGadgetsLayoutTest(unittest.IsolatedAsyncioTestCase):
    async def _enable_with_fakes(self, hid_gadgets: HidGadgets, keyboard, mouse, consumer) -> None:
        with patch("bluetooth_2_usb.gadgets.manager.rebuild_gadget", return_value=[]):
            with patch.object(hid_gadgets, "prune_stale_hidg_nodes"):
                with patch.object(hid_gadgets, "validate_hidg_nodes"):
                    with patch("bluetooth_2_usb.gadgets.manager.ExtendedKeyboard", return_value=keyboard):
                        with patch("bluetooth_2_usb.gadgets.manager.ExtendedMouse", return_value=mouse):
                            with patch(
                                "bluetooth_2_usb.gadgets.manager.ExtendedConsumerControl", return_value=consumer
                            ):
                                await hid_gadgets.enable()

    async def test_enable_requests_default_layout(self) -> None:
        layout = SimpleNamespace(devices=("keyboard", "mouse", "consumer"))

        with patch("bluetooth_2_usb.gadgets.manager.build_default_layout", return_value=layout):
            with patch("bluetooth_2_usb.gadgets.manager.rebuild_gadget", return_value=[]) as rebuild:
                with patch.object(HidGadgets, "prune_stale_hidg_nodes"):
                    with patch.object(HidGadgets, "validate_hidg_nodes"):
                        with patch("bluetooth_2_usb.gadgets.manager.ExtendedKeyboard"):
                            with patch("bluetooth_2_usb.gadgets.manager.ExtendedMouse"):
                                with patch("bluetooth_2_usb.gadgets.manager.ExtendedConsumerControl"):
                                    await HidGadgets().enable()

        rebuild.assert_called_once_with(layout)

    async def test_release_all_releases_keyboard_mouse_and_consumer(self) -> None:
        hid_gadgets = HidGadgets()
        keyboard = _FakeKeyboard()
        mouse = _FakeMouse()
        consumer = _FakeConsumer()
        await self._enable_with_fakes(hid_gadgets, keyboard, mouse, consumer)

        await hid_gadgets.release_all()

        self.assertEqual(keyboard.release_all_calls, 1)
        self.assertEqual(mouse.release_all_calls, 1)
        self.assertEqual(consumer.release_calls, 1)

    async def test_release_all_continues_when_one_raises(self) -> None:
        hid_gadgets = HidGadgets()
        keyboard = _FakeKeyboard()
        mouse = _FakeMouse()
        consumer = _FakeConsumer()
        keyboard.release_all = Mock(side_effect=RuntimeError("keyboard stuck"))
        await self._enable_with_fakes(hid_gadgets, keyboard, mouse, consumer)

        await hid_gadgets.release_all()

        keyboard.release_all.assert_called_once_with()
        self.assertEqual(mouse.release_all_calls, 1)
        self.assertEqual(consumer.release_calls, 1)

    async def test_enable_clears_published_refs_before_rebuild(self) -> None:
        hid_gadgets = HidGadgets()
        await self._enable_with_fakes(hid_gadgets, _FakeKeyboard(), _FakeMouse(), _FakeConsumer())

        with patch.object(hid_gadgets, "prune_stale_hidg_nodes"):
            with patch("bluetooth_2_usb.gadgets.manager.rebuild_gadget", side_effect=RuntimeError("rebuild failed")):
                with self.assertRaisesRegex(RuntimeError, "rebuild failed"):
                    await hid_gadgets.enable()

        self.assertIsNone(hid_gadgets.keyboard)
        self.assertIsNone(hid_gadgets.mouse)
        self.assertIsNone(hid_gadgets.consumer)

    async def test_declared_hidg_paths_use_declared_function_indexes(self) -> None:
        devices = (SimpleNamespace(function_index=2), SimpleNamespace(function_index=7))
        with patch(
            "bluetooth_2_usb.gadgets.manager.build_default_layout", return_value=SimpleNamespace(devices=devices)
        ):
            paths = HidGadgets().declared_hidg_paths()

        self.assertEqual(paths, (Path("/dev/hidg2"), Path("/dev/hidg7")))

    async def test_validate_hidg_nodes_uses_kernel_reported_device_paths(self) -> None:
        hid_gadgets = HidGadgets()
        device = SimpleNamespace(name="mouse", path="/dev/hidg9", get_device_path=Mock(return_value="/dev/hidg1"))
        stats = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_rdev=0)

        with patch.object(Path, "stat", return_value=stats) as path_stat:
            with patch("bluetooth_2_usb.gadgets.manager.os.open", return_value=7) as open_path:
                with patch("bluetooth_2_usb.gadgets.manager.os.close"):
                    await hid_gadgets.validate_hidg_nodes([device], timeout_sec=0, poll_interval_sec=0)

        path_stat.assert_called_once_with()
        open_path.assert_called_once_with(Path("/dev/hidg9"), os.O_WRONLY | os.O_NONBLOCK)

    async def test_default_layout_uses_strict_keyboard_and_extended_mouse_consumer(self) -> None:
        layout = build_default_layout()

        self.assertEqual(len(layout.devices), 3)
        self.assertEqual(bytes(layout.devices[0].descriptor), DEFAULT_KEYBOARD_DESCRIPTOR)
        self.assertEqual(bytes(layout.devices[1].descriptor), DEFAULT_MOUSE_DESCRIPTOR)
        self.assertEqual(DEFAULT_MOUSE_DESCRIPTOR.count(bytes((0x09, 0x48))), 2)
        self.assertEqual(tuple(layout.devices[1].report_ids), (0,))
        self.assertEqual(tuple(layout.devices[1].in_report_lengths), (7,))
        self.assertEqual(tuple(layout.devices[1].out_report_lengths), (0,))
        self.assertEqual(layout.devices[1].configfs_report_length, 8)
        self.assertEqual(bytes(layout.devices[2].descriptor), bytes(usb_hid.Device.CONSUMER_CONTROL.descriptor))
        self.assertEqual(layout.bcd_device, DEFAULT_BCD_DEVICE)
        self.assertEqual(layout.product_name, "USB Combo Device")
        self.assertEqual(layout.serial_number, "213374badcafe")
        self.assertEqual(layout.max_power, 100)
        self.assertEqual(layout.bm_attributes, COMBO_BM_ATTRIBUTES)
        self.assertEqual(layout.max_speed, "high-speed")
        self.assertTrue(layout.devices[0].wakeup_on_write)
        self.assertFalse(layout.devices[1].wakeup_on_write)
        self.assertFalse(layout.devices[2].wakeup_on_write)

    async def test_gadget_hid_device_passes_protocol_and_subclass_when_required(self) -> None:
        init_calls = []

        def fake_device_init(self, **kwargs) -> None:
            init_calls.append(kwargs)
            if "subclass" not in kwargs or "protocol" not in kwargs:
                raise TypeError(
                    "Device.__init__() missing 2 required keyword-only arguments: " + "'subclass' and 'protocol'"
                )

        with patch.object(usb_hid.Device, "__init__", fake_device_init):
            GadgetHidDevice.from_existing(usb_hid.Device.BOOT_KEYBOARD, function_index=0, protocol=1, subclass=1)

        self.assertEqual(len(init_calls), 1)
        self.assertEqual(init_calls[0]["protocol"], 1)
        self.assertEqual(init_calls[0]["subclass"], 1)

    async def test_prune_stale_hidg_nodes_removes_regular_files(self) -> None:
        hid_gadgets = HidGadgets()
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "hidg1"
            stale.write_text("stale", encoding="utf-8")
            with patch.object(hid_gadgets, "declared_hidg_paths", return_value=(stale,)):
                hid_gadgets.prune_stale_hidg_nodes()
            self.assertFalse(stale.exists())

    async def test_prune_stale_hidg_nodes_ignores_unlink_race(self) -> None:
        hid_gadgets = HidGadgets()
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "hidg1"
            stale.write_text("stale", encoding="utf-8")
            with patch.object(hid_gadgets, "declared_hidg_paths", return_value=(stale,)):
                with patch.object(Path, "unlink", side_effect=FileNotFoundError):
                    hid_gadgets.prune_stale_hidg_nodes()

    async def test_validate_hidg_nodes_rejects_regular_files(self) -> None:
        hid_gadgets = HidGadgets()
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "hidg1"
            bad.write_text("not-a-device", encoding="utf-8")
            device = SimpleNamespace(name="mouse", path=str(bad))
            with self.assertRaisesRegex(RuntimeError, re.escape(str(bad))):
                await hid_gadgets.validate_hidg_nodes([device], timeout_sec=0, poll_interval_sec=0)

    async def test_validate_hidg_nodes_waits_for_delayed_nodes(self) -> None:
        hid_gadgets = HidGadgets()

        with patch.object(
            hid_gadgets, "collect_invalid_hidg_nodes", side_effect=[["/dev/hidg0 (missing)"], []]
        ) as collect_invalid:
            with patch("bluetooth_2_usb.gadgets.manager.asyncio.sleep") as sleep:
                await hid_gadgets.validate_hidg_nodes([object()], timeout_sec=0.1, poll_interval_sec=0.01)

        self.assertEqual(collect_invalid.call_count, 2)
        sleep.assert_called_once_with(0.01)

    async def test_collect_invalid_hidg_nodes_rejects_unopenable_character_devices(self) -> None:
        hid_gadgets = HidGadgets()
        path = Path("/dev/hidg0")
        stats = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_rdev=0)

        device = SimpleNamespace(name="mouse", path=str(path))
        with patch.object(Path, "stat", return_value=stats):
            with patch("bluetooth_2_usb.gadgets.manager.os.O_NONBLOCK", 0, create=True):
                with patch(
                    "bluetooth_2_usb.gadgets.manager.os.open", side_effect=OSError(errno.ENODEV, "No such device")
                ):
                    invalid_paths = hid_gadgets.collect_invalid_hidg_nodes([device])

        self.assertEqual(invalid_paths, [f"{path} (No such device)"])

    async def test_rebuild_gadget_writes_default_power_and_identity(self) -> None:
        layout = build_default_layout()
        with tempfile.TemporaryDirectory() as tmpdir:
            gadget_root = Path(tmpdir) / "usb_gadget" / "adafruit-blinka"
            with patch("bluetooth_2_usb.gadgets.config.GADGET_ROOT", gadget_root):
                with patch("bluetooth_2_usb.gadgets.config._resolve_udc_name", return_value="dummy.udc"):
                    with patch.object(usb_hid, "gadget_root", str(gadget_root)):
                        rebuild_gadget(layout)

            self.assertEqual(
                (gadget_root / "strings" / LANGUAGE_ID / "product").read_text(encoding="utf-8").strip(),
                "USB Combo Device",
            )
            self.assertEqual(
                (gadget_root / "strings" / LANGUAGE_ID / "serialnumber").read_text(encoding="utf-8").strip(),
                "213374badcafe",
            )
            self.assertEqual((gadget_root / "bcdDevice").read_text(encoding="utf-8").strip(), DEFAULT_BCD_DEVICE)
            self.assertEqual(
                (gadget_root / "configs" / CONFIG_NAME / "MaxPower").read_text(encoding="utf-8").strip(), "100"
            )
            self.assertEqual(
                (gadget_root / "configs" / CONFIG_NAME / "bmAttributes").read_text(encoding="utf-8").strip(),
                hex(COMBO_BM_ATTRIBUTES),
            )
            self.assertEqual(
                (gadget_root / "configs" / CONFIG_NAME / "strings" / LANGUAGE_ID / "configuration")
                .read_text(encoding="utf-8")
                .strip(),
                "Config 1: HID relay",
            )
            self.assertEqual((gadget_root / "max_speed").read_text(encoding="utf-8").strip(), "high-speed")
            self.assertEqual(
                (gadget_root / "functions/hid.usb0/report_length").read_text(encoding="utf-8").strip(), "8"
            )
            self.assertEqual(
                (gadget_root / "functions/hid.usb1/report_length").read_text(encoding="utf-8").strip(), "8"
            )
            self.assertEqual(
                (gadget_root / "functions/hid.usb2/report_length").read_text(encoding="utf-8").strip(), "2"
            )

    async def test_rebuild_gadget_sets_wakeup_on_write_only_when_supported(self) -> None:
        layout = build_default_layout()
        with tempfile.TemporaryDirectory() as tmpdir:
            gadget_root = Path(tmpdir) / "usb_gadget" / "adafruit-blinka"
            keyboard_wakeup = gadget_root / "functions/hid.usb0/wakeup_on_write"
            mouse_wakeup = gadget_root / "functions/hid.usb1/wakeup_on_write"

            def fake_exists(path: Path) -> bool:
                if path in {keyboard_wakeup, mouse_wakeup}:
                    return True
                return original_exists(path)

            original_exists = type(keyboard_wakeup).exists

            with patch("bluetooth_2_usb.gadgets.config.GADGET_ROOT", gadget_root):
                with patch("bluetooth_2_usb.gadgets.config._resolve_udc_name", return_value="dummy.udc"):
                    with patch.object(usb_hid, "gadget_root", str(gadget_root)):
                        with patch.object(type(keyboard_wakeup), "exists", fake_exists):
                            rebuild_gadget(layout)

            self.assertEqual(keyboard_wakeup.read_text(encoding="utf-8").strip(), "1")
            self.assertEqual(mouse_wakeup.read_text(encoding="utf-8").strip(), "0")
            self.assertFalse((gadget_root / "functions/hid.usb2/wakeup_on_write").exists())

    async def test_remove_owned_gadgets_removes_default_and_project_gadget_trees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            configfs_root = Path(tmpdir) / "usb_gadget"
            gadget_root = configfs_root / "adafruit-blinka"
            project_root = configfs_root / "bluetooth_2_usb-test"
            for root in (gadget_root, project_root):
                (root / "configs/c.1").mkdir(parents=True)
                (root / "functions/hid.usb0").mkdir(parents=True)
                (root / "UDC").write_text("dummy.udc\n", encoding="utf-8")
                (root / "functions/hid.usb0/report_length").write_text("8\n", encoding="utf-8")
                (root / "configs/c.1/hid.usb0").symlink_to(root / "functions/hid.usb0")

            with patch("bluetooth_2_usb.gadgets.config.GADGET_ROOT", gadget_root):
                remove_owned_gadgets()

            self.assertFalse(gadget_root.exists())
            self.assertFalse(project_root.exists())

    async def test_from_existing_preserves_wakeup_on_write_by_default(self) -> None:
        base_device = GadgetHidDevice.from_existing(
            usb_hid.Device.BOOT_KEYBOARD,
            function_index=0,
            protocol=1,
            subclass=1,
            descriptor=DEFAULT_KEYBOARD_DESCRIPTOR,
            configfs_report_length=8,
            wakeup_on_write=True,
        )

        cloned = GadgetHidDevice.from_existing(base_device, function_index=1, protocol=0, subclass=0)

        self.assertTrue(cloned.wakeup_on_write)
        self.assertEqual(cloned.configfs_report_length, 8)


class GadgetDescriptorContractTest(unittest.TestCase):
    def test_default_layout_uses_hid_descriptor_contract(self) -> None:
        layout = build_default_layout()

        self.assertEqual(bytes(layout.devices[0].descriptor), DEFAULT_KEYBOARD_DESCRIPTOR)
        self.assertEqual(bytes(layout.devices[1].descriptor), DEFAULT_MOUSE_DESCRIPTOR)
        self.assertEqual(layout.devices[1].in_report_lengths, (MOUSE_IN_REPORT_LENGTH,))
        self.assertEqual(layout.devices[1].configfs_report_length, MOUSE_CONFIGFS_REPORT_LENGTH)
