from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass

from .hid_gadgets import HidGadgets
from .logging import get_logger
from .relay_supervisor import RelaySupervisor
from .runtime_config import RuntimeConfig
from .runtime_event_source import RuntimeEventSource
from .runtime_events import RuntimeEvent, ShutdownRequested
from .shortcut_toggler import ShortcutToggler

logger = get_logger(__name__)


GRACEFUL_SHUTDOWN_TIMEOUT_SEC = 4.0


@dataclass(slots=True)
class _SignalHandlers:
    previous_handlers: dict[int, signal.Handlers]
    loop_handled_signals: tuple[int, ...]


def _handled_shutdown_signals() -> tuple[signal.Signals, ...]:
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
        relaying_active = asyncio.Event()
        hid_gadgets = HidGadgets()
        hid_gadgets.enable()

        shortcut_toggler = self._build_shortcut_toggler(relaying_active, hid_gadgets)
        self._supervisor = RelaySupervisor(
            hid_gadgets=hid_gadgets,
            device_identifiers=list(self._config.device_ids),
            auto_discover=self._config.auto_discover,
            grab_devices=self._config.grab_devices,
            relaying_active=relaying_active,
            shortcut_toggler=shortcut_toggler,
        )
        self._event_source = RuntimeEventSource(self._events, udc_path=self._config.udc_path)

        handlers = self._install_signal_handlers()
        try:
            await self._run_tasks(self._event_source, self._supervisor)
        finally:
            self._restore_signal_handlers(handlers)

    def _build_shortcut_toggler(
        self, relaying_active: asyncio.Event, hid_gadgets: HidGadgets
    ) -> ShortcutToggler | None:
        if not self._config.interrupt_shortcut:
            return None

        shortcut_keys = set(self._config.interrupt_shortcut)
        logger.debug("Configuring global interrupt shortcut: %s", shortcut_keys)
        return ShortcutToggler(shortcut_keys=shortcut_keys, relaying_active=relaying_active, hid_gadgets=hid_gadgets)

    async def _run_tasks(self, event_source: RuntimeEventSource, supervisor: RelaySupervisor) -> None:
        event_source_task = asyncio.create_task(event_source.run(), name="runtime event source")
        supervisor_task = asyncio.create_task(supervisor.run(self._events), name="relay supervisor")
        try:
            done, pending = await asyncio.wait(
                {event_source_task, supervisor_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()

            for task in pending:
                if task is event_source_task:
                    event_source.stop()
                if task is supervisor_task:
                    supervisor.request_shutdown()
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Runtime task failed.")
            raise
        finally:
            event_source.stop()
            supervisor.request_shutdown()
            await self._wait_for_shutdown(supervisor_task, event_source_task)

    async def _wait_for_shutdown(
        self, supervisor_task: asyncio.Task[None] | None, event_source_task: asyncio.Task[None] | None
    ) -> None:
        tasks = [task for task in (supervisor_task, event_source_task) if task]
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

        def _request_shutdown(sig_name: str) -> None:
            logger.debug("Received signal: %s. Requesting graceful shutdown.", sig_name)
            self._events.put_nowait(ShutdownRequested(sig_name))

        def _fallback_signal_handler(sig: int, frame) -> None:
            del frame
            _request_shutdown(signal.Signals(sig).name)

        for handled_signal in _handled_shutdown_signals():
            sig_name = signal.Signals(handled_signal).name
            add_signal_handler = getattr(active_loop, "add_signal_handler", None)
            if add_signal_handler is not None:
                try:
                    active_loop.add_signal_handler(handled_signal, _request_shutdown, sig_name)
                    loop_handled_signals.append(handled_signal)
                    continue
                except (NotImplementedError, RuntimeError, ValueError):
                    pass
            previous_handlers[handled_signal] = signal.getsignal(handled_signal)
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
