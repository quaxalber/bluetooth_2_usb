from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass

from ..gadgets.identity import load_or_create_usb_identity
from ..gadgets.manager import HidGadgets
from ..logging import get_logger
from ..relay.gate import RelayGate
from ..relay.jiggler import JigglerToggler, MouseJiggler
from ..relay.led import KeyboardLedBlinker, resolve_led_name
from ..relay.shortcut import ShortcutToggler
from ..relay.supervisor import RelaySupervisor
from .config import RuntimeConfig
from .event_source import RuntimeEventSource
from .events import RuntimeEvent, ShutdownRequested
from .status import StatusPublisher

logger = get_logger(__name__)


GRACEFUL_SHUTDOWN_TIMEOUT_SEC = 4.0


@dataclass(slots=True)
class _SignalHandlers:
    previous_handlers: dict[int, signal.Handlers]
    loop_handled_signals: tuple[int, ...]


def handled_shutdown_signals() -> tuple[signal.Signals, ...]:
    signals = [signal.SIGINT, signal.SIGTERM]
    for optional_name in ("SIGHUP", "SIGQUIT"):
        optional_signal = getattr(signal, optional_name, None)
        if optional_signal is not None:
            signals.append(optional_signal)
    return tuple(signals)


class Runtime:
    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config
        self._events: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._event_source: RuntimeEventSource | None = None
        self._supervisor: RelaySupervisor | None = None

    async def run(self) -> None:
        relay_gate = RelayGate()
        identity = load_or_create_usb_identity()
        logger.info("Using USB gadget identity: product=%r serial=%r", identity.product_name, identity.serial_number)
        hid_gadgets = HidGadgets(identity)
        await hid_gadgets.enable()

        shortcut_toggler = self._build_shortcut_toggler(relay_gate)
        mouse_jiggler, jiggler_toggler, led_blinker = self._build_jiggler(hid_gadgets, relay_gate)
        self._event_source = RuntimeEventSource(self._events)
        status_publisher = StatusPublisher.from_environment(relay_gate, mouse_jiggler)
        if status_publisher is not None:
            logger.debug("Publishing runtime status to %s", status_publisher.path)
            status_publisher.start()

        handlers = self._install_signal_handlers()
        try:
            await self._run_tasks(
                self._event_source,
                hid_gadgets,
                relay_gate,
                shortcut_toggler,
                jiggler_toggler,
                mouse_jiggler,
                led_blinker,
            )
        finally:
            self._restore_signal_handlers(handlers)
            if status_publisher is not None:
                status_publisher.stop()

    def _build_supervisor(
        self,
        hid_gadgets: HidGadgets,
        relay_gate: RelayGate,
        shortcut_toggler: ShortcutToggler | None,
        jiggler_toggler: JigglerToggler | None,
        mouse_jiggler: MouseJiggler | None,
        led_blinker: KeyboardLedBlinker | None,
        task_group: asyncio.TaskGroup,
    ) -> RelaySupervisor:
        return RelaySupervisor(
            hid_gadgets=hid_gadgets,
            relay_gate=relay_gate,
            task_group=task_group,
            devices=list(self._config.devices),
            auto_relay=self._config.auto,
            grab=self._config.grab,
            shortcut_toggler=shortcut_toggler,
            jiggler_toggler=jiggler_toggler,
            mouse_jiggler=mouse_jiggler,
            led_blinker=led_blinker,
        )

    def _build_shortcut_toggler(self, relay_gate: RelayGate) -> ShortcutToggler | None:
        if not self._config.shortcut:
            return None

        shortcut_keys = set(self._config.shortcut)
        logger.debug("Configuring global interrupt shortcut: %s", shortcut_keys)
        return ShortcutToggler(shortcut_keys=shortcut_keys, relay_gate=relay_gate)

    def _build_jiggler(
        self, hid_gadgets: HidGadgets, relay_gate: RelayGate
    ) -> tuple[MouseJiggler | None, JigglerToggler | None, KeyboardLedBlinker | None]:
        if not self._config.mouse_jiggler:
            return None, None, None

        logger.debug("Configuring mouse jiggler (base_interval=120s, jitter=±15s)")
        mouse_jiggler = MouseJiggler(hid_gadgets=hid_gadgets, relay_gate=relay_gate)

        jiggler_toggler: JigglerToggler | None = None
        led_blinker: KeyboardLedBlinker | None = None
        if self._config.jiggler_shortcut:
            shortcut_keys = set(self._config.jiggler_shortcut)
            logger.debug("Configuring jiggler toggle shortcut: %s", shortcut_keys)
            jiggler_toggler = JigglerToggler(shortcut_keys=shortcut_keys, mouse_jiggler=mouse_jiggler)
            # Toggling the jiggler has no other visible feedback, so blink a
            # keyboard LED to confirm the shortcut was recognized.
            led_blinker = KeyboardLedBlinker(led=resolve_led_name(self._config.jiggler_led))

        return mouse_jiggler, jiggler_toggler, led_blinker

    async def _run_tasks(
        self,
        event_source: RuntimeEventSource,
        hid_gadgets: HidGadgets,
        relay_gate: RelayGate,
        shortcut_toggler: ShortcutToggler | None,
        jiggler_toggler: JigglerToggler | None,
        mouse_jiggler: MouseJiggler | None,
        led_blinker: KeyboardLedBlinker | None = None,
    ) -> None:
        event_source_task: asyncio.Task[None] | None = None
        supervisor_task: asyncio.Task[None] | None = None
        jiggler_task: asyncio.Task[None] | None = None
        supervisor: RelaySupervisor | None = None
        try:
            async with asyncio.TaskGroup() as task_group:
                supervisor = self._build_supervisor(
                    hid_gadgets, relay_gate, shortcut_toggler, jiggler_toggler, mouse_jiggler, led_blinker, task_group
                )
                self._supervisor = supervisor
                event_source_task = task_group.create_task(event_source.run(), name="runtime event source")
                supervisor_task = task_group.create_task(supervisor.run(self._events), name="relay supervisor")
                if mouse_jiggler is not None:
                    jiggler_task = task_group.create_task(mouse_jiggler.run(), name="mouse jiggler")
                done, pending = await asyncio.wait(
                    {event_source_task, supervisor_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    task.result()

                for task in pending:
                    if task is event_source_task:
                        event_source.stop()
                    if task is supervisor_task:
                        self._events.put_nowait(ShutdownRequested("runtime"))
                if jiggler_task is not None and not jiggler_task.done():
                    jiggler_task.cancel()
                await self._wait_for_shutdown(supervisor_task, event_source_task, jiggler_task)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Runtime task failed.")
            raise
        finally:
            event_source.stop()
            if supervisor is not None:
                self._events.put_nowait(ShutdownRequested("runtime cleanup"))
            if jiggler_task is not None and not jiggler_task.done():
                jiggler_task.cancel()
            await self._wait_for_shutdown(supervisor_task, event_source_task, jiggler_task)

    async def _wait_for_shutdown(
        self,
        supervisor_task: asyncio.Task[None] | None,
        event_source_task: asyncio.Task[None] | None,
        jiggler_task: asyncio.Task[None] | None = None,
    ) -> None:
        tasks = [task for task in (supervisor_task, event_source_task, jiggler_task) if task]
        if not tasks:
            return

        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SEC
            )
        except TimeoutError:
            logger.warning(
                "Runtime shutdown exceeded %.1fs; cancelling remaining tasks.", GRACEFUL_SHUTDOWN_TIMEOUT_SEC
            )
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _install_signal_handlers(self) -> _SignalHandlers:
        active_loop = asyncio.get_running_loop()
        previous_handlers: dict[int, signal.Handlers] = {}
        loop_handled_signals: list[int] = []

        def _enqueue_shutdown(sig_name: str) -> None:
            logger.debug("Received signal: %s. Enqueuing graceful shutdown.", sig_name)
            self._events.put_nowait(ShutdownRequested(sig_name))

        def _fallback_signal_handler(sig: int, frame) -> None:
            del frame
            _enqueue_shutdown(signal.Signals(sig).name)

        for handled_signal in handled_shutdown_signals():
            sig_name = signal.Signals(handled_signal).name
            previous_handlers[handled_signal] = signal.getsignal(handled_signal)
            add_signal_handler = getattr(active_loop, "add_signal_handler", None)
            if add_signal_handler is not None:
                try:
                    active_loop.add_signal_handler(handled_signal, _enqueue_shutdown, sig_name)
                    loop_handled_signals.append(handled_signal)
                    continue
                except (NotImplementedError, RuntimeError, ValueError):
                    pass
            signal.signal(handled_signal, _fallback_signal_handler)

        return _SignalHandlers(previous_handlers, tuple(loop_handled_signals))

    def _restore_signal_handlers(self, handlers: _SignalHandlers) -> None:
        active_loop = asyncio.get_running_loop()
        remove_signal_handler = getattr(active_loop, "remove_signal_handler", None)
        if remove_signal_handler is not None:
            for handled_signal in handlers.loop_handled_signals:
                remove_signal_handler(handled_signal)
        for handled_signal, previous_handler in handlers.previous_handlers.items():
            signal.signal(handled_signal, previous_handler)
