import asyncio
import signal


class ShutdownSignal:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def is_set(self) -> bool:
        return self._event.is_set()

    def request_stop(self) -> None:
        self._event.set()

    def install(self) -> None:
        loop = asyncio.get_running_loop()
        for value in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(value, self.request_stop)
            except (NotImplementedError, RuntimeError):
                signal.signal(value, lambda *_: self.request_stop())

    async def wait(self, timeout_seconds: float) -> None:
        try:
            await asyncio.wait_for(self._event.wait(), timeout_seconds)
        except TimeoutError:
            pass
