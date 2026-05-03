import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bluetooth_2_usb.evdev import ecodes
from bluetooth_2_usb.relay.gate import RelayGate
from bluetooth_2_usb.relay.supervisor import RelaySupervisor
from bluetooth_2_usb.runtime.events import ShutdownRequested, UdcState, UdcStateChanged


class _FakeKeyboard:
    def __init__(self) -> None:
        self.presses = []
        self.releases = []

    async def press(self, key_id) -> None:
        self.presses.append(key_id)

    async def release(self, key_id) -> None:
        self.releases.append(key_id)

    async def release_all(self) -> None:
        self.releases.append("all")


class _FakeMouse:
    def __init__(self) -> None:
        self.moves = []
        self.releases = []

    async def move(self, x=0, y=0, wheel=0, pan=0) -> None:
        self.moves.append((x, y, wheel, pan))

    async def press(self, key_id) -> None:
        self.releases.append(("press", key_id))

    async def release(self, key_id) -> None:
        self.releases.append(("release", key_id))

    async def release_all(self) -> None:
        self.releases.append("all")


class _FakeConsumer:
    async def press(self, _key_id) -> None:
        return None

    async def release(self) -> None:
        return None


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


class _FakeKeyEvent:
    key_down = 1
    key_hold = 2
    key_up = 0

    def __init__(self, scancode: int, keystate: int) -> None:
        self.scancode = scancode
        self.keystate = keystate


class _FakeRelEvent:
    def __init__(self, code: int, value: int) -> None:
        self.event = SimpleNamespace(type=ecodes.EV_REL, code=code, value=value)


class _FakeSynEvent:
    type = ecodes.EV_SYN
    code = ecodes.SYN_REPORT
    value = 0


class _FakeInputDevice:
    path = "/dev/input/event-test"
    name = "integration keyboard mouse"
    phys = ""
    uniq = ""

    def __init__(self, event_queue: asyncio.Queue) -> None:
        self._event_queue = event_queue
        self.close_calls = 0

    def capabilities(self, verbose: bool = False):
        del verbose
        return {ecodes.EV_KEY: [], ecodes.EV_REL: []}

    async def async_read_loop(self):
        while True:
            event = await self._event_queue.get()
            if event is None:
                return
            yield event

    def close(self) -> None:
        self.close_calls += 1


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("condition was not met")
        await asyncio.sleep(0)


class RuntimeRelayIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_supervisor_relays_events_releases_on_disconnect_and_stops_cleanly(self) -> None:
        runtime_events: asyncio.Queue = asyncio.Queue()
        input_events: asyncio.Queue = asyncio.Queue()
        device = _FakeInputDevice(input_events)
        gate = RelayGate()
        hid_gadgets = _FakeHidGadgets()

        with (
            patch("bluetooth_2_usb.relay.supervisor.list_input_devices", return_value=[device]),
            patch("bluetooth_2_usb.hid.dispatch.categorize", side_effect=lambda event: event),
            patch("bluetooth_2_usb.hid.dispatch.KeyEvent", _FakeKeyEvent),
            patch("bluetooth_2_usb.hid.dispatch.RelEvent", _FakeRelEvent),
        ):
            async with asyncio.TaskGroup() as task_group:
                supervisor = RelaySupervisor(
                    hid_gadgets=hid_gadgets, relay_gate=gate, task_group=task_group, auto_discover=True
                )
                run_task = task_group.create_task(supervisor.run(runtime_events))

                runtime_events.put_nowait(UdcStateChanged(UdcState.CONFIGURED))
                input_events.put_nowait(_FakeKeyEvent(ecodes.KEY_A, _FakeKeyEvent.key_down))
                input_events.put_nowait(_FakeKeyEvent(ecodes.KEY_A, _FakeKeyEvent.key_up))
                input_events.put_nowait(_FakeRelEvent(ecodes.REL_X, 7))
                input_events.put_nowait(_FakeRelEvent(ecodes.REL_Y, -3))
                input_events.put_nowait(_FakeSynEvent())
                await _wait_until(lambda: hid_gadgets.mouse.moves == [(7, -3, 0, 0)])

                runtime_events.put_nowait(UdcStateChanged(UdcState.NOT_ATTACHED))
                await _wait_until(lambda: hid_gadgets.release_all_calls == 1)
                input_events.put_nowait(_FakeKeyEvent(ecodes.KEY_B, _FakeKeyEvent.key_down))
                await asyncio.sleep(0)

                runtime_events.put_nowait(ShutdownRequested("test"))
                await asyncio.wait_for(run_task, timeout=1)

        self.assertEqual(hid_gadgets.keyboard.presses, [4])
        self.assertEqual(hid_gadgets.keyboard.releases, [4, "all"])
        self.assertEqual(device.close_calls, 1)
